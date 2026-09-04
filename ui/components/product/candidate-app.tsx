'use client';

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';
import {
  ArrowRight,
  BriefcaseBusiness,
  Camera,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  FileCheck2,
  Lightbulb,
  LockKeyhole,
  Mic,
  Mic2,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Volume2,
  WifiOff,
} from 'lucide-react';

import { BackButton, StatusPill } from '@/components/product/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { mockApi } from '@/lib/mock-api';
import {
  candidateHistories,
  getCandidateStatus,
  questionTopics,
  type Candidate,
  type InterviewHistory,
  type Position,
} from '@/lib/mock-data';

type CandidateView =
  | { type: 'home' }
  | { type: 'preparation' }
  | { type: 'preflight' }
  | { type: 'interview' }
  | { type: 'processing' }
  | { type: 'overview' }
  | { type: 'history'; historyId: string };

type CandidateAppProps = {
  candidateId: string;
  positions: Position[];
  setPositions: Dispatch<SetStateAction<Position[]>>;
  notify: (message: string) => void;
};

type LiveQuestion = {
  id: string;
  text: string;
  topic: string;
  kind: 'core' | 'follow_up';
};

function CurrentInterviewCard({
  position,
  candidate,
  onOpen,
}: {
  position: Position;
  candidate: Candidate;
  onOpen: () => void;
}) {
  const status = getCandidateStatus(candidate);
  return (
    <button className="candidate-interview-card group" onClick={onOpen}>
      <div className="flex min-w-0 flex-1 items-start gap-4">
        <span className="company-mark" aria-hidden="true">N</span>
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-medium text-muted-foreground">Neon</span>
          <span className="mt-1 block truncate text-lg font-semibold tracking-[-0.02em]">
            {position.title}
          </span>
          <span className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Clock3 className="size-3.5" aria-hidden="true" /> 25–30 минут
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Volume2 className="size-3.5" aria-hidden="true" /> Вопросы озвучиваются
            </span>
          </span>
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <StatusPill status={status} candidateView />
        <span className="grid size-10 place-items-center rounded-full bg-muted transition group-hover:bg-accent group-hover:text-accent-foreground">
          <ChevronRight className="size-4" aria-hidden="true" />
        </span>
      </div>
    </button>
  );
}

function HistoryCard({ item, onOpen }: { item: InterviewHistory; onOpen: () => void }) {
  const status = item.status;
  return (
    <button className="history-interview-row group" onClick={onOpen}>
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted text-sm font-semibold">
        {item.company[0]}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{item.positionTitle}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {item.company} · {item.date}
        </span>
      </span>
      <StatusPill status={status} candidateView />
      <ChevronRight
        className="size-4 text-muted-foreground transition group-hover:text-foreground"
        aria-hidden="true"
      />
    </button>
  );
}

function CandidateHome({
  firstName,
  position,
  candidate,
  history,
  onOpenCurrent,
  onOpenHistory,
}: {
  firstName: string;
  position: Position;
  candidate: Candidate;
  history: InterviewHistory[];
  onOpenCurrent: () => void;
  onOpenHistory: (historyId: string) => void;
}) {
  return (
    <main className="candidate-shell">
      <div className="candidate-welcome">
        <div>
          <p className="eyebrow">Ваши интервью</p>
          <h1 className="page-title">Здравствуйте, {firstName}</h1>
          <p className="mt-3 max-w-2xl text-[15px] text-muted-foreground">
            Здесь видно, что нужно сделать сейчас и какие решения уже приняла команда.
          </p>
        </div>
        <div className="candidate-privacy-note">
          <ShieldCheck aria-hidden="true" />
          <span>AI не оценивает внешность, акцент или эмоции.</span>
        </div>
      </div>

      <section aria-labelledby="current-interview-heading">
        <div className="mb-3 flex items-center justify-between px-1">
          <h2 id="current-interview-heading" className="text-sm font-semibold">Актуальное</h2>
          <span className="text-xs text-muted-foreground">1 интервью</span>
        </div>
        <CurrentInterviewCard position={position} candidate={candidate} onOpen={onOpenCurrent} />
      </section>

      <section className="mt-9" aria-labelledby="history-heading">
        <div className="mb-3 flex items-center justify-between px-1">
          <h2 id="history-heading" className="text-sm font-semibold">История</h2>
          <span className="text-xs text-muted-foreground">{history.length} интервью</span>
        </div>
        <div className="surface-card p-2 sm:p-3">
          {history.map((item) => (
            <HistoryCard key={item.id} item={item} onOpen={() => onOpenHistory(item.id)} />
          ))}
        </div>
      </section>
    </main>
  );
}

function PreparationView({
  position,
  onBack,
  onContinue,
}: {
  position: Position;
  onBack: () => void;
  onContinue: () => void;
}) {
  const [consent, setConsent] = useState(false);
  const steps = [
    {
      icon: Camera,
      title: 'Проверка устройств',
      text: 'Попросим доступ к камере и микрофону и покажем превью.',
    },
    {
      icon: Volume2,
      title: '6 основных вопросов',
      text: 'Каждый вопрос появится на экране и будет озвучен.',
    },
    {
      icon: Mic2,
      title: 'Ответ в своём темпе',
      text: 'Когда закончите, нажмите на круг в центре экрана.',
    },
    {
      icon: FileCheck2,
      title: 'Проверка командой',
      text: 'AI соберёт evidence, а решение примет человек.',
    },
  ];

  return (
    <main className="candidate-shell max-w-6xl">
      <BackButton onClick={onBack} label="К интервью" />
      <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div>
          <p className="eyebrow">Перед началом</p>
          <h1 className="page-title max-w-3xl">Интервью на позицию {position.title}</h1>
          <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
            Заложите 25–30 минут и выберите тихое место. Основных вопросов шесть;
            AI может задать одно короткое уточнение по вашему ответу.
          </p>

          <section className="mt-8 surface-card p-5 sm:p-6" aria-labelledby="process-heading">
            <h2 id="process-heading" className="text-base font-semibold">Как всё пройдёт</h2>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {steps.map(({ icon: Icon, title, text }, index) => (
                <article key={title} className="process-step">
                  <div className="flex items-center gap-3">
                    <span className="grid size-9 place-items-center rounded-xl bg-accent text-accent-foreground">
                      <Icon className="size-4" aria-hidden="true" />
                    </span>
                    <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      Шаг {index + 1}
                    </span>
                  </div>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="mt-4 surface-card p-5 sm:p-6" aria-labelledby="topics-heading">
            <div className="flex items-center gap-2">
              <Lightbulb className="size-4 text-primary" aria-hidden="true" />
              <h2 id="topics-heading" className="text-base font-semibold">Каких тем ожидать</h2>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {questionTopics.map((topic) => (
                <span key={topic} className="topic-chip">{topic}</span>
              ))}
            </div>
          </section>
        </div>

        <aside className="lg:pt-10">
          <div className="surface-card sticky top-24 p-5 sm:p-6">
            <div className="mb-5 flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-[#eef7ff] text-blue-700">
                <LockKeyhole className="size-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-sm font-semibold">Запись и обработка</h2>
                <p className="text-xs text-muted-foreground">Нужно ваше согласие</p>
              </div>
            </div>
            <ul className="space-y-3 text-xs leading-relaxed text-muted-foreground">
              <li className="flex gap-2"><Check className="mt-0.5 size-3.5 shrink-0 text-emerald-600" /> Видео и звук используются для транскрипта и проверки ответов.</li>
              <li className="flex gap-2"><Check className="mt-0.5 size-3.5 shrink-0 text-emerald-600" /> Материалы видит только нанимающая команда.</li>
              <li className="flex gap-2"><Check className="mt-0.5 size-3.5 shrink-0 text-emerald-600" /> Данные не используются для обучения без отдельного разрешения.</li>
            </ul>

            <label className="consent-row" htmlFor="interview-consent">
              <Checkbox
                id="interview-consent"
                checked={consent}
                onCheckedChange={(checked) => setConsent(checked === true)}
                aria-label="Согласие на запись и обработку"
              />
              <span>Я согласен на запись и обработку материалов этого интервью.</span>
            </label>

            <Button
              size="lg"
              className="mt-5 h-12 w-full rounded-xl"
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

function PreflightView({
  onBack,
  onStream,
  onStart,
}: {
  onBack: () => void;
  onStream: (stream: MediaStream | null) => void;
  onStart: () => void;
}) {
  const [permission, setPermission] = useState<'idle' | 'requesting' | 'granted' | 'denied'>('idle');
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const requestPermissions = async () => {
    setPermission('requesting');
    setErrorMessage('');
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Браузер не поддерживает доступ к камере и микрофону.');
      }
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: { facingMode: 'user' },
      });
      setStream(mediaStream);
      onStream(mediaStream);
      setPermission('granted');
    } catch (error) {
      setPermission('denied');
      setErrorMessage(
        error instanceof Error
          ? error.message
          : 'Не удалось получить доступ к камере и микрофону.',
      );
    }
  };

  return (
    <main className="candidate-shell max-w-5xl">
      <BackButton onClick={onBack} label="К подготовке" />
      <div className="mb-7 text-center">
        <p className="eyebrow">Проверка устройств</p>
        <h1 className="page-title">Камера и микрофон</h1>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Разрешение запросит браузер. Мы используем поток только внутри демонстрации интервью.
        </p>
      </div>

      <div className="preflight-grid">
        <div className="camera-preview">
          {stream ? (
            <video ref={videoRef} autoPlay muted playsInline aria-label="Предпросмотр камеры" />
          ) : (
            <div className="text-center text-white/70">
              <Camera className="mx-auto size-9" aria-hidden="true" />
              <p className="mt-3 text-sm">Предпросмотр появится здесь</p>
            </div>
          )}
          <span className="camera-label">
            <CircleDot className="size-3.5" aria-hidden="true" />
            {permission === 'granted' ? 'Камера работает' : 'Предпросмотр'}
          </span>
        </div>

        <div className="surface-card p-5 sm:p-6">
          <h2 className="text-base font-semibold">Состояние устройств</h2>
          <div className="mt-5 space-y-3">
            <div className="device-check-row">
              <span><Camera aria-hidden="true" /> Камера</span>
              <span className={permission === 'granted' ? 'text-emerald-700' : 'text-muted-foreground'}>
                {permission === 'granted' ? 'Готова' : 'Нужен доступ'}
              </span>
            </div>
            <div className="device-check-row">
              <span><Mic aria-hidden="true" /> Микрофон</span>
              <span className={permission === 'granted' ? 'text-emerald-700' : 'text-muted-foreground'}>
                {permission === 'granted' ? 'Готов' : 'Нужен доступ'}
              </span>
            </div>
          </div>

          {permission === 'denied' ? (
            <div className="permission-error" role="alert">
              <p className="font-medium">Доступ не получен</p>
              <p>{errorMessage || 'Проверьте настройки браузера и попробуйте снова.'}</p>
            </div>
          ) : null}

          {permission === 'granted' ? (
            <div className="mt-5 rounded-xl bg-emerald-50 p-3 text-xs leading-relaxed text-emerald-800">
              Всё готово. Когда интервью начнётся, вы увидите статус записи и услышите первый вопрос.
            </div>
          ) : null}

          <div className="mt-5 space-y-2">
            {permission === 'granted' ? (
              <Button size="lg" className="h-12 w-full rounded-xl" onClick={onStart}>
                Начать интервью
                <ArrowRight data-icon="inline-end" />
              </Button>
            ) : (
              <Button
                size="lg"
                className="h-12 w-full rounded-xl"
                onClick={requestPermissions}
                disabled={permission === 'requesting'}
              >
                {permission === 'requesting' ? 'Запрашиваем доступ…' : 'Разрешить камеру и микрофон'}
              </Button>
            )}
            {permission === 'denied' ? (
              <>
                <Button variant="outline" size="lg" className="h-11 w-full rounded-xl" onClick={requestPermissions}>
                  <RotateCcw data-icon="inline-start" /> Попробовать снова
                </Button>
                <Button
                  variant="ghost"
                  size="lg"
                  className="h-11 w-full rounded-xl"
                  onClick={() => {
                    onStream(null);
                    onStart();
                  }}
                >
                  Продолжить демо без записи
                </Button>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </main>
  );
}

function formatTimer(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes.toString().padStart(2, '0')}:${rest.toString().padStart(2, '0')}`;
}

function InterviewRoom({
  questions,
  stream,
  onComplete,
  notify,
}: {
  questions: LiveQuestion[];
  stream: MediaStream | null;
  onComplete: () => void;
  notify: (message: string) => void;
}) {
  const [questionIndex, setQuestionIndex] = useState(0);
  const [secondsRemaining, setSecondsRemaining] = useState(30 * 60);
  const [phase, setPhase] = useState<'asking' | 'answering'>('asking');
  const [saving, setSaving] = useState(false);
  const [savedAnswers, setSavedAnswers] = useState(0);
  const [signalLevel, setSignalLevel] = useState(0.35);
  const [online, setOnline] = useState(() =>
    typeof navigator === 'undefined' ? true : navigator.onLine,
  );
  const completedRef = useRef(false);
  const currentQuestion = questions[questionIndex];
  const timerUrgent = secondsRemaining <= 120;

  const finish = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    window.speechSynthesis?.cancel();
    onComplete();
  }, [onComplete]);

  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsRemaining((current) => {
        if (current <= 1) {
          window.clearInterval(timer);
          window.setTimeout(finish, 0);
          return 0;
        }
        return current - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [finish]);

  useEffect(() => {
    const fallbackTimer = window.setTimeout(() => setPhase('answering'), 5000);
    if ('speechSynthesis' in window && 'SpeechSynthesisUtterance' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(currentQuestion.text);
      utterance.lang = 'ru-RU';
      utterance.rate = 1.04;
      utterance.onend = () => {
        window.clearTimeout(fallbackTimer);
        setPhase('answering');
      };
      utterance.onerror = () => {
        window.clearTimeout(fallbackTimer);
        setPhase('answering');
      };
      window.speechSynthesis.speak(utterance);
    }
    return () => {
      window.clearTimeout(fallbackTimer);
      window.speechSynthesis?.cancel();
    };
  }, [currentQuestion.id, currentQuestion.text]);

  useEffect(() => {
    if (!stream || phase !== 'answering') return;
    const audioTrack = stream.getAudioTracks()[0];
    if (!audioTrack) return;

    let animationFrame = 0;
    let audioContext: AudioContext | null = null;
    try {
      audioContext = new AudioContext();
      const analyser = audioContext.createAnalyser();
      const source = audioContext.createMediaStreamSource(stream);
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.82;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const update = () => {
        analyser.getByteFrequencyData(data);
        const average = data.reduce((sum, value) => sum + value, 0) / data.length;
        setSignalLevel(Math.min(1, Math.max(0.22, average / 80)));
        animationFrame = window.requestAnimationFrame(update);
      };
      update();
    } catch {
      // The visual remains available even if Web Audio isn't supported.
    }

    return () => {
      window.cancelAnimationFrame(animationFrame);
      void audioContext?.close();
    };
  }, [phase, stream]);

  const skipSpeech = () => {
    window.speechSynthesis?.cancel();
    setPhase('answering');
  };

  const saveAndContinue = async () => {
    if (phase !== 'answering' || saving) return;
    setSaving(true);
    await mockApi.saveInterviewAnswer(currentQuestion.id);
    const nextSaved = savedAnswers + 1;
    setSavedAnswers(nextSaved);
    setSaving(false);
    if (questionIndex >= questions.length - 1) {
      finish();
      return;
    }
    notify(`Ответ ${nextSaved} сохранён`);
    setPhase('asking');
    setQuestionIndex((current) => current + 1);
  };

  return (
    <main className="interview-room">
      {!online ? (
        <output className="offline-banner">
          <WifiOff className="size-4" aria-hidden="true" />
          Сети нет — текущий ответ сохраняется локально и отправится после восстановления.
        </output>
      ) : null}

      <div className="interview-topline">
        <div className="flex items-center gap-2 text-xs font-medium">
          <span className="recording-dot" aria-hidden="true" />
          {stream ? 'Идёт запись' : 'Демо без записи'}
        </div>
        <div className={`interview-timer ${timerUrgent ? 'timer-urgent' : ''}`} aria-label={`Осталось ${formatTimer(secondsRemaining)}`}>
          <Clock3 aria-hidden="true" />
          {formatTimer(secondsRemaining)}
        </div>
      </div>

      <div className="interview-content">
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-4 flex flex-wrap items-center justify-center gap-2">
            <Badge variant="outline">Вопрос {questionIndex + 1} из {questions.length}</Badge>
            <Badge className={currentQuestion.kind === 'follow_up' ? 'bg-violet-50 text-violet-700' : 'bg-muted text-foreground'}>
              {currentQuestion.kind === 'follow_up' ? 'AI-уточнение' : currentQuestion.topic}
            </Badge>
          </div>
          <h1 className="interview-question">{currentQuestion.text}</h1>
          {currentQuestion.kind === 'follow_up' ? (
            <p className="mt-3 text-xs text-muted-foreground">Основание: предыдущий ответ не раскрыл безопасный replay.</p>
          ) : null}
        </div>

        <div className="voice-stage">
          <button
            className={`voice-orb ${phase === 'asking' ? 'orb-asking' : 'orb-answering'}`}
            style={
              {
                '--signal-level': phase === 'asking' ? 0.72 : signalLevel,
                '--orb-scale': (
                  1.02 + (phase === 'asking' ? 0.72 : signalLevel) * 0.16
                ).toFixed(3),
              } as React.CSSProperties
            }
            onClick={saveAndContinue}
            disabled={phase === 'asking' || saving}
            aria-label={
              phase === 'asking'
                ? 'Signal озвучивает вопрос'
                : saving
                  ? 'Сохраняем ответ'
                  : 'Закончить ответ и перейти дальше'
            }
          >
            <span className="orb-wave orb-wave-one" aria-hidden="true" />
            <span className="orb-wave orb-wave-two" aria-hidden="true" />
            <span className="orb-core" aria-hidden="true">
              {phase === 'asking' ? <Volume2 /> : saving ? <CircleDot /> : <Check />}
            </span>
          </button>
          <div className="mt-6 min-h-14 text-center" aria-live="polite">
            <p className="text-sm font-medium">
              {phase === 'asking'
                ? 'Signal озвучивает вопрос'
                : saving
                  ? 'Сохраняем ответ…'
                  : 'Говорите. Нажмите на круг, когда закончите.'}
            </p>
            {phase === 'asking' ? (
              <Button variant="ghost" size="sm" className="mt-1" onClick={skipSpeech}>
                Перейти к ответу
              </Button>
            ) : (
              <p className="mt-1 text-xs text-muted-foreground">
                Волны реагируют на громкость речи. Текст вопроса всегда остаётся на экране.
              </p>
            )}
          </div>
        </div>

        <div className="interview-progress-wrap">
          <div className="mb-2 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>{savedAnswers ? `Сохранено ответов: ${savedAnswers}` : 'Первый ответ ещё не сохранён'}</span>
            <span>{Math.round((questionIndex / questions.length) * 100)}%</span>
          </div>
          <div className="interview-progress" aria-hidden="true">
            <span style={{ width: `${(questionIndex / questions.length) * 100}%` }} />
          </div>
        </div>
      </div>
    </main>
  );
}

function ProcessingView() {
  return (
    <main className="candidate-shell grid min-h-[calc(100dvh-68px)] place-items-center py-12 text-center">
      <div>
        <div className="processing-orb" aria-hidden="true"><Sparkles /></div>
        <p className="eyebrow mt-7">Отправляем интервью</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em]">Сохраняем последние ответы</h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
          После загрузки AI структурирует evidence, а нанимающая команда проверит результат.
        </p>
      </div>
    </main>
  );
}

function CurrentOverview({
  candidate,
  position,
  onBack,
}: {
  candidate: Candidate;
  position: Position;
  onBack: () => void;
}) {
  const status = getCandidateStatus(candidate);

  if (status === 'rejected') {
    return (
      <FeedbackOverview
        company="Neon"
        positionTitle={position.title}
        feedback={candidate.decision?.feedback || 'Команда завершила рассмотрение позиции.'}
        onBack={onBack}
      />
    );
  }

  if (status === 'next_stage') {
    return (
      <main className="candidate-shell max-w-4xl">
        <BackButton onClick={onBack} label="К интервью" />
        <div className="overview-hero overview-success">
          <span className="overview-icon"><CheckCircle2 aria-hidden="true" /></span>
          <Badge className="bg-emerald-100 text-emerald-800">Позвали дальше</Badge>
          <h1>Команда хочет продолжить знакомство</h1>
          <p>{candidate.decision?.feedback || 'Рекрутер свяжется с вами и предложит время следующего этапа.'}</p>
        </div>
        <div className="mt-4 surface-card p-5 sm:p-6">
          <h2 className="text-sm font-semibold">Что дальше</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Следующий этап — разговор с техническим лидом. Вопросы будут про личный вклад в CI/CD,
            Kubernetes и измеримые результаты проектов.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="candidate-shell max-w-4xl">
      <BackButton onClick={onBack} label="К интервью" />
      <div className="overview-hero">
        <span className="overview-icon"><CheckCircle2 aria-hidden="true" /></span>
        <Badge className="bg-blue-50 text-blue-700">Интервью отправлено</Badge>
        <h1>Спасибо, всё получилось</h1>
        <p>
          Ответы сохранены. Теперь AI соберёт проверяемые фрагменты, а решение примет нанимающая команда.
        </p>
      </div>

      <section className="mt-4 surface-card p-5 sm:p-6" aria-labelledby="next-process-heading">
        <h2 id="next-process-heading" className="text-base font-semibold">Что происходит дальше</h2>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {[
            ['1', 'Структурируем ответы', 'AI связывает выводы с вопросами и цитатами.'],
            ['2', 'Команда проверяет', 'Рекрутер читает evidence и принимает решение.'],
            ['3', 'Вы получите ответ', 'Обычно в течение трёх рабочих дней.'],
          ].map(([number, title, text]) => (
            <article key={number} className="next-process-card">
              <span>{number}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function FeedbackOverview({
  company,
  positionTitle,
  feedback,
  onBack,
}: {
  company: string;
  positionTitle: string;
  feedback: string;
  onBack: () => void;
}) {
  return (
    <main className="candidate-shell max-w-4xl">
      <BackButton onClick={onBack} label="К интервью" />
      <div className="overview-hero overview-feedback">
        <span className="overview-icon"><BriefcaseBusiness aria-hidden="true" /></span>
        <Badge className="bg-rose-50 text-rose-700">Отказ</Badge>
        <h1>Команда завершила рассмотрение</h1>
        <p>{company} · {positionTitle}</p>
      </div>
      <section className="mt-4 surface-card p-5 sm:p-7" aria-labelledby="feedback-heading">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-accent text-accent-foreground">
            <FileCheck2 className="size-5" aria-hidden="true" />
          </span>
          <div>
            <h2 id="feedback-heading" className="text-base font-semibold">Фидбэк команды</h2>
            <p className="text-xs text-muted-foreground">Только по требованиям позиции и вашим ответам</p>
          </div>
        </div>
        <p className="mt-5 text-[15px] leading-7 text-foreground/85">{feedback}</p>
        <div className="mt-6 rounded-xl bg-muted p-4 text-xs leading-relaxed text-muted-foreground">
          AI помог структурировать материалы, но решение и этот фидбэк подтвердил человек.
        </div>
      </section>
    </main>
  );
}

function HistoryOverview({ item, onBack }: { item: InterviewHistory; onBack: () => void }) {
  if (item.status === 'rejected') {
    return (
      <FeedbackOverview
        company={item.company}
        positionTitle={item.positionTitle}
        feedback={item.feedback || 'Команда завершила рассмотрение.'}
        onBack={onBack}
      />
    );
  }

  return (
    <main className="candidate-shell max-w-4xl">
      <BackButton onClick={onBack} label="К интервью" />
      <div className="overview-hero overview-success">
        <span className="overview-icon"><CheckCircle2 aria-hidden="true" /></span>
        <Badge className="bg-emerald-100 text-emerald-800">Позвали дальше</Badge>
        <h1>{item.company} приглашает вас дальше</h1>
        <p>{item.positionTitle}</p>
      </div>
      <div className="mt-4 surface-card p-5 sm:p-6">
        <h2 className="text-sm font-semibold">Следующий шаг</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {item.nextStep || 'Команда свяжется с вами и предложит время следующего этапа.'}
        </p>
      </div>
    </main>
  );
}

export function CandidateApp({
  candidateId,
  positions,
  setPositions,
  notify,
}: CandidateAppProps) {
  const [view, setView] = useState<CandidateView>({ type: 'home' });
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);

  let match: { position: Position; candidate: Candidate } | undefined;
  for (const position of positions) {
    const candidate = position.candidates.find((item) => item.id === candidateId);
    if (candidate) {
      match = { position, candidate };
      break;
    }
  }

  const history = candidateHistories[candidateId] || [];
  const selectedHistory =
    view.type === 'history' ? history.find((item) => item.id === view.historyId) : undefined;

  useEffect(() => {
    return () => {
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const updateCandidate = useCallback(
    (update: Partial<Candidate>) => {
      setPositions((current) =>
        current.map((position) => ({
          ...position,
          candidates: position.candidates.map((candidate) =>
            candidate.id === candidateId ? { ...candidate, ...update } : candidate,
          ),
        })),
      );
    },
    [candidateId, setPositions],
  );

  const completeInterview = useCallback(async () => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    setMediaStream(null);
    updateCandidate({ processingStatus: 'recorded' });
    setView({ type: 'processing' });
    const result = await mockApi.submitInterview();
    updateCandidate({
      processingStatus: result.processingStatus,
      analysis: result.analysis,
      hiringDecision: 'pending',
    });
    notify('Интервью отправлено нанимающей команде');
    setView({ type: 'overview' });
  }, [notify, updateCandidate]);

  if (!match) {
    return (
      <main className="candidate-shell">
        <div className="surface-card p-8 text-center">
          <h1 className="text-xl font-semibold">Интервью не найдено</h1>
          <p className="mt-2 text-sm text-muted-foreground">Переключитесь на другого тестового пользователя.</p>
        </div>
      </main>
    );
  }

  const { position, candidate } = match;
  const questions: LiveQuestion[] = position.questions.flatMap((text, index) => {
    const base: LiveQuestion = {
      id: `question-${index + 1}`,
      text,
      topic: questionTopics[index] || 'Технический опыт',
      kind: 'core',
    };
    if (index === 1) {
      return [
        base,
        {
          id: 'follow-up-messaging',
          text:
            'Уточните: как вы ограничивали количество повторов и безопасно переигрывали сообщения из dead-letter очереди?',
          topic: 'Надёжность сообщений',
          kind: 'follow_up' as const,
        },
      ];
    }
    return [base];
  });

  if (view.type === 'preparation') {
    return (
      <PreparationView
        position={position}
        onBack={() => setView({ type: 'home' })}
        onContinue={() => setView({ type: 'preflight' })}
      />
    );
  }

  if (view.type === 'preflight') {
    return (
      <PreflightView
        onBack={() => setView({ type: 'preparation' })}
        onStream={(stream) => {
          mediaStreamRef.current = stream;
          setMediaStream(stream);
        }}
        onStart={() => setView({ type: 'interview' })}
      />
    );
  }

  if (view.type === 'interview') {
    return (
      <InterviewRoom
        questions={questions}
        stream={mediaStream}
        onComplete={completeInterview}
        notify={notify}
      />
    );
  }

  if (view.type === 'processing') {
    return <ProcessingView />;
  }

  if (view.type === 'overview') {
    return (
      <CurrentOverview
        candidate={candidate}
        position={position}
        onBack={() => setView({ type: 'home' })}
      />
    );
  }

  if (view.type === 'history' && selectedHistory) {
    return <HistoryOverview item={selectedHistory} onBack={() => setView({ type: 'home' })} />;
  }

  return (
    <CandidateHome
      firstName={candidate.name.split(' ')[0]}
      position={position}
      candidate={candidate}
      history={history}
      onOpenCurrent={() => {
        if (getCandidateStatus(candidate) === 'needs_interview') {
          setView({ type: 'preparation' });
        } else {
          setView({ type: 'overview' });
        }
      }}
      onOpenHistory={(historyId) => setView({ type: 'history', historyId })}
    />
  );
}
