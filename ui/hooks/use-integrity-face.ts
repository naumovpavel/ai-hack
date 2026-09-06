'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { RecordIntegrityEvent } from './use-integrity-events';

type FaceStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'calibrating'
  | 'calibrated'
  | 'unavailable';

export function useIntegrityFace(
  active: boolean,
  camera: MediaStream | null,
  offset: () => number,
  record: RecordIntegrityEvent,
) {
  const [status, setStatus] = useState<FaceStatus>('idle');
  const [progress, setProgress] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const workerRef = useRef<Worker | null>(null);
  const calibrationTimerRef = useRef<number | null>(null);
  const calibrate = useCallback(() => {
    if (!workerRef.current) return;
    setStatus('calibrating');
    setProgress(0);
    workerRef.current.postMessage({ type: 'calibrate' });
    record('calibration', { stage: 'started', localOnly: true });
    if (calibrationTimerRef.current)
      window.clearTimeout(calibrationTimerRef.current);
    calibrationTimerRef.current = window.setTimeout(() => {
      setStatus('unavailable');
      workerRef.current?.terminate();
      workerRef.current = null;
      record('heuristic_unavailable', {
        reason: 'calibration_timeout',
        technical: true,
      });
    }, 30_000);
  }, [record]);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    if (!active || !camera) return;
    let disposed = false;
    let ready = false;
    let busy = false;
    let worker: Worker;
    const video = document.createElement('video');
    video.srcObject = camera;
    video.muted = true;
    video.playsInline = true;
    queueMicrotask(() => {
      if (!disposed) setStatus('loading');
    });
    const unavailable = () => {
      if (disposed) return;
      setStatus('unavailable');
      ready = false;
      record('heuristic_unavailable', {
        technical: true,
        limitation:
          'Локальные сигналы недоступны; запись и интервью продолжаются.',
      });
      workerRef.current?.terminate();
      workerRef.current = null;
    };
    try {
      if (!window.Worker || !window.createImageBitmap)
        throw new Error('Worker unavailable');
      worker = new Worker('/integrity/face-worker.js');
      workerRef.current = worker;
    } catch {
      unavailable();
      video.srcObject = null;
      return;
    }
    const loadTimeout = window.setTimeout(unavailable, 25_000);
    worker.onmessage = ({ data }) => {
      if (data.type === 'closed') {
        worker.terminate();
        return;
      }
      if (data.type === 'signal') {
        record(data.name, data.payload, data.durationMs, data.offsetMs);
        return;
      }
      if (disposed) return;
      if (data.type === 'ready') {
        window.clearTimeout(loadTimeout);
        ready = true;
        setStatus('ready');
      }
      if (data.type === 'frame_done') busy = false;
      if (data.type === 'progress')
        setProgress(Math.min(100, Math.round((data.samples / 25) * 100)));
      if (data.type === 'calibrated') {
        if (calibrationTimerRef.current)
          window.clearTimeout(calibrationTimerRef.current);
        setStatus('calibrated');
        setProgress(100);
        record('calibration', { stage: 'completed', localOnly: true, fps: 5 });
      }
      if (data.type === 'error') {
        window.clearTimeout(loadTimeout);
        unavailable();
      }
    };
    worker.onerror = unavailable;
    worker.postMessage({ type: 'init' });
    void video.play().catch(unavailable);
    const timer = window.setInterval(async () => {
      if (!ready || disposed || busy || video.readyState < 2) return;
      busy = true;
      try {
        const bitmap = await createImageBitmap(video, {
          resizeWidth: 320,
          resizeHeight: 180,
        });
        if (disposed || !workerRef.current) {
          bitmap.close();
          busy = false;
          return;
        }
        worker.postMessage(
          {
            type: 'frame',
            bitmap,
            timestampMs: performance.now(),
            offsetMs: offset(),
          },
          [bitmap],
        );
      } catch {
        busy = false;
      }
    }, 200);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.clearTimeout(loadTimeout);
      if (calibrationTimerRef.current)
        window.clearTimeout(calibrationTimerRef.current);
      worker.postMessage({ type: 'close' });
      window.setTimeout(() => worker.terminate(), 1_000);
      workerRef.current = null;
      video.pause();
      video.srcObject = null;
    };
  }, [active, attempt, camera, offset, record]);
  return { status, progress, calibrate, retry };
}
