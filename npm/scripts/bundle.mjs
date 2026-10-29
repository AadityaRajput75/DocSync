import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile, readdir, rm, writeFile, chmod } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.resolve(root, '..');
const destination = path.join(root, 'runtime');
// Exact build-owned destination; never remove the application source or user repository.
if (destination !== path.resolve(source, 'npm/runtime')) throw new Error('Invalid bundle destination');
await rm(destination, { recursive: true, force: true });
const files = {};
async function copy(relative) {
  const target = path.join(destination, relative);
  await mkdir(path.dirname(target), { recursive: true });
  await copyFile(path.join(source, relative), target);
  files[relative] = createHash('sha256').update(await readFile(target)).digest('hex');
}
for (const name of ['pyproject.toml', 'uv.lock', 'README.md']) await copy(name);
for (const name of (await readdir(path.join(source, 'src/docsync'))).sort()) {
  if (name.endsWith('.py')) await copy(`src/docsync/${name}`);
}
await writeFile(path.join(root, 'runtime-manifest.json'), JSON.stringify({
  id: createHash('sha256').update(JSON.stringify(files)).digest('hex'), files,
}, null, 2) + '\n');
await chmod(path.join(root, 'bin/docsync.mjs'), 0o755);
console.log(`Bundled ${Object.keys(files).length} allowlisted files. No user repositories, state, or credentials.`);
