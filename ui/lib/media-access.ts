export function mediaAccessSupportError(): string | null {
  if (typeof window === 'undefined') return null;
  if (!window.isSecureContext) {
    return 'Камера и микрофон доступны только по защищённому HTTPS-адресу. Откройте защищённую ссылку на интервью.';
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return 'Этот браузер не поддерживает доступ к камере и микрофону. Откройте интервью в актуальном Safari, Chrome, Firefox или Edge.';
  }
  if (typeof MediaRecorder === 'undefined') {
    return 'Этот браузер не поддерживает запись интервью. Обновите браузер или откройте интервью в другом браузере.';
  }
  return null;
}

export function mediaAccessError(error: unknown): string {
  const name =
    error && typeof error === 'object' && 'name' in error
      ? String(error.name)
      : '';
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return 'Доступ к камере или микрофону запрещён. Разрешите их для этого сайта в настройках браузера и операционной системы, затем повторите проверку.';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'Камера или микрофон не найдены. Подключите оба устройства и повторите проверку.';
    case 'NotReadableError':
    case 'TrackStartError':
      return 'Не удалось включить устройство. Закройте приложения и вкладки, которые могут использовать камеру или микрофон, затем повторите проверку.';
    case 'OverconstrainedError':
      return 'Устройство не поддерживает запрошенный режим записи. Выберите другую камеру или микрофон.';
    case 'SecurityError':
      return 'Браузер заблокировал доступ к устройствам. Откройте интервью по HTTPS и проверьте разрешения сайта.';
    case 'AbortError':
      return 'Подключение к устройствам прервалось. Повторите проверку.';
    default:
      return error instanceof Error
        ? error.message
        : 'Не удалось подключить камеру и микрофон. Повторите проверку.';
  }
}

export async function requestInterviewMedia(): Promise<MediaStream> {
  const unsupported = mediaAccessSupportError();
  if (unsupported) throw new Error(unsupported);
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
      video: {
        width: { ideal: 640 },
        height: { ideal: 360 },
        frameRate: { ideal: 15, max: 24 },
        facingMode: 'user',
      },
    });
  } catch (error) {
    if (
      error &&
      typeof error === 'object' &&
      'name' in error &&
      error.name === 'OverconstrainedError'
    ) {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: true,
      });
    } else {
      throw error;
    }
  }
  if (!stream.getAudioTracks().length || !stream.getVideoTracks().length) {
    stream.getTracks().forEach((track) => track.stop());
    throw new Error(
      'Для интервью нужны и камера, и микрофон. Проверьте оба устройства.',
    );
  }
  return stream;
}
