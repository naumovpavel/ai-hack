import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';
import { IDBFactory } from 'fake-indexeddb';

const root = resolve(import.meta.dirname, '..');
async function loadQueue(api, database = new IDBFactory()) {
  globalThis.indexedDB = database;
  const directory = await mkdtemp(join(tmpdir(), 'integrity-queue-test-'));
  const source = await readFile(
    join(root, 'lib/integrity-upload-queue.ts'),
    'utf8',
  );
  const compiled = ts.transpileModule(
    source.replace(
      /import \{[\s\S]+?\} from '\.\/integrity-capture-api';\s*/,
      'const integrityCaptureApi = globalThis.__integrityTestApi;\n',
    ),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ESNext,
      },
    },
  ).outputText;
  globalThis.__integrityTestApi = api;
  await writeFile(join(directory, 'queue.mjs'), compiled);
  const queue = await import(pathToFileURL(join(directory, 'queue.mjs')).href);
  await rm(directory, { recursive: true });
  delete globalThis.__integrityTestApi;
  return queue;
}
const chunk = (sequence) => ({
  clientChunkId: `chunk-${sequence}`,
  streamId: 'stream-one',
  kind: 'camera',
  sequence,
  startMs: sequence * 10_000,
  endMs: (sequence + 1) * 10_000,
  blob: new Blob(['webm-data'], { type: 'video/webm' }),
});

await test('event allowlist matches backend and all literal emitters, including worker', async () => {
  const api = await readFile(
    join(root, 'lib/integrity-capture-api.ts'),
    'utf8',
  );
  const backend = await readFile(
    join(root, '../backend/src/interview_api/workflow/integrity_schemas.py'),
    'utf8',
  );
  const clientTypes = [
    ...api
      .match(/INTEGRITY_EVENT_TYPES = \[([\s\S]+?)\] as const/)[1]
      .matchAll(/'([^']+)'/g),
  ].map((match) => match[1]);
  const backendTypes = [
    ...backend
      .match(
        /class IntegrityEvent\(ApiModel\):[\s\S]+?type: Literal\[([\s\S]+?)\]/,
      )[1]
      .matchAll(/"([^"]+)"/g),
  ].map((match) => match[1]);
  assert.deepEqual(
    [...clientTypes].sort((a, b) => a.localeCompare(b)),
    backendTypes.sort((a, b) => a.localeCompare(b)),
  );
  for (const filename of [
    'hooks/use-integrity-capture.ts',
    'hooks/use-integrity-events.ts',
    'hooks/use-integrity-face.ts',
    'components/product/candidate-app.tsx',
    'public/integrity/face-worker.js',
  ]) {
    const source = await readFile(join(root, filename), 'utf8');
    for (const match of source.matchAll(
      /(?:record|recordEvent|recordIntegrityEvent|track)\('([^']+)'/g,
    ))
      assert.ok(clientTypes.includes(match[1]), `${filename}: ${match[1]}`);
  }
  const events = await readFile(
    join(root, 'hooks/use-integrity-events.ts'),
    'utf8',
  );
  assert.ok(events.includes('visibilityState: document.visibilityState'));
});

await test('IndexedDB preserves unacknowledged blobs; retry uses same id and finish follows all chunks', async () => {
  const calls = [];
  let offline = true;
  const queue = await loadQueue({
    chunk: async (_, value) => {
      calls.push(value.clientChunkId);
      if (offline) throw new Error('offline');
    },
    events: async () => {},
    finish: async () => calls.push('finish'),
  });
  await queue.enqueueIntegrity(
    queue.queueEntry('interview-a', { kind: 'finish', value: 20_000 }),
  );
  await queue.enqueueIntegrity(
    queue.queueEntry('interview-a', { kind: 'chunk', value: chunk(0) }),
  );
  await assert.rejects(queue.flushIntegrityQueue('interview-a'));
  assert.equal(await queue.pendingIntegrityCount('interview-a'), 2);
  offline = false;
  await queue.flushIntegrityQueue('interview-a');
  assert.deepEqual(calls, ['chunk-0', 'chunk-0', 'finish']);
  assert.equal(await queue.pendingIntegrityCount('interview-a'), 0);
  await queue.flushIntegrityQueue('interview-a');
  assert.equal(calls.length, 3);
});

await test('rejected event cannot stall valid chunks or falsely finish incomplete upload', async () => {
  const calls = [];
  const queue = await loadQueue({
    events: async () => {
      const error = new Error('invalid legacy event');
      error.status = 422;
      throw error;
    },
    chunk: async (_, value) => calls.push(value.clientChunkId),
    finish: async () => calls.push('finish'),
  });
  await queue.enqueueIntegrity(
    queue.queueEntry('interview-a', {
      kind: 'event',
      value: {
        clientEventId: 'legacy',
        type: 'obsolete',
        offsetMs: 0,
        payload: {},
      },
    }),
  );
  await queue.enqueueIntegrity(
    queue.queueEntry('interview-a', { kind: 'chunk', value: chunk(0) }),
  );
  await queue.enqueueIntegrity(
    queue.queueEntry('interview-a', { kind: 'finish', value: 10_000 }),
  );
  await assert.rejects(queue.flushIntegrityQueue('interview-a'));
  assert.deepEqual(calls, ['chunk-0']);
  assert.equal(await queue.pendingIntegrityCount('interview-a'), 2);
});

await test('concurrent drains send each chunk once and never access another interview', async () => {
  const calls = [];
  const queue = await loadQueue({
    chunk: async (id, value) => {
      calls.push([id, value.clientChunkId]);
      await new Promise((resolve) => setTimeout(resolve, 5));
    },
    events: async () => {},
    finish: async () => {},
  });
  await queue.enqueueIntegrity(
    queue.queueEntry('interview-a', { kind: 'chunk', value: chunk(0) }),
  );
  await queue.enqueueIntegrity(
    queue.queueEntry('interview-b', { kind: 'chunk', value: chunk(1) }),
  );
  await Promise.all([
    queue.flushIntegrityQueue('interview-a'),
    queue.flushIntegrityQueue('interview-a'),
  ]);
  assert.deepEqual(calls, [['interview-a', 'chunk-0']]);
  assert.equal(await queue.pendingIntegrityCount('interview-b'), 1);
});

await test('tab reload reopens persisted records without changing media identifiers', async () => {
  const database = new IDBFactory();
  const calls = [];
  const api = {
    chunk: async (_, value) =>
      calls.push([
        value.clientChunkId,
        value.streamId,
        await value.blob.text(),
      ]),
    events: async () => {},
    finish: async () => {},
  };
  const beforeReload = await loadQueue(api, database);
  await beforeReload.enqueueIntegrity(
    beforeReload.queueEntry('interview-a', { kind: 'chunk', value: chunk(7) }),
  );
  // A fresh module has no in-memory map or previously opened database handle.
  const afterReload = await loadQueue(api, database);
  assert.equal(await afterReload.pendingIntegrityCount('interview-a'), 1);
  await afterReload.flushIntegrityQueue('interview-a');
  assert.deepEqual(calls, [['chunk-7', 'stream-one', 'webm-data']]);
  assert.equal(await afterReload.pendingIntegrityCount('interview-a'), 0);
});
