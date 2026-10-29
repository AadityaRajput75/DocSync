import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { argumentsFor, applicationEnvironment, ensureUv, launch, prepareRuntime,
  sha256, verifyRuntime, withInstallLock } from '../lib/launcher.mjs';

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'docsync-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'runtime'));
  await writeFile(path.join(root, 'runtime/pyproject.toml'), 'example');
  const files = { 'pyproject.toml': sha256('example') };
  await writeFile(path.join(root, 'runtime-manifest.json'), JSON.stringify({ files, id: sha256(JSON.stringify(files)) }));
  return root;
}
test('empty invocation starts the guided flow; explicit commands are preserved', () => {
  assert.deepEqual(argumentsFor([]), ['run']);
  assert.deepEqual(argumentsFor(['review', '123', '--accept']), ['review', '123', '--accept']);
  assert.equal(applicationEnvironment({}).DOCSYNC_QDRANT_MODE, 'embedded');
  assert.equal(applicationEnvironment({ DOCSYNC_QDRANT_MODE: 'server' }).DOCSYNC_QDRANT_MODE, 'server');
});
test('modified or traversing runtime paths are rejected', async t => {
  const root = await fixture(t);
  await verifyRuntime(root);
  await writeFile(path.join(root, 'runtime/pyproject.toml'), 'tampered');
  await assert.rejects(verifyRuntime(root), /integrity/);
  const files = { '../secret': 'abc' };
  await writeFile(path.join(root, 'runtime-manifest.json'), JSON.stringify({ files, id: sha256(JSON.stringify(files)) }));
  await assert.rejects(verifyRuntime(root), /Invalid runtime path/);
});
test('runtime is isolated, cached, and setup does not inherit the Gemini key', async t => {
  const root = await fixture(t);
  const calls = [];
  const options = { home: path.join(root, 'cache'), env: { GEMINI_API_KEY: 'test-secret' }, ensure: async () => 'uv',
    run: async (command, args, opt) => {
      calls.push({ command, args, opt });
      assert.equal(opt.env.GEMINI_API_KEY, undefined);
      assert.equal(opt.env.UV_PYTHON_INSTALL_BIN, '0');
      assert.equal(opt.env.UV_PYTHON_INSTALL_REGISTRY, '0');
      assert.ok(opt.env.UV_PYTHON_INSTALL_DIR.startsWith(path.join(root, 'cache')));
      const python = path.join(opt.env.UV_PROJECT_ENVIRONMENT,
        process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
      await mkdir(path.dirname(python), { recursive: true });
      await writeFile(python, 'fixture');
      return 0;
    } };
  const first = await prepareRuntime(root, options);
  assert.equal(await prepareRuntime(root, options), first);
  assert.equal(calls.length, 1);
  assert.ok(calls[0].args.includes('--frozen'));
  assert.equal(calls[0].opt.cwd, root);
  assert.ok(!existsSync(path.join(root, '.venv')));
});
test('failed setup is not marked ready and releases its install lock', async t => {
  const root = await fixture(t);
  const home = path.join(root, 'cache');
  await assert.rejects(prepareRuntime(root, { home, ensure: async () => 'uv', run: async () => 1 }), /setup failed/);
  assert.ok(!existsSync(path.join(home, 'install.lock')));
});
test('launch keeps the target working directory and forwards exit status and cloud key only to app', async t => {
  const root = await fixture(t);
  const home = path.join(root, 'cache');
  const env = { GEMINI_API_KEY: 'test-only' };
  const code = await launch(['review', '--show'], { root, home, env, ensure: async () => 'uv',
    run: async (command, args, opt) => {
      if (command === 'uv') {
        const python = path.join(opt.env.UV_PROJECT_ENVIRONMENT,
          process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
        await mkdir(path.dirname(python), { recursive: true });
        await writeFile(python, 'fixture');
        return 0;
      }
      assert.deepEqual(args, ['-I', '-m', 'docsync', 'review', '--show']);
      assert.equal(opt.cwd, process.cwd());
      assert.equal(opt.env.GEMINI_API_KEY, 'test-only');
      return 23;
    } });
  assert.equal(code, 23);
});
test('uv download fails closed on checksum mismatch without running downloaded text', async t => {
  const root = await fixture(t);
  let ran = false;
  await assert.rejects(ensureUv(root, { env: {}, probe: () => ({ status: 1 }),
    fetcher: async () => new Response('untrusted script'), run: async () => { ran = true; } }), /checksum mismatch/);
  assert.equal(ran, false);
});
test('available uv avoids downloading the installer', async t => {
  const root = await fixture(t);
  assert.equal(await ensureUv(root, { env: {}, probe: () => ({ status: 0 }),
    fetcher: () => { throw new Error('should not download'); } }), 'uv');
});
test('parallel installs are serialized and clean up locks', async t => {
  const root = await fixture(t);
  const order = [];
  const first = withInstallLock(root, async () => {
    order.push(1);
    await new Promise(resolve => setTimeout(resolve, 50));
    order.push(2);
  });
  await new Promise(resolve => setTimeout(resolve, 20));
  const second = withInstallLock(root, async () => order.push(3));
  await Promise.all([first, second]);
  assert.deepEqual(order, [1, 2, 3]);
  assert.ok(!existsSync(path.join(root, 'install.lock')));
});
