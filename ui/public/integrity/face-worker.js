/* Local-only MediaPipe inference. No images, landmark meshes, identity or expression
 * features leave this worker. CPU inference runs at the caller's 5 FPS limit.
 * Runtime: @mediapipe/tasks-vision 0.10.32 (Apache-2.0); self-hosted by build script. */
self.exports = {};
importScripts('/integrity/runtime/vision_bundle.js');
const { FaceLandmarker, FilesetResolver } = self.exports;
let landmarker;
let calibration = null;
let samples = [];
let calibrating = false;
const signals = new Map();
let latestOffset = 0;

function emitInterval(type, signal, end) {
  if (end - signal.start < signal.minimum) return;
  self.postMessage({
    type: 'signal',
    name: type,
    offsetMs: signal.start,
    durationMs: end - signal.start,
    payload: {
      source: 'local_heuristic',
      strength: 'weak',
      requiresVideoReview: true,
      limitation:
        'Это геометрическая эвристика, а не направление внимания или доказательство подсказки.',
      alternativeExplanation:
        type === 'face_absent'
          ? 'Движение, освещение, перекрытие камеры или ошибка распознавания.'
          : 'Чтение вопроса, естественное движение, расположение камеры, очки или освещение.',
    },
  });
}
function track(type, detected, offset, minimum) {
  const previous = signals.get(type);
  if (detected && !previous) signals.set(type, { start: offset, minimum });
  if (!detected && previous) {
    emitInterval(type, previous, offset);
    signals.delete(type);
  }
  if (detected && previous && offset - previous.start >= 10_000) {
    emitInterval(type, previous, offset);
    signals.set(type, { start: offset, minimum });
  }
}
function measures(result) {
  const points = result.faceLandmarks[0];
  const matrix = result.facialTransformationMatrixes[0]?.data;
  if (!points || !matrix || points.length < 478) return null;
  const iris = (center, left, right) => {
    const width = points[right].x - points[left].x;
    return Math.abs(width) > 0.005
      ? (points[center].x - points[left].x) / width
      : 0.5;
  };
  return [
    Math.atan2(matrix[8], matrix[10]),
    Math.atan2(-matrix[9], Math.hypot(matrix[8], matrix[10])),
    iris(468, 33, 133),
    iris(473, 362, 263),
  ];
}
self.onmessage = async ({ data }) => {
  try {
    if (data.type === 'init') {
      const vision = await FilesetResolver.forVisionTasks(
        '/integrity/runtime/wasm',
      );
      landmarker = await FaceLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: '/integrity/face_landmarker.task',
          delegate: 'CPU',
        },
        runningMode: 'VIDEO',
        numFaces: 1,
        minFaceDetectionConfidence: 0.6,
        minFacePresenceConfidence: 0.6,
        minTrackingConfidence: 0.6,
        outputFaceBlendshapes: false,
        outputFacialTransformationMatrixes: true,
      });
      self.postMessage({ type: 'ready' });
      return;
    }
    if (data.type === 'calibrate') {
      samples = [];
      calibration = null;
      calibrating = true;
      signals.clear();
      return;
    }
    if (data.type === 'close') {
      for (const [name, signal] of signals)
        emitInterval(name, signal, latestOffset);
      signals.clear();
      landmarker?.close();
      self.postMessage({ type: 'closed' });
      self.close();
      return;
    }
    if (data.type !== 'frame') return;
    latestOffset = data.offsetMs;
    try {
      if (!landmarker) return;
      const value = measures(
        landmarker.detectForVideo(data.bitmap, data.timestampMs),
      );
      if (calibrating) {
        if (value) samples.push(value);
        self.postMessage({ type: 'progress', samples: samples.length });
        if (samples.length >= 25) {
          calibration = samples[0].map((_, index) => ({
            min: Math.min(...samples.map((item) => item[index])),
            max: Math.max(...samples.map((item) => item[index])),
          }));
          calibrating = false;
          samples = [];
          self.postMessage({ type: 'calibrated' });
        }
      } else if (calibration) {
        const outside = (index, margin) =>
          value &&
          (value[index] < calibration[index].min - margin ||
            value[index] > calibration[index].max + margin);
        track('face_absent', !value, latestOffset, 3_000);
        track(
          'head_deviation',
          Boolean(value && (outside(0, 0.28) || outside(1, 0.25))),
          latestOffset,
          4_000,
        );
        track(
          'gaze_deviation',
          Boolean(value && (outside(2, 0.16) || outside(3, 0.16))),
          latestOffset,
          4_000,
        );
      }
    } finally {
      data.bitmap.close();
      self.postMessage({ type: 'frame_done' });
    }
  } catch (error) {
    self.postMessage({
      type: 'error',
      message:
        error instanceof Error ? error.message : 'Локальный анализ недоступен',
    });
  }
};
