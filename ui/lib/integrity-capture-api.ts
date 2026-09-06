import { jsonRequest, required } from '@/lib/api';

export type CaptureHealth = {
  cameraActive: boolean;
  microphoneActive: boolean;
  screenActive: boolean;
  displaySurface: string | null;
};
export type IntegrityCaptureSession = {
  id: string;
  interviewId: string;
  status: string;
  elapsedMs: number;
  nextQuestionBlocked: boolean;
  heartbeatIntervalMs: number;
};
export type IntegrityEvent = {
  clientEventId: string;
  type: IntegrityEventType;
  offsetMs: number;
  durationMs?: number;
  questionId?: string;
  payload: Record<string, unknown>;
};
// Kept in sync with workflow/integrity_schemas.py; checked by the capture tests.
export const INTEGRITY_EVENT_TYPES = [
  'visibility_change',
  'focus_lost',
  'focus_gained',
  'capture_stopped',
  'capture_restored',
  'device_change',
  'display_info',
  'face_absent',
  'head_deviation',
  'gaze_deviation',
  'calibration',
  'heuristic_unavailable',
  'technical_error',
  'question_started',
  'answer_started',
  'answer_ended',
  'recording_gap',
  'capture_state',
] as const;
export type IntegrityEventType = (typeof INTEGRITY_EVENT_TYPES)[number];
export type IntegrityChunk = {
  clientChunkId: string;
  streamId: string;
  kind: 'camera' | 'screen';
  sequence: number;
  startMs: number;
  endMs: number;
  blob: Blob;
};
const path = (id: string, action: string) =>
  `/interviews/${encodeURIComponent(id)}/integrity/${action}`;

async function boundedRequest<T>(
  url: string,
  options: RequestInit,
  timeoutMs = 30_000,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await required<T>(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

export const integrityCaptureApi = {
  start(id: string, health: CaptureHealth, clientSessionId: string) {
    return boundedRequest<IntegrityCaptureSession>(
      path(id, 'start'),
      jsonRequest({ ...health, clientSessionId }, { method: 'POST' }),
    );
  },
  heartbeat(id: string, health: CaptureHealth, offsetMs: number) {
    return boundedRequest<IntegrityCaptureSession>(
      path(id, 'heartbeat'),
      jsonRequest({ ...health, offsetMs }, { method: 'POST' }),
      5_000,
    );
  },
  events(id: string, events: IntegrityEvent[]) {
    return boundedRequest(
      path(id, 'events'),
      jsonRequest({ events }, { method: 'POST' }),
    );
  },
  chunk(id: string, chunk: IntegrityChunk) {
    const form = new FormData();
    const { blob, ...metadata } = chunk;
    for (const [key, value] of Object.entries(metadata))
      form.set(key, String(value));
    form.set(
      'chunk',
      blob,
      `${chunk.streamId}-${chunk.sequence}.${blob.type.includes('mp4') ? 'mp4' : 'webm'}`,
    );
    return boundedRequest(path(id, 'chunks'), { method: 'POST', body: form });
  },
  finish(id: string, offsetMs: number) {
    return boundedRequest(
      path(id, 'finish'),
      jsonRequest({ offsetMs }, { method: 'POST' }),
    );
  },
};
