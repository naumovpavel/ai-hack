'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  BriefcaseBusiness,
  Camera,
  Check,
  CheckCircle2,
  CircleDot,
  Clock3,
  FileCheck2,
  Lightbulb,
  LoaderCircle,
  LockKeyhole,
  Mic,
  Mic2,
  RotateCcw,
  ShieldCheck,
  Volume2,
  WifiOff,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { api, ApiError } from '@/lib/api';
import type {
  CandidateOutcome,
  InterviewBriefing,
  InterviewState,
  PublicQuestion,
} from '@/lib/types';

type CandidateView =
  | 'home'
  | 'preparation'
  | 'preflight'
  | 'interview'
  | 'processing';
type CandidateAppProps = {
  candidateId: string | null;
  candidateName: string;
  initialBriefing: InterviewBriefing | null;
  notify: (message: string) => void;
};

type RecorderBundle = {
  audio: MediaRecorder;
  video: MediaRecorder;
  audioChunks: BlobPart[];
  videoChunks: BlobPart[];
};

type PendingAnswer = {
  question: PublicQuestion;
  audio: Blob;
  video: Blob;
  durationSeconds: number;
};

const MAX_ANSWER_SECONDS = 180;

function errorText(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error
    ? error.message
    : 'Произошла неизвестная ошибка.';
}

function BackButton({
  onClick,
  label,
}: {
  onClick: () => void;
  label: string;
}) {
  return (
    <Button variant="ghost" onClick={onClick} className="-ml-2 mb-6">
      <ArrowLeft data-icon="inline-start" /> {label}
    </Button>
  );
}

function formatTimer(seconds: number) {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}

function supportedMime(candidates: string[]) {
  return candidates.find((mime) => MediaRecorder.isTypeSupported(mime));
}

function startRecorders(stream: MediaStream): RecorderBundle {
  const audioTrack = stream.getAudioTracks()[0];
  const videoTrack = stream.getVideoTracks()[0];
  if (!audioTrack || !videoTrack) {
    throw new Error('Для интервью нужны работающие камера и микрофон.');
  }

  const audioStream = new MediaStream([audioTrack]);
  const audioMime = supportedMime([
    'audio/webm;codecs=opus',
    'audio/mp4',
    'audio/webm',
  ]);
  const videoMime = supportedMime([
    'video/webm;codecs=vp8,opus',
    'video/webm;codecs=vp9,opus',
    'video/mp4',
    'video/webm',
  ]);
  const audio = new MediaRecorder(audioStream, {
    ...(audioMime ? { mimeType: audioMime } : {}),
    audioBitsPerSecond: 16_000,
  });
  const video = new MediaRecorder(stream, {
    ...(videoMime ? { mimeType: videoMime } : {}),
    audioBitsPerSecond: 24_000,
    videoBitsPerSecond: 180_000,
  });
  const bundle: RecorderBundle = {
    audio,
    video,
    audioChunks: [],
    videoChunks: [],
  };
  audio.ondataavailable = (event) => {
    if (event.data.size) bundle.audioChunks.push(event.data);
  };
  video.ondataavailable = (event) => {
    if (event.data.size) bundle.videoChunks.push(event.data);
  };
  try {
    audio.start(500);
    video.start(500);
  } catch (error) {
    if (audio.state !== 'inactive') audio.stop();
    if (video.state !== 'inactive') video.stop();
    throw error;
  }
  return bundle;
}

function stopRecorder(recorder: MediaRecorder, chunks: BlobPart[]) {
  return new Promise<Blob>((resolve, reject) => {
    const finish = () =>
      resolve(
        new Blob(chunks, {
          type: recorder.mimeType || 'application/octet-stream',
        }),
      );
    if (recorder.state === 'inactive') {
      finish();
      return;
    }
    recorder.addEventListener('stop', finish, { once: true });
    recorder.addEventListener(
      'error',
      () => reject(new Error('Не удалось завершить запись ответа.')),
      { once: true },
    );
    recorder.stop();
  });
}

async function stopRecorders(bundle: RecorderBundle) {
  const [audio, video] = await Promise.all([
    stopRecorder(bundle.audio, bundle.audioChunks),
    stopRecorder(bundle.video, bundle.videoChunks),
  ]);
  return { audio, video };
}

function CandidateHome({
  name,
  briefing,
  outcome,
  loading,
  onOpen,
}: {
  name: string;
  briefing: InterviewBriefing | null;
  outcome: CandidateOutcome | null;
  loading: boolean;
  onOpen: () => void;
}) {
  const interviewFinished = Boolean(
    briefing &&
    ['completed', 'processing', 'analyzing'].includes(briefing.status),
  );
  const interviewUnavailable = briefing?.status === 'error';
  const interviewStarted = briefing?.status === 'in_progress';
  return (
    <main className="candidate-shell">
      <div className="candidate-welcome">
        <div>
          <p className="eyebrow">Ваше интервью</p>
          <h1 className="page-title">Здравствуйте, {name.split(' ')[0]}</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Здесь виден текущий этап и ответ нанимающей команды.
          </p>
        </div>
        <div className="candidate-privacy-note">
          <ShieldCheck aria-hidden="true" />
          <span>AI не оценивает внешность, акцент, голос или эмоции.</span>
        </div>
      </div>

      {briefing ? (
        <button
          className="candidate-interview-card group mt-8"
          onClick={onOpen}
          disabled={interviewFinished || interviewUnavailable}
        >
          <span className="company-mark" aria-hidden="true">
            S
          </span>
          <span className="min-w-0 flex-1 text-left">
            <span className="block text-xs text-muted-foreground">
              Активное интервью
            </span>
            <span className="mt-1 block truncate text-lg font-semibold">
              {briefing.positionTitle}
            </span>
            <span className="mt-2 flex flex-wrap gap-4 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Clock3 className="size-3.5" />
                {briefing.durationMinutes} минут
              </span>
              <span>{briefing.questionCount} вопросов</span>
            </span>
          </span>
          <Badge
            className={
              interviewUnavailable
                ? 'bg-rose-50 text-rose-700'
                : interviewFinished
                  ? 'bg-violet-50 text-violet-700'
                  : 'bg-blue-50 text-blue-700'
            }
          >
            {interviewUnavailable
              ? 'Нужна помощь рекрутера'
              : interviewFinished
                ? 'Интервью отправлено'
                : interviewStarted
                  ? 'Продолжить интервью'
                  : 'Пройти интервью'}
          </Badge>
          <ArrowRight className="size-4" aria-hidden="true" />
        </button>
      ) : (
        <section className="surface-card mt-8 p-7 text-center">
          {loading ? (
            <LoaderCircle className="mx-auto size-6 animate-spin text-primary" />
          ) : (
            <BriefcaseBusiness className="mx-auto size-6 text-muted-foreground" />
          )}
          <h2 className="mt-4 font-medium">
            {loading ? 'Проверяем приглашения…' : 'Активного интервью нет'}
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Откройте персональную ссылку, которую прислал рекрутер.
          </p>
        </section>
      )}

      {interviewFinished && outcome?.status === 'pending' ? (
        <section className="surface-card mt-4 p-5">
          <p className="text-sm font-medium">
            Команда ещё рассматривает интервью
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Страница обновит решение автоматически.
          </p>
        </section>
      ) : null}
    </main>
  );
}

function Preparation({
  briefing,
  onBack,
  onContinue,
}: {
  briefing: InterviewBriefing;
  onBack: () => void;
  onContinue: () => void;
}) {
  const [consent, setConsent] = useState(false);
  return (
    <main className="candidate-shell max-w-6xl">
      <BackButton onClick={onBack} label="Назад" />
      <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_350px]">
        <div>
          <p className="eyebrow">Перед началом</p>
          <h1 className="page-title">
            Интервью на позицию {briefing.positionTitle}
          </h1>
          <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
            Интервью займёт до {briefing.durationMinutes} минут и содержит{' '}
            {briefing.questionCount} основных вопросов. Отвечайте голосом;
            камера и микрофон будут записываться.
          </p>

          <section
            className="surface-card mt-7 p-5 sm:p-6"
            aria-labelledby="process-heading"
          >
            <h2 id="process-heading" className="font-semibold">
              Как всё пройдёт
            </h2>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {[
                [
                  Volume2,
                  'Вопрос на экране и вслух',
                  'Голос генерирует серверная TTS-модель; текст всегда остаётся видимым.',
                ],
                [
                  Mic2,
                  'Ответ голосом',
                  'Каждый ответ отдельно загружается, превращается в текст и сохраняется вместе с видео.',
                ],
                [
                  Lightbulb,
                  'Возможны уточнения',
                  briefing.allowsFollowUps
                    ? 'AI может задать уточнение, если это полезно и остаётся время.'
                    : 'В этом интервью уточняющие вопросы отключены.',
                ],
                [
                  FileCheck2,
                  'Проверка человеком',
                  'AI связывает выводы с ответами, но не принимает кадровое решение.',
                ],
              ].map(([Icon, title, text]) => {
                const StepIcon = Icon as typeof Volume2;
                return (
                  <article className="process-step" key={String(title)}>
                    <StepIcon className="size-5 text-primary" />
                    <h3>{String(title)}</h3>
                    <p>{String(text)}</p>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="surface-card mt-4 p-5 sm:p-6">
            <h2 className="font-semibold">Темы интервью</h2>
            <div className="mt-4 flex flex-wrap gap-2">
              {briefing.topics.map((topic) => (
                <span className="topic-chip" key={topic}>
                  {topic}
                </span>
              ))}
            </div>
          </section>

          <section className="surface-card mt-4 p-5 sm:p-6">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
              <div>
                <h2 className="font-semibold">Как AI оценивает ответы</h2>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  AI сопоставляет содержание ответов с требованиями позиции,
                  отмечает подтверждённые и непроверенные пункты. Он не
                  оценивает внешность, голос, акцент, эмоции и защищённые
                  характеристики.
                </p>
              </div>
            </div>
            <div className="mt-4 rounded-xl bg-muted p-4 text-sm leading-relaxed text-muted-foreground">
              Нанимающая команда не увидит итоговую рекомендацию, пока не
              откроет каждый пункт анализа и не изучит его минимум 10 секунд.
            </div>
          </section>
        </div>

        <aside className="lg:pt-10">
          <div className="surface-card sticky top-24 p-5 sm:p-6">
            <div className="flex items-center gap-3">
              <LockKeyhole className="size-5 text-primary" />
              <div>
                <h2 className="font-semibold">Согласие на запись</h2>
                <p className="text-xs text-muted-foreground">
                  Нужно до доступа к устройствам
                </p>
              </div>
            </div>
            <ul className="mt-5 space-y-3 text-xs leading-relaxed text-muted-foreground">
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 text-emerald-600" />
                Записываются видео и звук.
              </li>
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 text-emerald-600" />
                Материалы используются для транскрипта и анализа ответов.
              </li>
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 text-emerald-600" />
                Аудио и текстовый контекст обрабатываются моделями через
                OpenRouter согласно настроенной политике хранения; видео
                остаётся в локальном хранилище компании.
              </li>
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 text-emerald-600" />
                Решение всегда подтверждает человек.
              </li>
            </ul>
            <label className="consent-row" htmlFor="recording-consent">
              <Checkbox
                id="recording-consent"
                checked={consent}
                onCheckedChange={(value) => setConsent(value === true)}
              />
              <span>Я согласен на запись и обработку этого интервью.</span>
            </label>
            <Button
              className="mt-5 h-12 w-full"
              disabled={!consent}
              onClick={onContinue}
            >
              Проверить устройства
              <ArrowRight data-icon="inline-end" />
            </Button>
          </div>
        </aside>
      </div>
    </main>
  );
}

function Preflight({
  onBack,
  onReady,
}: {
  onBack: () => void;
  onReady: (stream: MediaStream) => void;
}) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [status, setStatus] = useState<
    'idle' | 'requesting' | 'granted' | 'denied'
  >('idle');
  const [error, setError] = useState('');
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const handedOffRef = useRef(false);
  useEffect(() => {
    if (videoRef.current && stream) videoRef.current.srcObject = stream;
  }, [stream]);

  useEffect(
    () => () => {
      if (!handedOffRef.current)
        stream?.getTracks().forEach((track) => track.stop());
    },
    [stream],
  );

  const requestAccess = async () => {
    setStatus('requesting');
    setError('');
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        throw new Error('Браузер не поддерживает запись с микрофона.');
      }
      stream?.getTracks().forEach((track) => track.stop());
      const media = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: {
          facingMode: 'user',
          width: { ideal: 640, max: 640 },
          height: { ideal: 360, max: 480 },
          frameRate: { ideal: 15, max: 15 },
        },
      });
      setStream(media);
      setStatus('granted');
    } catch (caught) {
      setStatus('denied');
      setError(errorText(caught));
    }
  };

  return (
    <main className="candidate-shell max-w-5xl">
      <BackButton onClick={onBack} label="К подготовке" />
      <div className="text-center">
        <p className="eyebrow">Проверка устройств</p>
        <h1 className="page-title">Камера и микрофон</h1>
        <p className="mx-auto mt-3 max-w-xl text-sm text-muted-foreground">
          Разрешите доступ в системном окне браузера. Запись начнётся только
          после кнопки «Начать интервью».
        </p>
      </div>
      <div className="preflight-grid mt-7">
        <div className="camera-preview">
          {stream ? (
            <video
              ref={videoRef}
              autoPlay
              muted
              playsInline
              aria-label="Предпросмотр камеры"
            />
          ) : (
            <div className="text-center text-white/70">
              <Camera className="mx-auto size-9" />
              <p className="mt-3 text-sm">Предпросмотр появится здесь</p>
            </div>
          )}
          <span className="camera-label">
            <CircleDot className="size-3.5" />
            {status === 'granted' ? 'Камера и микрофон готовы' : 'Предпросмотр'}
          </span>
        </div>
        <section className="surface-card p-5 sm:p-6">
          <h2 className="font-semibold">Состояние</h2>
          <div className="mt-5 space-y-3">
            <div className="device-check-row">
              <span>
                <Camera />
                Камера
              </span>
              <span>{status === 'granted' ? 'Готова' : 'Нужен доступ'}</span>
            </div>
            <div className="device-check-row">
              <span>
                <Mic />
                Микрофон
              </span>
              <span>{status === 'granted' ? 'Готов' : 'Нужен доступ'}</span>
            </div>
          </div>
          {error ? (
            <p className="permission-error" role="alert">
              {error}
            </p>
          ) : null}
          {status === 'granted' ? (
            <Button
              className="mt-5 h-12 w-full"
              onClick={() => {
                if (!stream) return;
                handedOffRef.current = true;
                onReady(stream);
              }}
            >
              Начать интервью
              <ArrowRight data-icon="inline-end" />
            </Button>
          ) : (
            <Button
              className="mt-5 h-12 w-full"
              onClick={() => void requestAccess()}
              disabled={status === 'requesting'}
            >
              {status === 'requesting'
                ? 'Запрашиваем доступ…'
                : 'Продолжить к системному запросу'}
            </Button>
          )}
          {status === 'denied' ? (
            <Button
              variant="outline"
              className="mt-2 w-full"
              onClick={() => void requestAccess()}
            >
              <RotateCcw data-icon="inline-start" />
              Попробовать снова
            </Button>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function InterviewRoom({
  briefing,
  state,
  stream,
  notify,
  onComplete,
  onTerminalError,
}: {
  briefing: InterviewBriefing;
  state: InterviewState;
  stream: MediaStream;
  notify: (message: string) => void;
  onComplete: () => void;
  onTerminalError: (message: string) => void;
}) {
  const [question, setQuestion] = useState<PublicQuestion | null>(
    state.currentQuestion || briefing.currentQuestion,
  );
  const [phase, setPhase] = useState<
    | 'loading-voice'
    | 'ready-voice'
    | 'voice-error'
    | 'asking'
    | 'answering'
    | 'uploading'
    | 'error'
    | 'completing'
  >('loading-voice');
  const [secondsRemaining, setSecondsRemaining] = useState(
    state.remainingSeconds,
  );
  const [answered, setAnswered] = useState(
    Math.max(
      0,
      state.currentQuestion?.orderIndex ??
        briefing.currentQuestion?.orderIndex ??
        0,
    ),
  );
  const [answerSeconds, setAnswerSeconds] = useState(0);
  const [online, setOnline] = useState(() => navigator.onLine);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<PendingAnswer | null>(null);
  const [voiceAttempt, setVoiceAttempt] = useState(0);
  const [voiceError, setVoiceError] = useState('');
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const recordingRef = useRef<RecorderBundle | null>(null);
  const answerStartedAtRef = useRef(0);
  const secondsRemainingRef = useRef(state.remainingSeconds);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const orbRef = useRef<HTMLButtonElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const microphoneAnalyserRef = useRef<AnalyserNode | null>(null);
  const playbackAnalyserRef = useRef<AnalyserNode | null>(null);
  const playbackSourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const hasVideo = stream.getVideoTracks().length > 0;

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream;
  }, [stream]);
  useEffect(() => {
    if (!window.AudioContext) return;
    let context: AudioContext;
    try {
      context = new AudioContext();
    } catch {
      // Visual feedback is optional; recording and playback remain available.
      return;
    }
    audioContextRef.current = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.75;
    const source = context.createMediaStreamSource(stream);
    // The microphone is analysed locally and never connected to the speakers.
    source.connect(analyser);
    microphoneAnalyserRef.current = analyser;
    return () => {
      source.disconnect();
      playbackSourceRef.current?.disconnect();
      microphoneAnalyserRef.current = null;
      playbackAnalyserRef.current = null;
      audioContextRef.current = null;
      void context.close();
    };
  }, [stream]);
  useEffect(() => {
    const element = orbRef.current;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (!element || reducedMotion.matches) return;
    const samples = new Uint8Array(256);
    let frame = 0;
    let level = 0;
    const update = () => {
      const analyser =
        phase === 'answering'
          ? microphoneAnalyserRef.current
          : phase === 'asking'
            ? playbackAnalyserRef.current
            : null;
      let volume = 0;
      if (analyser) {
        analyser.getByteTimeDomainData(samples);
        for (const sample of samples) volume += ((sample - 128) / 128) ** 2;
        volume = Math.min(1, Math.sqrt(volume / samples.length) * 5);
      }
      level += (volume - level) * 0.18;
      element.style.setProperty('--voice-level', level.toFixed(3));
      frame = requestAnimationFrame(update);
    };
    update();
    const stopForReducedMotion = () => {
      cancelAnimationFrame(frame);
      if (reducedMotion.matches) {
        element.style.removeProperty('--voice-level');
      } else {
        update();
      }
    };
    reducedMotion.addEventListener('change', stopForReducedMotion);
    return () => {
      cancelAnimationFrame(frame);
      reducedMotion.removeEventListener('change', stopForReducedMotion);
      element.style.removeProperty('--voice-level');
    };
  }, [phase]);
  useEffect(() => {
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    return () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  }, []);
  useEffect(() => {
    const timer = window.setInterval(
      () =>
        setSecondsRemaining((value) => {
          const next = Math.max(0, value - 1);
          secondsRemainingRef.current = next;
          return next;
        }),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const preventExit = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', preventExit);
    return () => window.removeEventListener('beforeunload', preventExit);
  }, []);

  const beginAnswer = useCallback(() => {
    if (recordingRef.current) return;
    if (secondsRemainingRef.current <= 0) {
      if (answered > 0 || (question?.orderIndex ?? 0) > 0) {
        setPhase('completing');
        onComplete();
      } else {
        onTerminalError(
          'Время истекло до сохранения первого ответа. Обратитесь к рекрутеру.',
        );
      }
      return;
    }
    try {
      void audioContextRef.current?.resume().catch(() => undefined);
      recordingRef.current = startRecorders(stream);
      answerStartedAtRef.current = performance.now();
      setAnswerSeconds(0);
      setPhase('answering');
      setError('');
    } catch (caught) {
      setError(errorText(caught));
      setPhase('error');
    }
  }, [answered, onComplete, onTerminalError, question?.orderIndex, stream]);

  const playModelVoice = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return;
    setPhase('asking');
    try {
      void audioContextRef.current?.resume().catch(() => undefined);
      await audio.play();
    } catch (caught) {
      // An old question can finish loading or reject play() after navigation.
      if (audioRef.current !== audio) return;
      if (caught instanceof DOMException && caught.name === 'NotAllowedError') {
        setPhase('ready-voice');
      } else {
        setVoiceError('Не удалось воспроизвести озвучку вопроса.');
        setPhase('voice-error');
      }
    }
  }, []);

  useEffect(() => {
    if (!question) return;
    const controller = new AbortController();
    let disposed = false;
    const voiceTimeout = window.setTimeout(() => controller.abort(), 120_000);
    recordingRef.current = null;
    audioRef.current?.pause();
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    playbackSourceRef.current?.disconnect();
    playbackSourceRef.current = null;
    playbackAnalyserRef.current = null;

    api
      .getQuestionSpeech(briefing.interviewId, question.id, controller.signal)
      .then((blob) => {
        window.clearTimeout(voiceTimeout);
        if (disposed) return;
        const url = URL.createObjectURL(blob);
        audioUrlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        const context = audioContextRef.current;
        if (context) {
          const source = context.createMediaElementSource(audio);
          const analyser = context.createAnalyser();
          analyser.fftSize = 256;
          source.connect(analyser);
          analyser.connect(context.destination);
          playbackSourceRef.current = source;
          playbackAnalyserRef.current = analyser;
        }
        audio.onended = beginAnswer;
        audio.onerror = () => {
          if (disposed) return;
          setVoiceError('Не удалось воспроизвести озвучку вопроса.');
          setPhase('voice-error');
        };
        void playModelVoice();
      })
      .catch((caught) => {
        window.clearTimeout(voiceTimeout);
        if (disposed) return;
        setVoiceError(
          controller.signal.aborted
            ? 'Озвучка готовится дольше обычного. Попробуйте ещё раз.'
            : errorText(caught),
        );
        setPhase('voice-error');
      });

    return () => {
      disposed = true;
      window.clearTimeout(voiceTimeout);
      controller.abort();
      audioRef.current?.pause();
      if (audioRef.current) {
        audioRef.current.onended = null;
        audioRef.current.onerror = null;
      }
      audioRef.current = null;
      playbackSourceRef.current?.disconnect();
      playbackAnalyserRef.current?.disconnect();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    };
  }, [
    beginAnswer,
    briefing.interviewId,
    playModelVoice,
    question,
    voiceAttempt,
  ]);

  const completeExpiredInterview = useCallback(() => {
    setPhase('completing');
    setPending(null);
    setError('');
    onComplete();
  }, [onComplete]);

  const submitPending = useCallback(
    async (answer: PendingAnswer) => {
      setPhase('uploading');
      setError('');
      try {
        const result = await api.submitAnswer(
          briefing.interviewId,
          answer.question.id,
          answer.audio,
          answer.video,
          answer.durationSeconds,
        );
        setSecondsRemaining(result.remainingSeconds);
        secondsRemainingRef.current = result.remainingSeconds;
        setAnswered((count) => count + 1);
        setPending(null);
        if (result.nextQuestion) {
          setPhase('loading-voice');
          setError('');
          setQuestion(result.nextQuestion);
          notify(
            result.followUpAdded
              ? 'AI добавил уточняющий вопрос'
              : 'Ответ распознан и сохранён',
          );
        } else {
          setPhase('completing');
          onComplete();
        }
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 409) {
          try {
            const latest = await api.getInterviewState(briefing.interviewId);
            setSecondsRemaining(latest.remainingSeconds);
            secondsRemainingRef.current = latest.remainingSeconds;
            if (
              latest.status === 'completed' ||
              latest.status === 'analyzing'
            ) {
              setPending(null);
              onComplete();
              return;
            }
            if (latest.answeredQuestionIds.includes(answer.question.id)) {
              setPending(null);
              setAnswered((count) => count + 1);
              if (latest.currentQuestion) {
                setPhase('loading-voice');
                setQuestion(latest.currentQuestion);
              } else {
                onComplete();
              }
              return;
            }
          } catch {
            // Keep the recorded blobs available for an explicit retry.
          }
        }
        if (
          caught instanceof ApiError &&
          caught.status === 409 &&
          secondsRemainingRef.current <= 0 &&
          (answered > 0 || answer.question.orderIndex > 0)
        ) {
          completeExpiredInterview();
          return;
        }
        setError(errorText(caught));
        setPhase('error');
      }
    },
    [
      answered,
      briefing.interviewId,
      completeExpiredInterview,
      notify,
      onComplete,
    ],
  );

  const finishAnswer = useCallback(async () => {
    if (!question || phase !== 'answering' || !recordingRef.current) return;
    setPhase('uploading');
    try {
      const blobs = await stopRecorders(recordingRef.current);
      recordingRef.current = null;
      const answer = {
        question,
        ...blobs,
        durationSeconds: Math.max(
          0,
          Math.round((performance.now() - answerStartedAtRef.current) / 1000),
        ),
      };
      setPending(answer);
      await submitPending(answer);
    } catch (caught) {
      setError(errorText(caught));
      setPhase('error');
    }
  }, [phase, question, submitPending]);

  useEffect(() => {
    if (phase !== 'answering') return;
    const timer = window.setInterval(() => {
      setAnswerSeconds((current) => {
        const next = current + 1;
        if (next >= MAX_ANSWER_SECONDS) {
          window.setTimeout(() => void finishAnswer(), 0);
        }
        return next;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [finishAnswer, phase]);

  useEffect(() => {
    if (
      !question ||
      secondsRemaining !== 0 ||
      phase === 'uploading' ||
      phase === 'completing' ||
      phase === 'error'
    )
      return;
    if (phase === 'answering' && recordingRef.current) {
      void finishAnswer();
      return;
    }
    const expire = () => {
      audioRef.current?.pause();
      if (answered > 0 || question.orderIndex > 0) {
        completeExpiredInterview();
      } else {
        setPending(null);
        onTerminalError(
          'Время истекло до сохранения первого ответа. Обратитесь к рекрутеру.',
        );
      }
    };
    expire();
  }, [
    answered,
    completeExpiredInterview,
    finishAnswer,
    onTerminalError,
    phase,
    question,
    secondsRemaining,
  ]);

  useEffect(
    () => () => {
      audioRef.current?.pause();
      const active = recordingRef.current;
      if (active) {
        if (active.audio.state !== 'inactive') active.audio.stop();
        if (active.video && active.video.state !== 'inactive')
          active.video.stop();
      }
    },
    [],
  );

  if (!question) {
    return (
      <main className="candidate-shell">
        <section className="surface-card p-8 text-center" role="alert">
          <h1 className="font-semibold">Нет активного вопроса</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Вернитесь по ссылке или обратитесь к рекрутеру.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="interview-room">
      {!online ? (
        <output className="offline-banner">
          <WifiOff className="size-4" />
          Сети нет. Не закрывайте страницу; ответ можно будет отправить повторно
          после восстановления.
        </output>
      ) : null}
      <div className="interview-topline">
        <div className="flex items-center gap-2 text-xs font-medium">
          <span className="recording-dot" aria-hidden="true" />
          {phase === 'answering'
            ? hasVideo
              ? 'Идёт запись аудио и видео'
              : 'Идёт запись аудио'
            : hasVideo
              ? 'Камера и микрофон включены'
              : 'Микрофон включён'}
        </div>
        <div
          className={`interview-timer ${secondsRemaining <= 120 ? 'timer-urgent' : ''}`}
        >
          <Clock3 />
          {formatTimer(secondsRemaining)}
        </div>
      </div>
      <div className="interview-content">
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-4 flex flex-wrap justify-center gap-2">
            <Badge variant="outline">Ответов сохранено: {answered}</Badge>
            <Badge
              className={
                question.kind === 'follow_up'
                  ? 'bg-violet-50 text-violet-700'
                  : 'bg-muted text-foreground'
              }
            >
              {question.kind === 'follow_up' ? 'AI-уточнение' : question.topic}
            </Badge>
          </div>
          <h1 className="interview-question">{question.text}</h1>
          {question.followUpReason ? (
            <p className="mt-3 text-xs text-muted-foreground">
              Почему уточняем: {question.followUpReason}
            </p>
          ) : null}
        </div>

        <div className="voice-stage">
          {hasVideo ? (
            <video
              ref={videoRef}
              autoPlay
              muted
              playsInline
              className="mb-5 aspect-video w-40 rounded-xl bg-black object-cover shadow-lg"
              aria-label="Предпросмотр текущей записи"
            />
          ) : (
            <div className="mb-5 grid size-20 place-items-center rounded-full bg-muted text-muted-foreground">
              <Mic className="size-7" aria-hidden="true" />
            </div>
          )}
          <button
            ref={orbRef}
            className={`voice-orb ${phase === 'answering' ? 'orb-answering' : 'orb-asking'} ${phase === 'asking' || phase === 'answering' ? 'orb-active' : 'orb-idle'}`}
            onClick={() => void finishAnswer()}
            disabled={phase !== 'answering'}
            aria-label={
              phase === 'answering'
                ? 'Закончить и отправить ответ'
                : 'Подождите озвучку вопроса'
            }
          >
            <span className="orb-wave-field" aria-hidden="true">
              <span className="orb-wave orb-wave-one" />
              <span className="orb-wave orb-wave-two" />
              <span className="orb-wave orb-wave-three" />
              <span className="orb-wave orb-wave-four" />
            </span>
            <span className="orb-core">
              {phase === 'answering' ? (
                <Mic />
              ) : phase === 'uploading' || phase === 'completing' ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <Volume2 />
              )}
            </span>
          </button>
          <div className="voice-status min-h-20 text-center" aria-live="polite">
            <p className="text-sm font-medium">
              {phase === 'loading-voice'
                ? 'Готовим озвучку вопроса…'
                : phase === 'ready-voice'
                  ? 'Нажмите, чтобы услышать вопрос'
                  : phase === 'voice-error'
                    ? 'Озвучка недоступна'
                    : phase === 'asking'
                      ? 'Signal озвучивает вопрос'
                      : phase === 'answering'
                        ? `Говорите. Нажмите на микрофон, когда закончите. Автосохранение через ${formatTimer(MAX_ANSWER_SECONDS - answerSeconds)}.`
                        : phase === 'uploading'
                          ? hasVideo
                            ? 'Загружаем аудио и видео, распознаём речь…'
                            : 'Загружаем аудио и распознаём речь…'
                          : phase === 'completing'
                            ? 'Завершаем интервью и запускаем анализ…'
                            : 'Ответ не отправлен'}
            </p>
            {phase === 'ready-voice' ? (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void playModelVoice()}
              >
                <Volume2 data-icon="inline-start" />
                Озвучить вопрос
              </Button>
            ) : null}
            {phase === 'voice-error' ? (
              <div className="mx-auto mt-3 max-w-lg">
                <p className="text-sm text-muted-foreground">{voiceError}</p>
                <div className="mt-3 flex flex-wrap justify-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setPhase('loading-voice');
                      setVoiceError('');
                      setVoiceAttempt((value) => value + 1);
                    }}
                    disabled={!online}
                  >
                    <RotateCcw data-icon="inline-start" />
                    Повторить озвучку
                  </Button>
                  <Button variant="ghost" size="sm" onClick={beginAnswer}>
                    Прочитать вопрос и ответить
                  </Button>
                </div>
              </div>
            ) : null}
            {phase === 'answering' ? (
              <Button
                className="mt-3"
                variant="outline"
                size="sm"
                onClick={() => void finishAnswer()}
              >
                <Check data-icon="inline-start" />
                Завершить ответ
              </Button>
            ) : null}
            {phase === 'asking' ? (
              <Button
                variant="ghost"
                size="sm"
                className="mt-2"
                onClick={() => {
                  audioRef.current?.pause();
                  beginAnswer();
                }}
              >
                Перейти к ответу
              </Button>
            ) : null}
            {phase === 'error' ? (
              <div className="mt-2">
                <p className="text-sm text-rose-700" role="alert">
                  {error}
                </p>
                {pending ? (
                  <Button
                    className="mt-3"
                    onClick={() => void submitPending(pending)}
                    disabled={!online}
                  >
                    <RotateCcw data-icon="inline-start" />
                    Отправить ещё раз
                  </Button>
                ) : secondsRemaining > 0 ? (
                  <Button className="mt-3" onClick={beginAnswer}>
                    <RotateCcw data-icon="inline-start" />
                    Начать запись заново
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
        <div className="interview-progress-wrap">
          <div className="mb-2 flex justify-between text-xs text-muted-foreground">
            <span>{answered} ответов сохранено</span>
            <span>План: {briefing.questionCount} основных</span>
          </div>
          <div className="interview-progress">
            <span
              style={{
                width: `${Math.min(100, (answered / Math.max(1, briefing.questionCount)) * 100)}%`,
              }}
            />
          </div>
        </div>
      </div>
    </main>
  );
}

function Processing({
  outcome,
  completing,
  completionError,
  onRetry,
}: {
  outcome: CandidateOutcome | null;
  completing: boolean;
  completionError: string;
  onRetry: () => void;
}) {
  return (
    <main className="candidate-shell grid min-h-[calc(100dvh-68px)] place-items-center py-12 text-center">
      <div>
        <div className="processing-orb">
          {completing ? <LoaderCircle className="animate-spin" /> : <Check />}
        </div>
        <p className="eyebrow mt-7">Интервью завершено</p>
        <h1 className="mt-2 text-3xl font-semibold">
          Материалы переданы команде
        </h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
          {completing
            ? 'AI готовит анализ. Камера и микрофон уже выключены.'
            : 'Команда проверит каждый пункт анализа и примет решение. Эта страница обновится автоматически.'}
        </p>
        {outcome?.status === 'pending' ? (
          <Badge className="mt-5 bg-blue-50 text-blue-700">
            Решение ожидается
          </Badge>
        ) : null}
        {completionError ? (
          <div
            className="mx-auto mt-5 max-w-md rounded-xl bg-rose-50 p-4 text-sm text-rose-800"
            role="alert"
          >
            <p>{completionError}</p>
            <Button className="mt-3" variant="outline" onClick={onRetry}>
              <RotateCcw data-icon="inline-start" />
              Повторить завершение
            </Button>
          </div>
        ) : null}
      </div>
    </main>
  );
}

function Outcome({
  outcome,
  positionTitle,
}: {
  outcome: CandidateOutcome;
  positionTitle?: string;
}) {
  const accepted = outcome.status === 'next_stage';
  return (
    <main className="candidate-shell max-w-4xl">
      <div
        className={`overview-hero ${accepted ? 'overview-success' : 'overview-feedback'}`}
      >
        <span className="overview-icon">
          {accepted ? <CheckCircle2 /> : <BriefcaseBusiness />}
        </span>
        <Badge
          className={
            accepted
              ? 'bg-emerald-100 text-emerald-800'
              : 'bg-rose-50 text-rose-700'
          }
        >
          {accepted ? 'Позвали дальше' : 'Отказ'}
        </Badge>
        <h1>
          {accepted
            ? 'Команда хочет продолжить знакомство'
            : 'Команда завершила рассмотрение'}
        </h1>
        {positionTitle ? <p>{positionTitle}</p> : null}
      </div>
      <section className="surface-card mt-4 p-5 sm:p-7">
        <h2 className="font-semibold">Сообщение команды</h2>
        <p className="mt-4 text-[15px] leading-7">
          {outcome.candidateFeedback ||
            (accepted
              ? 'Рекрутер свяжется с вами по поводу следующего этапа.'
              : 'Спасибо за время, которое вы уделили интервью.')}
        </p>
        <p className="mt-5 rounded-xl bg-muted p-4 text-xs text-muted-foreground">
          AI помог структурировать ответы, но решение и этот фидбэк подтвердил
          человек.
        </p>
      </section>
    </main>
  );
}

export function CandidateApp({
  candidateId,
  candidateName,
  initialBriefing,
  notify,
}: CandidateAppProps) {
  const [view, setView] = useState<CandidateView>(() => {
    if (!initialBriefing) return 'home';
    return ['completed', 'processing', 'analyzing', 'error'].includes(
      initialBriefing.status,
    )
      ? 'processing'
      : 'preparation';
  });
  const [briefing, setBriefing] = useState<InterviewBriefing | null>(
    initialBriefing,
  );
  const [interviewState, setInterviewState] = useState<InterviewState | null>(
    null,
  );
  const [stream, setStream] = useState<MediaStream | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [outcome, setOutcome] = useState<CandidateOutcome | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [completing, setCompleting] = useState(false);
  const [completionError, setCompletionError] = useState('');
  const completionInFlight = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const [activeInterview, currentOutcome] = await Promise.all([
          initialBriefing
            ? Promise.resolve(initialBriefing)
            : api.getCandidateInterview(controller.signal),
          api.getCandidateOutcome(controller.signal).catch(() => null),
        ]);
        if (controller.signal.aborted) return;
        setBriefing(activeInterview);
        setOutcome(currentOutcome);
        if (
          activeInterview?.status === 'in_progress' &&
          !activeInterview.currentQuestion
        ) {
          const state = await api.getInterviewState(
            activeInterview.interviewId,
            controller.signal,
          );
          if (!state.currentQuestion) {
            setView('processing');
            setCompleting(true);
            try {
              await api.completeInterview(activeInterview.interviewId);
            } catch (caught) {
              if (!controller.signal.aborted)
                setCompletionError(errorText(caught));
            } finally {
              if (!controller.signal.aborted) setCompleting(false);
            }
          }
        }
        if (
          activeInterview &&
          ['completed', 'processing', 'analyzing', 'error'].includes(
            activeInterview.status,
          ) &&
          currentOutcome?.status === 'pending'
        ) {
          setView('processing');
          if (activeInterview.status === 'error') {
            setCompletionError(
              'Подготовка анализа прервалась. Повторите завершение интервью.',
            );
          }
        }
        setError('');
      } catch (caught) {
        if (!controller.signal.aborted) setError(errorText(caught));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [candidateId, initialBriefing]);

  useEffect(() => {
    if (!candidateId) return;
    const poll = window.setInterval(() => {
      void api
        .getCandidateOutcome()
        .then(setOutcome)
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(poll);
  }, [candidateId]);

  useEffect(
    () => () => streamRef.current?.getTracks().forEach((track) => track.stop()),
    [],
  );

  const startInterview = async (media: MediaStream) => {
    if (!briefing) return;
    streamRef.current = media;
    setStream(media);
    setError('');
    try {
      const state = await api.startInterview(briefing.interviewId, true);
      if (!state.currentQuestion && !briefing.currentQuestion) {
        media.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        setStream(null);
        setView('processing');
        setCompleting(true);
        try {
          await api.completeInterview(briefing.interviewId);
          notify('Сохранённые ответы переданы команде');
        } catch (caught) {
          setCompletionError(errorText(caught));
        } finally {
          setCompleting(false);
        }
        return;
      }
      setInterviewState(state);
      setView('interview');
    } catch (caught) {
      media.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setStream(null);
      setView('preparation');
      setError(errorText(caught));
      notify(errorText(caught));
    }
  };

  const finalizeInterview = useCallback(async () => {
    if (!briefing || completionInFlight.current) return;
    completionInFlight.current = true;
    setCompleting(true);
    setCompletionError('');
    try {
      await api.completeInterview(briefing.interviewId);
    } catch (caught) {
      try {
        const current = await api.getCandidateInterview();
        if (!current || !['analyzing', 'completed'].includes(current.status)) {
          setCompletionError(errorText(caught));
        }
      } catch {
        setCompletionError(errorText(caught));
      }
    } finally {
      completionInFlight.current = false;
      setCompleting(false);
    }
  }, [briefing]);

  const complete = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
    setView('processing');
    notify('Интервью завершено и передано команде');
    void finalizeInterview();
  }, [finalizeInterview, notify]);

  const stopAfterTerminalError = useCallback(
    (message: string) => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setStream(null);
      setInterviewState(null);
      setBriefing((current) =>
        current
          ? { ...current, status: 'error', currentQuestion: null }
          : current,
      );
      setError(message);
      setView('home');
      notify(message);
    },
    [notify],
  );

  if (outcome && outcome.status !== 'pending')
    return (
      <Outcome outcome={outcome} positionTitle={briefing?.positionTitle} />
    );
  if (view === 'processing')
    return (
      <Processing
        outcome={outcome}
        completing={completing}
        completionError={completionError}
        onRetry={() => void finalizeInterview()}
      />
    );
  if (view === 'interview' && briefing && interviewState && stream)
    return (
      <InterviewRoom
        briefing={briefing}
        state={interviewState}
        stream={stream}
        notify={notify}
        onComplete={complete}
        onTerminalError={stopAfterTerminalError}
      />
    );
  if (view === 'preflight' && briefing)
    return (
      <>
        <Preflight
          onBack={() => setView('preparation')}
          onReady={(media) => void startInterview(media)}
        />
        {error ? (
          <div className="app-notice app-notice-visible" role="alert">
            {error}
          </div>
        ) : null}
      </>
    );
  if (view === 'preparation' && briefing)
    return (
      <Preparation
        briefing={briefing}
        onBack={() => setView('home')}
        onContinue={() => setView('preflight')}
      />
    );
  return (
    <>
      <CandidateHome
        name={briefing?.candidateName || candidateName}
        briefing={briefing}
        outcome={outcome}
        loading={loading}
        onOpen={() => setView('preparation')}
      />
      {error ? (
        <div className="app-notice app-notice-visible" role="alert">
          {error}
        </div>
      ) : null}
    </>
  );
}
