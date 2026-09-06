import type { EvidenceRange, EvidenceStream } from './integrity-types';

export function clampTime(timeMs: number, range: EvidenceRange) {
  return Math.max(range.startMs, Math.min(range.endMs, timeMs));
}

export function initialEvidenceRange(
  episode: EvidenceRange,
  context: EvidenceRange,
): EvidenceRange {
  return {
    startMs: clampTime(episode.startMs - 5_000, context),
    endMs: clampTime(episode.endMs + 5_000, context),
  };
}

/** Half-open ranges avoid showing the final stale frame in a recording gap. */
export function streamAt(streams: EvidenceStream[], timeMs: number) {
  return streams.find(
    (stream) => timeMs >= stream.startMs && timeMs < stream.endMs,
  );
}

export function mediaTimeSeconds(stream: EvidenceStream, globalMs: number) {
  return Math.max(
    0,
    (globalMs - stream.startMs + stream.mediaOffsetMs) / 1_000,
  );
}

export function globalTimeMs(stream: EvidenceStream, seconds: number) {
  return stream.startMs + seconds * 1_000 - stream.mediaOffsetMs;
}

export function needsCorrection(actualSeconds: number, targetSeconds: number) {
  return Math.abs(actualSeconds - targetSeconds) > 0.25;
}

export function expandEvidenceRange(
  range: EvidenceRange,
  context: EvidenceRange,
  edge: 'start' | 'end',
  amountMs = 10_000,
): EvidenceRange {
  return {
    startMs:
      edge === 'start'
        ? clampTime(range.startMs - amountMs, context)
        : range.startMs,
    endMs:
      edge === 'end' ? clampTime(range.endMs + amountMs, context) : range.endMs,
  };
}

export function formatEvidenceTime(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1_000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
