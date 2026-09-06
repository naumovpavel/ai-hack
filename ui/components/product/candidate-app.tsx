'use client';

import {
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from 'react';
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
  Monitor,
  RotateCcw,
  ShieldCheck,
  Volume2,
  WifiOff,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { api, ApiError } from '@/lib/api';
import {
  requestIntegrityScreen,
  useIntegrityCapture,
  type IntegrityCapture,
} from '@/hooks/use-integrity-capture';
import {
  mediaAccessError,
  mediaAccessSupportError,
  requestInterviewMedia,
} from '@/lib/media-access';
import { practiceApi, type PracticeSession } from '@/lib/practice-api';
import { PracticeReview } from './practice-review';
import type {
  CandidateOutcome,
  InterviewBriefing,
  InterviewState,
  PracticeQuestion,
  PublicQuestion,
} from '@/lib/types';

type CandidateView =
  | 'home'
  | 'preparation'
  | 'practice_preflight'
  | 'practice_interview'
  | 'practice_complete'
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

type PendingPracticeAnswer = Omit<PendingAnswer, 'question'> & {
  question: PracticeQuestion;
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
  disabled = false,
}: {
  onClick: () => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      disabled={disabled}
      className="-ml-2 mb-6"
    >
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
                  ? 'bg-secondary text-secondary-foreground'
                  : 'bg-accent text-accent-foreground'
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
            <LoaderCircle className="mx-auto size-6 animate-spin text-accent-foreground" />
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
  practiceSet,
  practiceLoading,
  practiceError,
  onBack,
  onContinue,
  onLoadExamples,
  onPractice,
}: {
  briefing: InterviewBriefing;
  practiceSet: PracticeSession | null;
  practiceLoading: boolean;
  practiceError: string;
  onBack: () => void;
  onContinue: () => void;
  onLoadExamples: () => void;
  onPractice: () => void;
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
            {briefing.integrityEnabled
              ? 'камера, микрофон и весь выбранный экран записываются непрерывно, включая паузы между ответами.'
              : 'камера и микрофон будут записываться.'}
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
                  'Команда сначала оценит ответы и запишет своё решение, затем увидит рекомендацию AI.',
                ],
              ].map(([Icon, title, text]) => {
                const StepIcon = Icon as typeof Volume2;
                return (
                  <article className="process-step" key={String(title)}>
                    <StepIcon className="size-5 text-accent-foreground" />
                    <h3>{String(title)}</h3>
                    <p>{String(text)}</p>
                  </article>
                );
              })}
            </div>
          </section>

          {briefing.status === 'ready' ? (
            <section className="surface-card mt-4 p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="max-w-xl">
                  <h2 className="font-semibold">Попробуйте до начала</h2>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    Пройдите мок-интервью по тем же общим темам с другими
                    вопросами. После записи оцените свои ответы и сравните
                    выводы с анализом ИИ. Настоящее интервью начнётся отдельно.
                  </p>
                </div>
                <Badge className="bg-emerald-50 text-emerald-700">
                  Не влияет на оценку
                </Badge>
              </div>
              {practiceSet ? (
                <div className="mt-5 grid gap-3">
                  {practiceSet.questions.map((question, index) => (
                    <article
                      key={question.id}
                      className="rounded-xl border border-border/70 bg-muted/40 p-4"
                    >
                      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                        <span>Тренировочный пример {index + 1}</span>
                        <span>{question.topic}</span>
                      </div>
                      <p className="mt-2 text-sm leading-relaxed">
                        {question.text}
                      </p>
                    </article>
                  ))}
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {practiceSet.notice}
                  </p>
                </div>
              ) : null}
              {practiceError ? (
                <p className="mt-4 text-sm text-rose-700" role="alert">
                  {practiceError}
                </p>
              ) : null}
              <div className="mt-5 flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={onLoadExamples}
                  disabled={practiceLoading || Boolean(practiceSet)}
                >
                  {practiceLoading ? (
                    <LoaderCircle
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <Lightbulb data-icon="inline-start" />
                  )}
                  {practiceSet ? 'Примеры загружены' : 'Посмотреть примеры'}
                </Button>
                <Button onClick={onPractice} disabled={practiceLoading}>
                  <Mic2 data-icon="inline-start" />
                  {practiceSet &&
                  ['analyzing', 'completed', 'error'].includes(
                    practiceSet.status,
                  )
                    ? 'Открыть разбор тренировки'
                    : practiceSet?.status === 'in_progress'
                      ? 'Продолжить тренировку'
                      : 'Пройти тренировку'}
                </Button>
              </div>
            </section>
          ) : null}

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
              <ShieldCheck className="mt-0.5 size-5 shrink-0 text-accent-foreground" />
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
              Нанимающая команда сначала оценит каждый ответ и сохранит своё
              решение с фидбэком. Только после этого ей откроется рекомендация
              ИИ. Окончательное решение подтвердит человек.
            </div>
          </section>
        </div>

        <aside className="lg:pt-10">
          <div className="surface-card sticky top-24 p-5 sm:p-6">
            <div className="flex items-center gap-3">
              <LockKeyhole className="size-5 text-accent-foreground" />
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
                {briefing.integrityEnabled
                  ? 'Непрерывно записываются камера, звук и весь выбранный экран. Материалы контроля хранятся 30 дней.'
                  : 'Записываются видео и звук.'}
              </li>
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 text-emerald-600" />
                Материалы используются для транскрипта и анализа ответов.
              </li>
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 text-emerald-600" />
                {briefing.integrityEnabled
                  ? 'Запись, расшифровка и технические события обрабатываются после интервью через OpenRouter. Локальные сигналы положения лица служат только поводом для просмотра человеком.'
                  : 'Аудио и текстовый контекст обрабатываются моделями через OpenRouter согласно настроенной политике хранения; видео остаётся в локальном хранилище компании.'}
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
  practice = false,
  integrityEnabled = false,
}: {
  onBack: () => void;
  onReady: (stream: MediaStream, screen?: MediaStream) => void | Promise<void>;
  practice?: boolean;
  integrityEnabled?: boolean;
}) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [screenStream, setScreenStream] = useState<MediaStream | null>(null);
  const [requestingScreen, setRequestingScreen] = useState(false);
  const [status, setStatus] = useState<
    'idle' | 'requesting' | 'granted' | 'denied'
  >('idle');
  const [error, setError] = useState('');
  const [consent, setConsent] = useState(false);
  const [starting, setStarting] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const handedOffRef = useRef(false);
  const requestRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    const frame = window.requestAnimationFrame(() => {
      const supportError = mediaAccessSupportError();
      if (supportError) {
        setError(supportError);
        setStatus('denied');
      }
    });
    return () => {
      window.cancelAnimationFrame(frame);
      mountedRef.current = false;
      requestRef.current += 1;
    };
  }, []);
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
  useEffect(() => {
    const ended = () => {
      setScreenStream(null);
      setError(
        'Демонстрация экрана остановлена. Подключите весь экран ещё раз.',
      );
    };
    screenStream?.getVideoTracks()[0]?.addEventListener('ended', ended);
    return () => {
      screenStream?.getVideoTracks()[0]?.removeEventListener('ended', ended);
      if (!handedOffRef.current)
        screenStream?.getTracks().forEach((track) => track.stop());
    };
  }, [screenStream]);

  const requestAccess = async () => {
    const requestId = ++requestRef.current;
    setStatus('requesting');
    setError('');
    const timeout = window.setTimeout(() => {
      if (!mountedRef.current || requestRef.current !== requestId) return;
      requestRef.current += 1;
      setStatus('denied');
      setError(
        'Браузер пока не ответил на запрос. Проверьте окно разрешений камеры и микрофона, затем нажмите «Попробовать снова».',
      );
    }, 30_000);
    try {
      stream?.getTracks().forEach((track) => track.stop());
      setStream(null);
      const media = await requestInterviewMedia();
      if (!mountedRef.current || requestRef.current !== requestId) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      setStream(media);
      setStatus('granted');
    } catch (caught) {
      if (!mountedRef.current || requestRef.current !== requestId) return;
      setStatus('denied');
      setError(mediaAccessError(caught));
    } finally {
      window.clearTimeout(timeout);
    }
  };

  return (
    <main className="candidate-shell max-w-5xl">
      <BackButton onClick={onBack} label="К подготовке" disabled={starting} />
      <div className="text-center">
        <p className="eyebrow">Проверка устройств</p>
        <h1 className="page-title">
          {integrityEnabled
            ? 'Камера, микрофон и весь экран'
            : 'Камера и микрофон'}
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-sm text-muted-foreground">
          {practice
            ? 'Записи тренировки сохранятся на сервере для транскрипта и личного разбора. Аудио и текст обрабатываются моделями через OpenRouter; видео хранится у сервиса. Рекрутер не увидит тренировочные ответы и анализ.'
            : integrityEnabled
              ? 'Разрешите камеру и микрофон, затем выберите «Весь экран». После начала интервью запись идёт непрерывно, в том числе между ответами. Видеоматериалы контроля хранятся 30 дней.'
              : 'Разрешите доступ в системном окне браузера. Запись начнётся только после кнопки «Начать интервью».'}
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
            {integrityEnabled ? (
              <div className="device-check-row">
                <span>
                  <Monitor />
                  Весь экран
                </span>
                <span>{screenStream ? 'Готов' : 'Нужен доступ'}</span>
              </div>
            ) : null}
          </div>
          {error ? (
            <p className="permission-error" role="alert">
              {error}
            </p>
          ) : null}
          {practice ? (
            <label className="consent-row" htmlFor="practice-recording-consent">
              <Checkbox
                id="practice-recording-consent"
                checked={consent}
                onCheckedChange={(value) => setConsent(value === true)}
              />
              <span>
                Я согласен на запись и обработку мок-интервью для личного
                разбора.
              </span>
            </label>
          ) : null}
          {status === 'granted' ? (
            <>
              {integrityEnabled && !screenStream ? (
                <Button
                  className="mt-5 w-full"
                  variant="outline"
                  disabled={requestingScreen}
                  onClick={async () => {
                    setRequestingScreen(true);
                    setError('');
                    try {
                      const display = await requestIntegrityScreen();
                      if (!mountedRef.current)
                        display.getTracks().forEach((track) => track.stop());
                      else setScreenStream(display);
                    } catch (caught) {
                      if (mountedRef.current) setError(errorText(caught));
                    } finally {
                      if (mountedRef.current) setRequestingScreen(false);
                    }
                  }}
                >
                  <Monitor data-icon="inline-start" />
                  {requestingScreen
                    ? 'Выберите весь экран…'
                    : 'Поделиться всем экраном'}
                </Button>
              ) : null}
              <Button
                className="mt-5 h-12 w-full"
                disabled={
                  starting ||
                  (practice && !consent) ||
                  (integrityEnabled && !screenStream)
                }
                onClick={async () => {
                  if (!stream) return;
                  setStarting(true);
                  try {
                    handedOffRef.current = true;
                    await onReady(stream, screenStream || undefined);
                  } catch (caught) {
                    handedOffRef.current = false;
                    setError(errorText(caught));
                  } finally {
                    if (mountedRef.current) setStarting(false);
                  }
                }}
              >
                {starting
                  ? 'Начинаем…'
                  : practice
                    ? 'Начать тренировку'
                    : 'Начать интервью'}
                <ArrowRight data-icon="inline-end" />
              </Button>
            </>
          ) : (
            <Button
              className="mt-5 h-12 w-full"
              onClick={() => void requestAccess()}
              disabled={status === 'requesting' || (practice && !consent)}
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
              disabled={practice && !consent}
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

function PracticeRoom({
  practiceSet,
  stream,
  onComplete,
  onBack,
}: {
  practiceSet: PracticeSession;
  stream: MediaStream;
  onComplete: () => void;
  onBack: () => void;
}) {
  const [questionIndex, setQuestionIndex] = useState(() =>
    practiceSet.currentQuestion
      ? practiceSet.questions.findIndex(
          (item) => item.id === practiceSet.currentQuestion?.id,
        )
      : practiceSet.answeredQuestionIds.length,
  );
  const [recording, setRecording] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<PendingPracticeAnswer | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(
    practiceSet.currentQuestion?.answerSeconds ?? 90,
  );
  const recorderRef = useRef<RecorderBundle | null>(null);
  const mountedRef = useRef(true);
  const answerDeadlineRef = useRef(0);
  const answerStartedRef = useRef(0);
  const uploadRef = useRef<AbortController | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const questions = practiceSet.questions;
  const question = questions[questionIndex];

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream;
  }, [stream]);

  const submitAnswer = async (answer: PendingPracticeAnswer) => {
    if (uploadRef.current) return;
    const controller = new AbortController();
    uploadRef.current = controller;
    setStopping(true);
    setUploadProgress(0);
    setError('');
    setPending(answer);
    try {
      const result = await practiceApi.answer(
        practiceSet.practiceId,
        answer.question.id,
        answer.audio,
        answer.video,
        answer.durationSeconds,
        { signal: controller.signal, onProgress: setUploadProgress },
      );
      if (!mountedRef.current) return;
      setPending(null);
      if (!result.nextQuestion) {
        onComplete();
        return;
      }
      const nextIndex = questions.findIndex(
        (item) => item.id === result.nextQuestion?.id,
      );
      if (nextIndex < 0)
        throw new Error(
          'Не удалось открыть следующий вопрос. Вернитесь к подготовке и продолжите тренировку.',
        );
      setQuestionIndex(nextIndex);
      setSecondsLeft(result.nextQuestion.answerSeconds);
    } catch (caught) {
      if (mountedRef.current) setError(errorText(caught));
    } finally {
      uploadRef.current = null;
      if (mountedRef.current) setStopping(false);
    }
  };

  const finishAnswer = async () => {
    const active = recorderRef.current;
    if (!active) return;
    recorderRef.current = null;
    setStopping(true);
    setRecording(false);
    try {
      const blobs = await stopRecorders(active);
      if (!mountedRef.current) return;
      await submitAnswer({
        question,
        ...blobs,
        durationSeconds: Math.max(
          1,
          Math.ceil((performance.now() - answerStartedRef.current) / 1000),
        ),
      });
    } catch (caught) {
      if (mountedRef.current) setError(errorText(caught));
    } finally {
      active.audio.ondataavailable = null;
      active.video.ondataavailable = null;
      active.audioChunks.length = 0;
      active.videoChunks.length = 0;
      if (mountedRef.current) setStopping(false);
    }
  };
  const finishAnswerOnTimeout = useEffectEvent(finishAnswer);

  useEffect(() => {
    if (!recording) return;
    const timer = window.setInterval(() => {
      const remaining = Math.max(
        0,
        Math.ceil((answerDeadlineRef.current - performance.now()) / 1000),
      );
      setSecondsLeft(remaining);
      if (remaining === 0) {
        window.clearInterval(timer);
        void finishAnswerOnTimeout();
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [recording]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      window.speechSynthesis?.cancel();
      uploadRef.current?.abort();
      const active = recorderRef.current;
      recorderRef.current = null;
      if (active) {
        active.audio.ondataavailable = null;
        active.video.ondataavailable = null;
        if (active.audio.state !== 'inactive') active.audio.stop();
        if (active.video.state !== 'inactive') active.video.stop();
        active.audioChunks.length = 0;
        active.videoChunks.length = 0;
      }
    };
  }, []);

  useEffect(() => {
    if (!recording && !pending && !stopping) return;
    const preventExit = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', preventExit);
    return () => window.removeEventListener('beforeunload', preventExit);
  }, [recording, pending, stopping]);

  const speakQuestion = () => {
    if (!question || !('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(question.text);
    utterance.lang = 'ru-RU';
    window.speechSynthesis.speak(utterance);
  };

  const startAnswer = () => {
    if (!question || recording || stopping || pending) return;
    window.speechSynthesis?.cancel();
    setError('');
    try {
      recorderRef.current = startRecorders(stream);
      answerStartedRef.current = performance.now();
      answerDeadlineRef.current =
        performance.now() + question.answerSeconds * 1000;
      setSecondsLeft(question.answerSeconds);
      setRecording(true);
    } catch (caught) {
      setError(errorText(caught));
      setRecording(false);
    }
  };

  if (!question) return null;
  return (
    <main className="interview-room">
      <div className="px-5 pt-4">
        <BackButton
          onClick={() => {
            if (
              (recording || pending || stopping) &&
              !window.confirm(
                'Текущий ответ ещё не сохранён. Выйти из тренировки?',
              )
            )
              return;
            onBack();
          }}
          label="Выйти из тренировки"
        />
      </div>
      <div className="interview-topline">
        <div className="flex items-center gap-2 text-xs font-medium">
          <span
            className={recording ? 'recording-dot' : ''}
            aria-hidden="true"
          />
          {recording
            ? 'Записываем ответ для вашего личного разбора'
            : 'Тренировка не передаётся рекрутеру'}
        </div>
        <div className="interview-timer">
          <Clock3 />
          {formatTimer(secondsLeft)}
        </div>
      </div>
      <div className="interview-content">
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-4 flex flex-wrap justify-center gap-2">
            <Badge className="bg-emerald-50 text-emerald-700">
              Тренировочный пример
            </Badge>
            <Badge variant="outline">{question.topic}</Badge>
          </div>
          <h1 className="interview-question">{question.text}</h1>
          <p className="mt-3 text-xs text-muted-foreground">
            В настоящем интервью вопросы будут другими. Этот ответ будет
            разобран только в вашей тренировке.
          </p>
        </div>
        <div className="voice-stage">
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className="mb-5 aspect-video w-40 rounded-xl bg-black object-cover shadow-lg"
            aria-label="Локальный предпросмотр тренировочной записи"
          />
          <button
            className={`voice-orb ${recording ? 'orb-answering' : 'orb-asking'}`}
            onClick={() => (recording ? void finishAnswer() : startAnswer())}
            disabled={stopping || Boolean(pending)}
            aria-label={
              recording ? 'Закончить тренировочный ответ' : 'Начать ответ'
            }
          >
            <span className="orb-wave orb-wave-one" />
            <span className="orb-wave orb-wave-two" />
            <span className="orb-core">
              {stopping ? (
                <LoaderCircle className="animate-spin" />
              ) : recording ? (
                <Check />
              ) : (
                <Mic />
              )}
            </span>
          </button>
          <p
            className="mt-6 text-center text-sm font-medium"
            aria-live="polite"
          >
            {stopping
              ? pending
                ? uploadProgress < 100
                  ? `Загружаем ответ: ${uploadProgress}%`
                  : 'Ответ загружен. Распознаём речь…'
                : 'Завершаем запись…'
              : recording
                ? 'Говорите и нажмите на круг, когда закончите.'
                : pending
                  ? 'Запись осталась в браузере. Повторите загрузку, чтобы сохранить ответ.'
                  : 'Нажмите на круг, чтобы начать тренировочный ответ.'}
          </p>
          {!recording && !stopping ? (
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={speakQuestion}
            >
              <Volume2 data-icon="inline-start" />
              Озвучить вопрос
            </Button>
          ) : null}
          {error ? (
            <p className="mt-3 text-sm text-rose-700" role="alert">
              {error}
            </p>
          ) : null}
          {pending && !stopping ? (
            <Button className="mt-4" onClick={() => void submitAnswer(pending)}>
              <RotateCcw data-icon="inline-start" /> Повторить загрузку ответа
            </Button>
          ) : null}
        </div>
        <div className="interview-progress-wrap">
          <div className="mb-2 flex justify-between text-xs text-muted-foreground">
            <span>Пример {questionIndex + 1}</span>
            <span>Всего: {questions.length}</span>
          </div>
          <div className="interview-progress">
            <span
              style={{
                width: `${((questionIndex + (recording ? 0.5 : 0)) / Math.max(1, questions.length)) * 100}%`,
              }}
            />
          </div>
        </div>
      </div>
    </main>
  );
}

function IntegrityCaptureNotice({
  integrity,
  waiting,
  restoring,
  onRestore,
  allowHeuristicRetry,
}: {
  integrity: IntegrityCapture;
  waiting: boolean;
  restoring: boolean;
  onRestore: () => void;
  allowHeuristicRetry: boolean;
}) {
  if (!integrity.enabled) return null;
  return (
    <section
      className="mx-auto my-4 max-w-3xl rounded-xl border bg-muted/40 p-4 text-sm"
      aria-live="polite"
    >
      {integrity.blocked || waiting ? (
        <>
          <p className="font-medium">Нужно восстановить запись</p>
          <p className="mt-1 text-muted-foreground">
            Текущий ответ сохраняется. Следующий вопрос появится после
            восстановления камеры, микрофона и всего экрана. Технический сбой не
            считается нарушением.
          </p>
          <Button className="mt-3" onClick={onRestore} disabled={restoring}>
            <Monitor data-icon="inline-start" />
            {restoring
              ? 'Восстанавливаем…'
              : 'Восстановить запись и продолжить'}
          </Button>
        </>
      ) : (
        <p className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-accent-foreground" />
          Камера, микрофон и весь экран записываются непрерывно.
        </p>
      )}
      {integrity.face.status === 'loading' ? (
        <p className="mt-2 text-muted-foreground">
          Готовим локальную калибровку камеры…
        </p>
      ) : null}
      {['ready', 'calibrating'].includes(integrity.face.status) ? (
        <div className="mt-3">
          <p>
            Смотрите на область с вопросом, слегка переводя взгляд по тексту.
            Калибровка займёт около 5 секунд. Эти сигналы не определяют
            нарушение.
          </p>
          {integrity.face.status === 'ready' ? (
            <Button
              className="mt-2"
              variant="outline"
              onClick={integrity.face.calibrate}
            >
              Начать калибровку
            </Button>
          ) : (
            <p className="mt-2">
              Калибровка: {integrity.face.progress}% — держите лицо в кадре.
            </p>
          )}
        </div>
      ) : null}
      {integrity.face.status === 'unavailable' ? (
        <p className="mt-2 text-muted-foreground">
          Локальная проверка камеры недоступна. Интервью и запись продолжаются.{' '}
          {allowHeuristicRetry ? (
            <button className="underline" onClick={integrity.face.retry}>
              Повторить калибровку
            </button>
          ) : null}
        </p>
      ) : null}
      {integrity.uploadError ? (
        <p className="mt-2 text-amber-800">{integrity.uploadError}</p>
      ) : null}
      {integrity.pendingUploads > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Ожидают загрузки: {integrity.pendingUploads} порций и событий.
        </p>
      ) : null}
    </section>
  );
}

function InterviewRoom({
  briefing,
  state,
  stream,
  notify,
  onComplete,
  onTerminalError,
  integrity,
  onRestoreCapture,
}: {
  briefing: InterviewBriefing;
  state: InterviewState;
  stream: MediaStream;
  notify: (message: string) => void;
  onComplete: () => void;
  onTerminalError: (message: string) => void;
  integrity: IntegrityCapture;
  onRestoreCapture: () => Promise<void>;
}) {
  const [question, setQuestion] = useState<PublicQuestion | null>(
    state.integrityBlocked
      ? null
      : state.currentQuestion || briefing.currentQuestion,
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
    | 'capture-paused'
  >('loading-voice');
  const [restoringCapture, setRestoringCapture] = useState(false);
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
  const recordIntegrityEvent = integrity.recordEvent;
  const syncIntegrityHealth = integrity.syncHealth;
  const questionId = question?.id;
  const calibrationPending =
    integrity.enabled &&
    ['idle', 'loading', 'ready', 'calibrating'].includes(integrity.face.status);

  useEffect(() => {
    if (questionId)
      recordIntegrityEvent(
        'question_started',
        {},
        undefined,
        undefined,
        questionId,
      );
  }, [questionId, recordIntegrityEvent]);

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
    if (integrity.enabled && (integrity.blocked || calibrationPending)) {
      setPhase('capture-paused');
      return;
    }
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
      recordIntegrityEvent(
        'answer_started',
        {},
        undefined,
        undefined,
        question?.id,
      );
      setAnswerSeconds(0);
      setPhase('answering');
      setError('');
    } catch (caught) {
      setError(errorText(caught));
      setPhase('error');
    }
  }, [
    answered,
    onComplete,
    onTerminalError,
    question,
    stream,
    integrity.enabled,
    integrity.blocked,
    calibrationPending,
    recordIntegrityEvent,
  ]);

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
    if (
      !question ||
      calibrationPending ||
      (integrity.enabled && integrity.blocked)
    )
      return;
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
    calibrationPending,
    integrity.enabled,
    integrity.blocked,
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
        // Report capture loss before accepting an answer so the server can keep
        // the saved answer while withholding the next question.
        if (integrity.enabled) await syncIntegrityHealth();
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
        if (result.integrityBlocked) {
          setQuestion(null);
          setPhase('capture-paused');
        } else if (result.nextQuestion) {
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
              if (latest.integrityBlocked) {
                setQuestion(null);
                setPhase('capture-paused');
              } else if (latest.currentQuestion) {
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
      integrity.enabled,
      syncIntegrityHealth,
    ],
  );

  const finishAnswer = useCallback(async () => {
    if (!question || phase !== 'answering' || !recordingRef.current) return;
    setPhase('uploading');
    try {
      const active = recordingRef.current;
      recordingRef.current = null;
      recordIntegrityEvent(
        'answer_ended',
        {},
        undefined,
        undefined,
        question.id,
      );
      const blobs = await stopRecorders(active);
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
  }, [phase, question, submitPending, recordIntegrityEvent]);

  useEffect(() => {
    if (!integrity.enabled || !integrity.blocked) return;
    audioRef.current?.pause();
    if (phase === 'answering') void finishAnswer();
  }, [integrity.enabled, integrity.blocked, finishAnswer, phase]);

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

  const restoreCapture = async () => {
    setRestoringCapture(true);
    setError('');
    try {
      await onRestoreCapture();
      const latest = await api.getInterviewState(briefing.interviewId);
      setSecondsRemaining(latest.remainingSeconds);
      secondsRemainingRef.current = latest.remainingSeconds;
      if (latest.integrityBlocked) {
        setPhase('capture-paused');
        return;
      }
      if (latest.currentQuestion) {
        setQuestion(latest.currentQuestion);
        setPhase('loading-voice');
        setVoiceAttempt((value) => value + 1);
      } else if (latest.answeredQuestionIds.length) onComplete();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setRestoringCapture(false);
    }
  };

  const captureNotice = (
    <IntegrityCaptureNotice
      integrity={integrity}
      waiting={phase === 'capture-paused' && !question}
      restoring={restoringCapture || phase === 'uploading'}
      onRestore={() => void restoreCapture()}
      allowHeuristicRetry={
        !pending &&
        [
          'loading-voice',
          'ready-voice',
          'voice-error',
          'capture-paused',
          'error',
        ].includes(phase)
      }
    />
  );

  if (!question) {
    return (
      <main className="candidate-shell">
        {captureNotice}
        {error ? (
          <p className="text-sm text-rose-700" role="alert">
            {error}
          </p>
        ) : null}
        {integrity.enabled ? null : (
          <section className="surface-card p-8 text-center" role="alert">
            <h1 className="font-semibold">Нет активного вопроса</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Вернитесь по ссылке или обратитесь к рекрутеру.
            </p>
          </section>
        )}
      </main>
    );
  }

  return (
    <main className="interview-room">
      {captureNotice}
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
          {integrity.enabled
            ? 'Непрерывная запись камеры, микрофона и экрана'
            : phase === 'answering'
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
                  ? 'bg-secondary text-secondary-foreground'
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
                ? calibrationPending
                  ? 'Завершите калибровку камеры, чтобы начать ответ.'
                  : 'Готовим озвучку вопроса…'
                : phase === 'ready-voice'
                  ? 'Нажмите, чтобы услышать вопрос'
                  : phase === 'voice-error'
                    ? 'Озвучка недоступна'
                    : phase === 'asking'
                      ? 'Slopy озвучивает вопрос'
                      : phase === 'answering'
                        ? `Говорите. Нажмите на микрофон, когда закончите. Автосохранение через ${formatTimer(MAX_ANSWER_SECONDS - answerSeconds)}.`
                        : phase === 'uploading'
                          ? hasVideo
                            ? 'Загружаем аудио и видео, распознаём речь…'
                            : 'Загружаем аудио и распознаём речь…'
                          : phase === 'completing'
                            ? 'Завершаем интервью и запускаем анализ…'
                            : phase === 'capture-paused'
                              ? 'Ожидаем восстановления обязательной записи.'
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
  integrity,
}: {
  outcome: CandidateOutcome | null;
  completing: boolean;
  completionError: string;
  onRetry: () => void;
  integrity: IntegrityCapture;
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
            : 'Команда оценит ответы и примет решение. Эта страница обновится автоматически.'}
        </p>
        {outcome?.status === 'pending' ? (
          <Badge className="mt-5 bg-accent text-accent-foreground">
            Решение ожидается
          </Badge>
        ) : null}
        {integrity.enabled &&
        (integrity.pendingUploads > 0 || integrity.uploadError) ? (
          <div
            className="mx-auto mt-5 max-w-lg rounded-xl bg-amber-50 p-4 text-sm"
            aria-live="polite"
          >
            <p>
              Ответы переданы на оценку. Материалы контроля ещё загружаются;
              оставьте страницу открытой до завершения.
            </p>
            {integrity.uploadError ? (
              <p className="mt-2">{integrity.uploadError}</p>
            ) : null}
            <p className="mt-2">
              Ожидают отправки: {integrity.pendingUploads}.
            </p>
            <Button
              className="mt-3"
              variant="outline"
              onClick={() => void integrity.flush()}
            >
              Повторить загрузку материалов
            </Button>
          </div>
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
  const [practiceSet, setPracticeSet] = useState<PracticeSession | null>(null);
  const [practiceLoading, setPracticeLoading] = useState(false);
  const [practiceError, setPracticeError] = useState('');
  const practiceRequestRef = useRef<AbortController | null>(null);
  const [outcome, setOutcome] = useState<CandidateOutcome | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [completing, setCompleting] = useState(false);
  const [completionError, setCompletionError] = useState('');
  const completionInFlight = useRef(false);
  const integrity = useIntegrityCapture(
    briefing?.interviewId,
    Boolean(briefing?.integrityEnabled || interviewState?.integrityEnabled),
  );
  const finishIntegrity = integrity.finish;

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
          if (!state.currentQuestion && !state.integrityBlocked) {
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

  useEffect(() => {
    return () => practiceRequestRef.current?.abort();
  }, [view, candidateId, briefing?.interviewId]);

  const loadPracticeSet = async () => {
    if (!briefing || briefing.status !== 'ready' || practiceLoading)
      return null;
    const controller = new AbortController();
    practiceRequestRef.current = controller;
    setPracticeLoading(true);
    setPracticeError('');
    try {
      const generated = await practiceApi.create(
        briefing.interviewId,
        controller.signal,
      );
      if (controller.signal.aborted) return null;
      setPracticeSet(generated);
      return generated;
    } catch (caught) {
      if (controller.signal.aborted) return null;
      const message = errorText(caught);
      setPracticeError(message);
      notify(message);
      return null;
    } finally {
      setPracticeLoading(false);
    }
  };

  const openPractice = async () => {
    const available = await loadPracticeSet();
    if (!available) return;
    setView(
      ['analyzing', 'completed', 'error'].includes(available.status) ||
        (available.status === 'in_progress' &&
          !available.currentQuestion &&
          available.answeredQuestionIds.length > 0)
        ? 'practice_complete'
        : 'practice_preflight',
    );
  };

  const startPractice = async (media: MediaStream) => {
    if (!practiceSet) return;
    streamRef.current = media;
    const session = await practiceApi.start(practiceSet.practiceId);
    if (media.getTracks().every((track) => track.readyState === 'ended'))
      return;
    setPracticeSet(session);
    if (!session.currentQuestion) {
      media.getTracks().forEach((track) => track.stop());
      setView('practice_complete');
    } else {
      streamRef.current = media;
      setStream(media);
      setView('practice_interview');
    }
  };

  const leavePractice = (nextView: CandidateView) => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
    setView(nextView);
  };

  const startInterview = async (media: MediaStream, display?: MediaStream) => {
    if (!briefing) return;
    streamRef.current = media;
    setStream(media);
    setError('');
    try {
      if (briefing.integrityEnabled) {
        if (!display)
          throw new Error('Для интервью нужна демонстрация всего экрана.');
        await integrity.start(media, display);
      }
      const state = await api.startInterview(briefing.interviewId, true);
      if (
        !state.currentQuestion &&
        !briefing.currentQuestion &&
        !state.integrityBlocked
      ) {
        await finishIntegrity();
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
      await integrity.pause();
      display?.getTracks().forEach((track) => track.stop());
      media.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setStream(null);
      setView('preparation');
      setError(errorText(caught));
      notify(errorText(caught));
    }
  };

  const restoreCapture = async () => {
    let media = streamRef.current;
    let display = integrity.screen;
    const cameraWorks =
      media
        ?.getVideoTracks()
        .some((track) => track.readyState === 'live' && !track.muted) &&
      media
        ?.getAudioTracks()
        .some((track) => track.readyState === 'live' && !track.muted);
    const displayWorks = display
      ?.getVideoTracks()
      .some((track) => track.readyState === 'live' && !track.muted);
    try {
      // Screen capture must be requested directly from this user gesture.
      if (!displayWorks) display = await requestIntegrityScreen();
      if (!cameraWorks) media = await requestInterviewMedia();
      if (!media || !display)
        throw new Error('Не удалось восстановить обязательные устройства.');
      await integrity.start(media, display);
      if (media !== streamRef.current)
        streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = media;
      setStream(media);
      await integrity.syncHealth();
    } catch (caught) {
      if (media !== streamRef.current)
        media?.getTracks().forEach((track) => track.stop());
      if (display !== integrity.screen)
        display?.getTracks().forEach((track) => track.stop());
      throw caught;
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
    void (async () => {
      await finishIntegrity();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setStream(null);
      setView('processing');
      notify('Интервью завершено и передано команде');
      await finalizeInterview();
    })();
  }, [finalizeInterview, notify, finishIntegrity]);

  const stopAfterTerminalError = useCallback(
    (message: string) => {
      void finishIntegrity();
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
    [notify, finishIntegrity],
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
        integrity={integrity}
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
        integrity={integrity}
        onRestoreCapture={restoreCapture}
      />
    );
  if (view === 'practice_interview' && practiceSet && stream)
    return (
      <PracticeRoom
        practiceSet={practiceSet}
        stream={stream}
        onComplete={() => {
          setPracticeSet((current) =>
            current
              ? { ...current, status: 'analyzing', currentQuestion: null }
              : current,
          );
          leavePractice('practice_complete');
        }}
        onBack={() => leavePractice('preparation')}
      />
    );
  if (view === 'practice_complete' && practiceSet)
    return (
      <PracticeReview
        practiceId={practiceSet.practiceId}
        onBack={() => setView('preparation')}
        notify={notify}
      />
    );
  if (view === 'practice_preflight' && briefing)
    return (
      <Preflight
        practice
        onBack={() => setView('preparation')}
        onReady={startPractice}
      />
    );
  if (view === 'preflight' && briefing)
    return (
      <>
        <Preflight
          onBack={() => setView('preparation')}
          onReady={startInterview}
          integrityEnabled={Boolean(briefing.integrityEnabled)}
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
        practiceSet={practiceSet}
        practiceLoading={practiceLoading}
        practiceError={practiceError}
        onBack={() => setView('home')}
        onContinue={() => setView('preflight')}
        onLoadExamples={() => void loadPracticeSet()}
        onPractice={() => void openPractice()}
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
