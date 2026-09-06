import { cp, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
const require = createRequire(import.meta.url);
const packageRoot = dirname(require.resolve('@mediapipe/tasks-vision'));
const target = resolve(import.meta.dirname, '../public/integrity/runtime');
await mkdir(target, { recursive: true });
await cp(
  resolve(packageRoot, 'vision_bundle.cjs'),
  resolve(target, 'vision_bundle.js'),
);
await cp(resolve(packageRoot, 'wasm'), resolve(target, 'wasm'), {
  recursive: true,
});
