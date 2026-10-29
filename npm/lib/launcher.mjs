import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile, unlink } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const packageRoot = fileURLToPath(new URL('../', import.meta.url));
export const UV_VERSION = '0.12.18';
const installers = {
  win32: { extension: 'ps1', sha256: '452b97dba048fd153b697a4d612bacdb6f1a29085f9691fd2bf869aeb9cca9eb' },
  unix: { extension: 'sh', sha256: 'e62a5ea089de9c6a9b1f767166c9f33194e18d350e9f375c6355fac3ba0fb42b' },
};
export const sha256 = data => createHash('sha256').update(data).digest('hex');
export function argumentsFor(args) { return args.length ? args : ['run']; }
export function runtimeHome(env = process.env) {
  return path.resolve(env.DOCSYNC_RUNTIME_HOME || path.join(
    env.LOCALAPPDATA || env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'docsync-runtime'));
}
export function applicationEnvironment(env = process.env) {
  return { ...env, DOCSYNC_QDRANT_MODE: env.DOCSYNC_QDRANT_MODE || 'embedded',
    PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
}

export function execute(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', windowsHide: true, shell: false, ...options });
    // Both parent and child receive Ctrl+C in a terminal. Keep the parent alive while Python cleans up.
    const interrupt = () => { if (process.platform !== 'win32') child.kill('SIGINT'); };
    process.on('SIGINT', interrupt);
    child.once('error', error => { process.off('SIGINT', interrupt); reject(error); });
    child.once('exit', (code, signal) => {
      process.off('SIGINT', interrupt);
      resolve(code ?? (signal === 'SIGINT' ? 130 : 1));
    });
  });
}

export async function verifyRuntime(root = packageRoot) {
  const manifest = JSON.parse(await readFile(path.join(root, 'runtime-manifest.json'), 'utf8'));
  const files = manifest.files;
  if (sha256(JSON.stringify(files)) !== manifest.id) throw new Error('Runtime manifest is invalid. Reinstall DocSync.');
  for (const [relative, expected] of Object.entries(files)) {
    if (relative.includes('\\') || relative.includes('..') || path.isAbsolute(relative)) {
      throw new Error('Invalid runtime path. Reinstall DocSync.');
    }
    if (sha256(await readFile(path.join(root, 'runtime', relative))) !== expected) {
      throw new Error(`Bundled runtime integrity check failed: ${relative}. Reinstall DocSync.`);
    }
  }
  return manifest;
}

export async function ensureUv(home, { env = process.env, run = execute, fetcher = fetch,
  probe = spawnSync, platform = process.platform } = {}) {
  const name = platform === 'win32' ? 'uv.exe' : 'uv';
  const installed = env.DOCSYNC_UV || 'uv';
  if (probe(installed, ['--version'], { windowsHide: true, stdio: 'ignore' }).status === 0) return installed;
  const destination = path.join(home, 'uv', UV_VERSION);
  const binary = path.join(destination, name);
  if (existsSync(binary)) return binary;
  const spec = platform === 'win32' ? installers.win32 : installers.unix;
  console.log(`Preparing DocSync runtime: downloading uv ${UV_VERSION} from Astral.`);
  const response = await fetcher(`https://astral.sh/uv/${UV_VERSION}/install.${spec.extension}`,
    { signal: AbortSignal.timeout(60000) });
  if (!response.ok) throw new Error('Cannot download uv. Check your connection or install uv from https://docs.astral.sh/uv/.');
  const script = Buffer.from(await response.arrayBuffer());
  if (sha256(script) !== spec.sha256) throw new Error('uv installer checksum mismatch. Installation stopped.');
  await mkdir(destination, { recursive: true });
  const installer = path.join(destination, `install.${spec.extension}`);
  await writeFile(installer, script);
  const installEnv = { ...env, UV_UNMANAGED_INSTALL: destination, UV_NO_MODIFY_PATH: '1' };
  delete installEnv.GEMINI_API_KEY;
  // PowerShell 7's inherited module path can break Windows PowerShell 5's startup.
  if (platform === 'win32') delete installEnv.PSModulePath;
  const command = platform === 'win32' ? 'powershell.exe' : 'sh';
  const args = platform === 'win32' ? ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', installer] : [installer];
  try {
    if (await run(command, args, { cwd: destination, env: installEnv }) !== 0 || !existsSync(binary)) {
      throw new Error('uv installation failed. Install uv manually, then retry docsync.');
    }
  } finally { await unlink(installer).catch(() => {}); }
  return binary;
}

export async function withInstallLock(home, operation) {
  await mkdir(home, { recursive: true });
  const lock = path.join(home, 'install.lock');
  const deadline = Date.now() + 20 * 60 * 1000;
  let announced = false;
  for (;;) {
    try { await writeFile(lock, String(process.pid), { flag: 'wx' }); break; }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      if (!announced) { console.log('Waiting for another DocSync runtime installation...'); announced = true; }
      if (Date.now() > deadline) throw new Error(`Installation lock timed out. If no installer is running, remove ${lock} and retry.`);
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
  try { return await operation(); }
  finally { await unlink(lock).catch(() => {}); }
}

export async function prepareRuntime(root = packageRoot, { env = process.env, run = execute,
  ensure = ensureUv, home = runtimeHome(env) } = {}) {
  const manifest = await verifyRuntime(root);
  // Include install location: editable Python metadata points to this particular npm installation.
  const identity = sha256(manifest.id + path.resolve(root)).slice(0, 20);
  const environment = path.join(home, `python-${identity}`);
  const python = path.join(environment, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const ready = path.join(environment, '.docsync-ready');
  if (existsSync(python) && existsSync(ready)) return python;
  return withInstallLock(home, async () => {
    if (existsSync(python) && existsSync(ready)) return python;
    const uv = await ensure(home, { env });
    const setupEnv = { ...env, UV_PROJECT_ENVIRONMENT: environment,
      UV_CACHE_DIR: path.join(home, 'uv-cache'), UV_PYTHON_INSTALL_DIR: path.join(home, 'python'),
      UV_PYTHON_INSTALL_BIN: '0', UV_PYTHON_INSTALL_REGISTRY: '0', UV_NO_CONFIG: '1' };
    delete setupEnv.GEMINI_API_KEY;
    console.log('Preparing isolated Python 3.12 and DocSync dependencies. First launch needs internet.');
    const code = await run(uv, ['sync', '--frozen', '--no-dev', '--python', '3.12',
      '--project', path.join(root, 'runtime')], { cwd: root, env: setupEnv });
    if (code !== 0 || !existsSync(python)) throw new Error('Runtime setup failed. Check the messages above and retry docsync.');
    await writeFile(ready, manifest.id);
    return python;
  });
}

export async function launch(args, options = {}) {
  const python = await prepareRuntime(options.root || packageRoot, options);
  return (options.run || execute)(python, ['-I', '-m', 'docsync', ...argumentsFor(args)], {
    cwd: process.cwd(), env: applicationEnvironment(options.env || process.env),
  });
}
