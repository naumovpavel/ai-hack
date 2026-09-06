import {
  integrityCaptureApi,
  type IntegrityChunk,
  type IntegrityEvent,
} from './integrity-capture-api';

type EntryBase = {
  id: string;
  interviewId: string;
  createdAt: number;
  expiresAt: number;
};
export type IntegrityQueueEntry = EntryBase &
  (
    | { kind: 'chunk'; value: IntegrityChunk }
    | { kind: 'event'; value: IntegrityEvent }
    | { kind: 'finish'; value: number }
  );
const DB_NAME = 'signal-integrity-uploads';
const STORE_NAME = 'pending';
let dbPromise: Promise<IDBDatabase> | undefined;
const flushPromises = new Map<string, Promise<number>>();
// Keep a failed IDB write in memory too; the caller surfaces the loss of durability.
const volatile = new Map<string, IntegrityQueueEntry>();

export function openIntegrityQueue() {
  if (!dbPromise)
    dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
      if (!globalThis.indexedDB) {
        reject(
          new Error(
            'Для надёжной записи нужен IndexedDB. Откройте интервью в обычном окне браузера.',
          ),
        );
        return;
      }
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore(STORE_NAME, { keyPath: 'id' });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => {
        dbPromise = undefined;
        reject(request.error);
      };
      request.onblocked = () => {
        dbPromise = undefined;
        reject(
          new Error(
            'Закройте старую вкладку интервью и повторите подключение.',
          ),
        );
      };
    });
  return dbPromise;
}

async function write(
  operation: 'put' | 'delete',
  value: IntegrityQueueEntry | string,
) {
  const db = await openIntegrityQueue();
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    if (operation === 'put') store.put(value);
    else store.delete(value as string);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () =>
      reject(transaction.error || new Error('Локальное хранилище недоступно.'));
  });
}

export async function enqueueIntegrity(entry: IntegrityQueueEntry) {
  volatile.set(entry.id, entry);
  await write('put', entry);
  volatile.delete(entry.id);
}

async function entries(interviewId: string) {
  const db = await openIntegrityQueue();
  const stored = await new Promise<IntegrityQueueEntry[]>((resolve, reject) => {
    const request = db.transaction(STORE_NAME).objectStore(STORE_NAME).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const combined = new Map(stored.map((entry) => [entry.id, entry]));
  for (const [key, entry] of volatile) combined.set(key, entry);
  const result: IntegrityQueueEntry[] = [];
  for (const entry of combined.values()) {
    if (entry.expiresAt < Date.now()) {
      await write('delete', entry.id);
      volatile.delete(entry.id);
    } else if (entry.interviewId === interviewId) result.push(entry);
  }
  // Finish is always last, even when a final dataavailable write completes late.
  return result.sort(
    (a, b) =>
      Number(a.kind === 'finish') - Number(b.kind === 'finish') ||
      a.createdAt - b.createdAt ||
      a.id.localeCompare(b.id),
  );
}

export async function pendingIntegrityCount(interviewId: string) {
  return (await entries(interviewId)).length;
}

export function flushIntegrityQueue(interviewId: string) {
  const existing = flushPromises.get(interviewId);
  if (existing) return existing;
  const promise = (async () => {
    const pending = await entries(interviewId);
    let failure: unknown;
    for (const entry of pending) {
      // Do not touch another candidate's queue; ownership is checked again server-side.
      if (entry.kind === 'finish' && failure) continue;
      try {
        if (entry.kind === 'chunk')
          await integrityCaptureApi.chunk(interviewId, entry.value);
        else if (entry.kind === 'event')
          await integrityCaptureApi.events(interviewId, [entry.value]);
        else {
          // A final MediaRecorder callback may have added a chunk after the snapshot.
          if (
            (await entries(interviewId)).some((item) => item.kind !== 'finish')
          )
            continue;
          await integrityCaptureApi.finish(interviewId, entry.value);
        }
        await write('delete', entry.id);
        volatile.delete(entry.id);
      } catch (error) {
        failure ||= error;
        // A malformed legacy event must not prevent valid recording chunks
        // from being delivered. Preserve it for a visible, retryable diagnostic.
        const status =
          error && typeof error === 'object' && 'status' in error
            ? error.status
            : 0;
        if (entry.kind !== 'event' || ![400, 413, 422].includes(Number(status)))
          break;
      }
    }
    if (failure) throw failure;
    return pendingIntegrityCount(interviewId);
  })().finally(() => {
    flushPromises.delete(interviewId);
  });
  flushPromises.set(interviewId, promise);
  return promise;
}

export function queueEntry(
  interviewId: string,
  payload: Pick<IntegrityQueueEntry, 'kind' | 'value'>,
): IntegrityQueueEntry {
  const now = Date.now();
  return {
    id: crypto.randomUUID(),
    interviewId,
    createdAt: now,
    expiresAt: now + 30 * 24 * 60 * 60 * 1000,
    ...payload,
  } as IntegrityQueueEntry;
}
