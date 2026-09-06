import test from 'node:test';
import assert from 'node:assert/strict';
import {
  clampTime,
  expandEvidenceRange,
  globalTimeMs,
  initialEvidenceRange,
  mediaTimeSeconds,
  needsCorrection,
  streamAt,
} from '../lib/evidence-timeline.ts';

const stream = {
  mediaId: 'camera-2',
  streamId: 'recorder-restart',
  url: '/authorized.mp4',
  startMs: 115_000,
  endMs: 240_000,
  mediaOffsetMs: 2_000,
};

await test('an interval-boundary episode includes both sides and five seconds of context', () => {
  assert.deepEqual(
    initialEvidenceRange(
      { startMs: 118_000, endMs: 127_000 },
      { startMs: 0, endMs: 240_000 },
    ),
    { startMs: 113_000, endMs: 132_000 },
  );
  assert.deepEqual(
    initialEvidenceRange(
      { startMs: 2_000, endMs: 238_000 },
      { startMs: 0, endMs: 240_000 },
    ),
    { startMs: 0, endMs: 240_000 },
  );
});

await test('restarted recorder and nonzero media offsets round-trip through interview time', () => {
  assert.equal(mediaTimeSeconds(stream, 120_000), 7);
  assert.equal(globalTimeMs(stream, 7), 120_000);
});

await test('manifest gaps do not carry forward the last screen frame', () => {
  const first = { ...stream, startMs: 0, endMs: 10_000 };
  const second = {
    ...stream,
    mediaId: 'restart',
    startMs: 15_000,
    endMs: 30_000,
  };
  assert.equal(streamAt([first, second], 9_999), first);
  assert.equal(streamAt([first, second], 10_000), undefined);
  assert.equal(streamAt([first, second], 12_000), undefined);
  assert.equal(streamAt([first, second], 15_000), second);
});

await test('screen correction threshold is strictly greater than 250ms', () => {
  assert.equal(needsCorrection(1, 1.25), false);
  assert.equal(needsCorrection(1, 1.251), true);
  assert.equal(needsCorrection(1.251, 1), true);
});

await test('context buttons and refresh position stay within available recording', () => {
  const context = { startMs: 10_000, endMs: 90_000 };
  const range = { startMs: 15_000, endMs: 85_000 };
  assert.deepEqual(expandEvidenceRange(range, context, 'start'), {
    startMs: 10_000,
    endMs: 85_000,
  });
  assert.deepEqual(expandEvidenceRange(range, context, 'end'), {
    startMs: 15_000,
    endMs: 90_000,
  });
  assert.equal(clampTime(120_000, context), 90_000);
});
