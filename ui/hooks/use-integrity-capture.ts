'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  integrityCaptureApi,
  type CaptureHealth,
} from '@/lib/integrity-capture-api';
import {
  enqueueIntegrity,
  flushIntegrityQueue,
  openIntegrityQueue,
  pendingIntegrityCount,
  queueEntry,
} from '@/lib/integrity-upload-queue';
import {
  useIntegrityEvents,
  type RecordIntegrityEvent,
} from './use-integrity-events';
import { useIntegrityFace } from './use-integrity-face';

export async function requestIntegrityScreen(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getDisplayMedia)
    throw new Error('Для интервью нужен браузер с демонстрацией всего экрана.');
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { displaySurface: 'monitor', frameRate: { ideal: 10, max: 15 } },
    audio: false,
  });
  const surface = stream.getVideoTracks()[0]?.getSettings().displaySurface;
  if (surface !== 'monitor') {
    stream.getTracks().forEach((track) => track.stop());
    throw new Error(
      'Выберите «Весь экран» в окне демонстрации. Вкладка или отдельное окно не подходят.',
    );
  }
  return stream;
}

function liveTrack(stream: MediaStream | null, kind: 'audio' | 'video') {
  return Boolean(
    stream
      ?.getTracks()
      .some(
        (track) =>
          track.kind === kind &&
          track.readyState === 'live' &&
          track.enabled &&
          !track.muted,
      ),
  );
}
function mimeType() {
  return [
    'video/webm;codecs=vp8,opus',
    'video/webm;codecs=vp9,opus',
    'video/mp4',
    'video/webm',
  ].find((mime) => MediaRecorder.isTypeSupported(mime));
}

export function useIntegrityCapture(
  interviewId: string | undefined,
  enabled: boolean,
) {
  const [active, setActive] = useState(false);
  const [camera, setCamera] = useState<MediaStream | null>(null);
  const [screen, setScreen] = useState<MediaStream | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [pendingUploads, setPendingUploads] = useState(0);
  const [uploadError, setUploadError] = useState('');
  const sessionRef = useRef(false);
  const activeRef = useRef(false);
  const cameraRef = useRef<MediaStream | null>(null);
  const screenRef = useRef<MediaStream | null>(null);
  const recorders = useRef<MediaRecorder[]>([]);
  const recorderStops = useRef(new Map<MediaRecorder, Promise<void>>());
  const clock = useRef({ base: 0, started: 0 });
  const pendingWrites = useRef(new Set<Promise<void>>());
  const heartbeatChain = useRef<Promise<unknown>>(Promise.resolve());
  const finishRef = useRef<Promise<void> | null>(null);
  const getOffsetMs = useCallback(
    () =>
      Math.max(
        0,
        Math.round(
          clock.current.base +
            (clock.current.started
              ? performance.now() - clock.current.started
              : 0),
        ),
      ),
    [],
  );

  const flush = useCallback(async () => {
    if (!enabled || !interviewId) return;
    try {
      setPendingUploads(await pendingIntegrityCount(interviewId));
      if (!navigator.onLine) return;
      const left = await flushIntegrityQueue(interviewId);
      setPendingUploads(left);
      if (!left) setUploadError('');
    } catch {
      setUploadError(
        'Запись ожидает загрузки. Не закрывайте страницу: отправка повторится при восстановлении связи.',
      );
    }
  }, [enabled, interviewId]);

  const enqueue = useCallback(
    (payload: Parameters<typeof queueEntry>[1]) => {
      if (!interviewId) return;
      const promise = enqueueIntegrity(queueEntry(interviewId, payload)).catch(
        () => {
          setUploadError(
            'Не удалось сохранить запись в памяти браузера. Освободите место и не закрывайте эту страницу до загрузки.',
          );
        },
      );
      pendingWrites.current.add(promise);
      void promise.finally(() => pendingWrites.current.delete(promise));
    },
    [interviewId],
  );

  const recordEvent: RecordIntegrityEvent = useCallback(
    (type, payload = {}, durationMs, offsetMs, questionId) => {
      if (!enabled || !sessionRef.current) return;
      enqueue({
        kind: 'event',
        value: {
          clientEventId: crypto.randomUUID(),
          type,
          payload,
          offsetMs: offsetMs ?? getOffsetMs(),
          ...(durationMs !== undefined ? { durationMs } : {}),
          ...(questionId ? { questionId } : {}),
        },
      });
    },
    [enabled, enqueue, getOffsetMs],
  );

  const getHealth = useCallback(
    (): CaptureHealth => ({
      cameraActive:
        liveTrack(cameraRef.current, 'video') &&
        recorders.current[0]?.state === 'recording',
      microphoneActive:
        liveTrack(cameraRef.current, 'audio') &&
        recorders.current[0]?.state === 'recording',
      screenActive:
        liveTrack(screenRef.current, 'video') &&
        recorders.current[1]?.state === 'recording',
      displaySurface:
        screenRef.current?.getVideoTracks()[0]?.getSettings().displaySurface ||
        null,
    }),
    [],
  );

  const checkHealth = useCallback(() => {
    if (!activeRef.current || !interviewId) return;
    const health = getHealth();
    const captureLost =
      !health.cameraActive ||
      !health.microphoneActive ||
      !health.screenActive ||
      health.displaySurface !== 'monitor';
    setBlocked(captureLost);
    if (captureLost) {
      // End the continuous streams at the real loss boundary. Restoration
      // creates new stream IDs, so unavailable time cannot look like a frozen
      // but current camera/screen frame in the playback manifest.
      for (const recorder of recorders.current) {
        if (recorder.state !== 'inactive') recorder.stop();
      }
    }
    heartbeatChain.current = heartbeatChain.current
      .catch(() => undefined)
      .then(async () => {
        if (!activeRef.current) return;
        // Re-read at dispatch so a delayed heartbeat cannot undo a restoration.
        await integrityCaptureApi.heartbeat(
          interviewId,
          getHealth(),
          getOffsetMs(),
        );
      })
      .catch(() => {
        /* Server heartbeat expiry enforces the same gate offline. */
      });
  }, [getHealth, getOffsetMs, interviewId]);

  const stopRecorders = useCallback(async () => {
    const running = recorders.current;
    recorders.current = [];
    await Promise.all(
      running.map(async (recorder) => {
        if (recorder.state !== 'inactive') recorder.stop();
        await recorderStops.current.get(recorder);
        recorderStops.current.delete(recorder);
      }),
    );
    await Promise.all(pendingWrites.current);
  }, []);

  const syncHealth = useCallback(async () => {
    checkHealth();
    await heartbeatChain.current;
  }, [checkHealth]);

  const pause = useCallback(async () => {
    activeRef.current = false;
    setActive(false);
    await stopRecorders();
    screenRef.current?.getTracks().forEach((track) => track.stop());
    setScreen(null);
    screenRef.current = null;
    setBlocked(true);
    if (sessionRef.current && interviewId) {
      recordEvent('capture_stopped', { technical: true });
      await integrityCaptureApi
        .heartbeat(interviewId, getHealth(), getOffsetMs())
        .catch(() => undefined);
    }
  }, [getHealth, getOffsetMs, interviewId, recordEvent, stopRecorders]);

  const start = useCallback(
    async (cameraStream: MediaStream, screenStream: MediaStream) => {
      if (!enabled || !interviewId) return;
      await openIntegrityQueue();
      if (
        !liveTrack(cameraStream, 'video') ||
        !liveTrack(cameraStream, 'audio') ||
        !liveTrack(screenStream, 'video') ||
        screenStream.getVideoTracks()[0]?.getSettings().displaySurface !==
          'monitor'
      )
        throw new Error(
          'Для продолжения нужны камера, микрофон и демонстрация всего экрана.',
        );
      activeRef.current = false;
      await stopRecorders();
      const requestStarted = performance.now();
      const session = await integrityCaptureApi.start(
        interviewId,
        {
          cameraActive: true,
          microphoneActive: true,
          screenActive: true,
          displaySurface: 'monitor',
        },
        crypto.randomUUID(),
      );
      // The server owns session time across tab reloads. Add half the measured RTT.
      clock.current = {
        base: session.elapsedMs + (performance.now() - requestStarted) / 2,
        started: performance.now(),
      };
      sessionRef.current = true;
      finishRef.current = null;
      cameraRef.current = cameraStream;
      screenRef.current = screenStream;
      setCamera(cameraStream);
      setScreen(screenStream);
      const mime = mimeType();
      try {
        for (const [kind, media] of [
          ['camera', cameraStream],
          ['screen', new MediaStream(screenStream.getVideoTracks())],
        ] as const) {
          const recorder = new MediaRecorder(media, {
            ...(mime ? { mimeType: mime } : {}),
            videoBitsPerSecond: kind === 'screen' ? 1_000_000 : 500_000,
            audioBitsPerSecond: 48_000,
          });
          recorderStops.current.set(
            recorder,
            new Promise<void>((resolve) => {
              recorder.addEventListener('stop', () => resolve(), {
                once: true,
              });
            }),
          );
          // Every recorder instance is a new independently decodable stream.
          const streamId = crypto.randomUUID();
          let sequence = 0;
          let previousOffset = getOffsetMs();
          recorder.addEventListener('dataavailable', (event) => {
            if (!event.data.size) return;
            const endMs = Math.max(previousOffset + 1, getOffsetMs());
            enqueue({
              kind: 'chunk',
              value: {
                clientChunkId: crypto.randomUUID(),
                streamId,
                kind,
                sequence: sequence++,
                startMs: previousOffset,
                endMs,
                blob: event.data,
              },
            });
            previousOffset = endMs;
            void Promise.all(pendingWrites.current).then(flush);
          });
          recorder.addEventListener('error', () => {
            recordEvent('technical_error', { kind, technical: true });
            checkHealth();
          });
          recorder.addEventListener('stop', () => {
            if (activeRef.current) {
              recordEvent('capture_stopped', { kind, technical: true });
              checkHealth();
            }
          });
          recorder.start(10_000);
          recorders.current.push(recorder);
          recordEvent('capture_restored', { kind, streamId, technical: true });
        }
      } catch (error) {
        await stopRecorders();
        setBlocked(true);
        throw error;
      }
      activeRef.current = true;
      setActive(true);
      setBlocked(false);
      checkHealth();
      void flush();
    },
    [
      checkHealth,
      enabled,
      enqueue,
      flush,
      getOffsetMs,
      interviewId,
      recordEvent,
      stopRecorders,
    ],
  );

  const finish = useCallback(() => {
    if (finishRef.current) return finishRef.current;
    finishRef.current = (async () => {
      if (!enabled || !interviewId || !sessionRef.current) return;
      const offset = getOffsetMs();
      recordEvent('capture_state', { technical: true });
      activeRef.current = false;
      setActive(false);
      await stopRecorders();
      screenRef.current?.getTracks().forEach((track) => track.stop());
      setScreen(null);
      screenRef.current = null;
      enqueue({ kind: 'finish', value: Math.max(offset, getOffsetMs()) });
      await Promise.all(pendingWrites.current);
      // Completion of answer scoring is independent of a slow integrity upload.
      let timeout = 0;
      await Promise.race([
        flush(),
        new Promise<void>((resolve) => {
          timeout = window.setTimeout(resolve, 12_000);
        }),
      ]);
      window.clearTimeout(timeout);
    })();
    return finishRef.current;
  }, [
    enabled,
    enqueue,
    flush,
    getOffsetMs,
    interviewId,
    recordEvent,
    stopRecorders,
  ]);

  useIntegrityEvents(active, camera, screen, recordEvent, checkHealth);
  const face = useIntegrityFace(active, camera, getOffsetMs, recordEvent);

  useEffect(() => {
    if (!enabled || !interviewId) return;
    const initialFlush = window.setTimeout(() => {
      void flush();
    }, 0);
    const timer = window.setInterval(() => {
      checkHealth();
      void flush();
    }, 10_000);
    const online = () => {
      checkHealth();
      void flush();
    };
    window.addEventListener('online', online);
    return () => {
      window.clearTimeout(initialFlush);
      window.clearInterval(timer);
      window.removeEventListener('online', online);
    };
  }, [checkHealth, enabled, flush, interviewId]);
  useEffect(
    () => () => {
      activeRef.current = false;
      for (const recorder of recorders.current)
        if (recorder.state !== 'inactive') recorder.stop();
      screenRef.current?.getTracks().forEach((track) => track.stop());
    },
    [],
  );

  return {
    enabled,
    active,
    blocked,
    pendingUploads,
    uploadError,
    camera,
    screen,
    start,
    pause,
    finish,
    recordEvent,
    getOffsetMs,
    checkHealth,
    syncHealth,
    flush,
    face,
  };
}

export type IntegrityCapture = ReturnType<typeof useIntegrityCapture>;
