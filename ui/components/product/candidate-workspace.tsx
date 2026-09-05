'use client';

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from 'react';
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clipboard,
  Download,
  Eye,
  LoaderCircle,
  LockKeyhole,
  Play,
  RotateCcw,
  Save,
  Sparkles,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { Textarea } from '@/components/ui/textarea';
import { api, ApiError } from '@/lib/api';
import type {
  Analysis,
  AnalysisEvidence,
  Approval,
  CandidateDetail,
  CandidateMedia,
  MediaAsset,
  DecisionInput,
  HiringDecision,
  InterviewQuestion,
  ProcessingStatus,
} from '@/lib/types';

function errorText(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error
    ? error.message
    : 'Произошла неизвестная ошибка.';
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
  }).format(date);
}

function initials(name: string) {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'К'
  );
}

function statusCopy(status: ProcessingStatus, decision: HiringDecision) {
  if (decision === 'next_stage')
    return {
      label: 'Следующий этап',
      className: 'bg-emerald-50 text-emerald-700',
    };
  if (decision === 'rejected')
    return { label: 'Отказ', className: 'bg-rose-50 text-rose-700' };
  if (status === 'ready' || status === 'completed')
    return { label: 'Нужно решение', className: 'bg-amber-50 text-amber-800' };
  if (status === 'invited')
    return {
      label: 'Приглашение готово',
      className: 'bg-blue-50 text-blue-700',
    };
  if (status === 'in_progress')
    return {
      label: 'Интервью идёт',
      className: 'bg-blue-50 text-blue-700',
    };
  if (status === 'not_started' || status === 'questions_draft')
    return {
      label: 'Согласовать вопросы',
      className: 'bg-violet-50 text-violet-700',
    };
  if (status === 'error')
    return { label: 'Ошибка обработки', className: 'bg-rose-50 text-rose-700' };
  return {
    label: 'AI обрабатывает',
    className: 'bg-violet-50 text-violet-700',
  };
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
      <ArrowLeft data-icon="inline-start" />
      {label}
    </Button>
  );
}

function Busy({ label = 'Загружаем…' }: { label?: string }) {
  return (
    <div
      className="grid min-h-72 place-items-center text-center"
      aria-live="polite"
      aria-busy="true"
    >
      <div>
        <LoaderCircle
          className="mx-auto size-7 animate-spin text-primary"
          aria-hidden="true"
        />
        <p className="mt-3 text-sm text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="surface-card p-7 text-center" role="alert">
      <p className="font-medium">Не удалось загрузить данные</p>
      <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      <Button variant="outline" className="mt-5" onClick={onRetry}>
        Повторить
      </Button>
    </div>
  );
}

type QuestionDraft = Pick<InterviewQuestion, 'text' | 'topic' | 'competency'>;

function QuestionApproval({
  candidate,
  notify,
}: {
  candidate: CandidateDetail;
  notify: (message: string) => void;
}) {
  const [questions, setQuestions] = useState(candidate.questions);
  const [drafts, setDrafts] = useState<Record<string, QuestionDraft>>(() =>
    Object.fromEntries(
      candidate.questions.map((question) => [
        question.id,
        {
          text: question.text,
          topic: question.topic,
          competency: question.competency,
        },
      ]),
    ),
  );
  const [savingId, setSavingId] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [error, setError] = useState('');
  const questionsLocked =
    questions.length > 0 &&
    questions.every((question) => question.status !== 'draft');

  const saveQuestion = async (question: InterviewQuestion) => {
    if (question.status !== 'draft') return question;
    const draft = drafts[question.id];
    if (!draft) return question;
    setSavingId(question.id);
    try {
      const updated = await api.updateCandidateQuestion(
        candidate.id,
        question.id,
        draft,
      );
      setQuestions((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
      return updated;
    } catch (caught) {
      setError(errorText(caught));
      return null;
    } finally {
      setSavingId(null);
    }
  };

  const approve = async () => {
    setApproving(true);
    setError('');
    try {
      for (const question of questions.filter(
        (item) => item.status === 'draft',
      )) {
        if (!(await saveQuestion(question))) return;
      }
      const result = await api.approveCandidateQuestions(candidate.id);
      setApproval(result);
      notify('Вопросы согласованы, ссылка готова');
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setApproving(false);
    }
  };

  const copyInvite = async () => {
    if (!approval) return;
    try {
      await navigator.clipboard.writeText(approval.inviteUrl);
      notify('Ссылка скопирована');
    } catch {
      setError(
        'Браузер не разрешил копирование. Выделите ссылку вручную или откройте её напрямую.',
      );
    }
  };

  return (
    <div className="space-y-4">
      <section className="surface-card p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">Вопросы кандидату</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {questionsLocked
                ? 'Вопросы согласованы и больше не редактируются.'
                : 'Проверьте формулировки и темы до создания ссылки.'}
            </p>
          </div>
          <Badge variant="outline">{questions.length} вопросов</Badge>
        </div>
        <div className="mt-5 space-y-3">
          {questions.map((question, index) => {
            const draft = drafts[question.id];
            return (
              <article
                key={question.id}
                className="rounded-2xl border bg-muted/20 p-4"
              >
                <div className="mb-3 flex items-center gap-2">
                  <Badge variant="outline">{index + 1}</Badge>
                  <Badge
                    className={
                      question.kind === 'provided'
                        ? 'bg-blue-50 text-blue-700'
                        : 'bg-violet-50 text-violet-700'
                    }
                  >
                    {question.kind === 'provided' ? 'Общий пул' : 'AI'}
                  </Badge>
                </div>
                <label
                  className="field-label"
                  htmlFor={`question-${question.id}`}
                >
                  Формулировка
                  <Textarea
                    id={`question-${question.id}`}
                    className="mt-2 min-h-24"
                    value={draft?.text || ''}
                    readOnly={question.status !== 'draft'}
                    onChange={(e) =>
                      setDrafts((current) => ({
                        ...current,
                        [question.id]: {
                          ...current[question.id],
                          text: e.target.value,
                        },
                      }))
                    }
                  />
                </label>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label
                    className="field-label"
                    htmlFor={`topic-${question.id}`}
                  >
                    Тема
                    <Input
                      id={`topic-${question.id}`}
                      className="mt-2"
                      value={draft?.topic || ''}
                      readOnly={question.status !== 'draft'}
                      onChange={(e) =>
                        setDrafts((current) => ({
                          ...current,
                          [question.id]: {
                            ...current[question.id],
                            topic: e.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                  <label
                    className="field-label"
                    htmlFor={`competency-${question.id}`}
                  >
                    Критерий
                    <Input
                      id={`competency-${question.id}`}
                      className="mt-2"
                      value={draft?.competency || ''}
                      readOnly={question.status !== 'draft'}
                      onChange={(e) =>
                        setDrafts((current) => ({
                          ...current,
                          [question.id]: {
                            ...current[question.id],
                            competency: e.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                </div>
                {question.status === 'draft' ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={() => void saveQuestion(question)}
                    disabled={savingId === question.id}
                  >
                    <Save data-icon="inline-start" />
                    {savingId === question.id ? 'Сохраняем…' : 'Сохранить'}
                  </Button>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>

      {approval ? (
        <section className="surface-card border-emerald-200 p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 size-5 text-emerald-600" />
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold">Ссылка готова</h2>
              <p className="mt-1 break-all text-sm text-muted-foreground">
                {approval.inviteUrl}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                Действует до {formatDate(approval.expiresAt)}
              </p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => void copyInvite()}>
              <Clipboard data-icon="inline-start" />
              Скопировать ссылку
            </Button>
            <a
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border bg-background px-2.5 text-sm font-medium hover:bg-muted"
              href={approval.inviteUrl}
            >
              Открыть интервью
              <ArrowUpRight className="size-4" aria-hidden="true" />
            </a>
          </div>
        </section>
      ) : (
        <div className="sticky-form-actions">
          <span className="mr-auto hidden text-xs text-muted-foreground sm:block">
            {questionsLocked
              ? 'Будет создана новая персональная ссылка.'
              : 'После согласования редактирование будет закрыто.'}
          </span>
          <Button
            onClick={() => void approve()}
            disabled={approving || !questions.length}
          >
            {approving
              ? 'Готовим ссылку…'
              : questionsLocked
                ? 'Получить новую ссылку'
                : 'Согласовать и получить ссылку'}
            <ArrowUpRight data-icon="inline-end" />
          </Button>
        </div>
      )}
      {error ? (
        <p
          className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}

type EvidenceClip = {
  quote: string;
  startSeconds: number;
  endSeconds: number;
  asset: MediaAsset;
};

function vttTime(seconds: number) {
  const milliseconds = Math.max(0, Math.round(seconds * 1000));
  const hours = Math.floor(milliseconds / 3_600_000);
  const minutes = Math.floor((milliseconds % 3_600_000) / 60_000);
  const remainderSeconds = Math.floor((milliseconds % 60_000) / 1000);
  const remainderMilliseconds = milliseconds % 1000;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainderSeconds).padStart(2, '0')}.${String(remainderMilliseconds).padStart(3, '0')}`;
}

function clipCaptions(clip: EvidenceClip) {
  return `data:text/vtt;charset=utf-8,${encodeURIComponent(
    `WEBVTT\n\n${vttTime(clip.startSeconds)} --> ${vttTime(clip.endSeconds)}\n${clip.quote}\n`,
  )}`;
}

function EvidenceAnswer({
  answerText,
  evidence,
  video,
  onPlay,
}: {
  answerText: string;
  evidence: AnalysisEvidence[];
  video: MediaAsset | undefined;
  onPlay: (clip: EvidenceClip) => void;
}) {
  const candidates = [...evidence]
    .filter(
      (entry) =>
        Number.isInteger(entry.start) &&
        Number.isInteger(entry.end) &&
        entry.start >= 0 &&
        entry.end > entry.start &&
        entry.end <= answerText.length,
    )
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const ranges: AnalysisEvidence[] = [];
  let acceptedEnd = 0;
  candidates.forEach((entry) => {
    if (entry.start < acceptedEnd) return;
    ranges.push(entry);
    acceptedEnd = entry.end;
  });

  if (!ranges.length) {
    return <p className="whitespace-pre-wrap">{answerText}</p>;
  }

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  ranges.forEach((entry, index) => {
    if (entry.start > cursor) parts.push(answerText.slice(cursor, entry.start));
    const marked = entry.label === 'incorrect' || entry.label === 'check';
    const canPlay =
      marked &&
      Boolean(video?.playbackUrl) &&
      entry.clipStartSeconds !== null &&
      entry.clipEndSeconds !== null &&
      entry.clipEndSeconds > entry.clipStartSeconds;
    const className =
      entry.label === 'incorrect'
        ? 'rounded bg-rose-200 px-0.5 text-rose-900 ring-1 ring-rose-300'
        : entry.label === 'check'
          ? 'rounded bg-rose-100/55 px-0.5 text-rose-800 ring-1 ring-rose-200/70'
          : '';
    const text = answerText.slice(entry.start, entry.end);
    if (
      canPlay &&
      video &&
      entry.clipStartSeconds !== null &&
      entry.clipEndSeconds !== null
    ) {
      parts.push(
        <button
          key={`evidence-${index}`}
          type="button"
          className="inline cursor-pointer text-left align-baseline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          title="Воспроизвести этот фрагмент ответа"
          onClick={() =>
            onPlay({
              quote: entry.quote,
              startSeconds: entry.clipStartSeconds as number,
              endSeconds: entry.clipEndSeconds as number,
              asset: video,
            })
          }
        >
          <span className={className}>{text}</span>
          <Play
            className="ml-1 inline size-3 text-rose-700"
            aria-hidden="true"
          />
        </button>,
      );
    } else {
      parts.push(
        <span
          key={`evidence-${index}`}
          className={className}
          title={
            marked ? 'Временные метки для этого ответа недоступны' : undefined
          }
        >
          {text}
        </span>,
      );
    }
    cursor = entry.end;
  });
  if (cursor < answerText.length) parts.push(answerText.slice(cursor));

  return <p className="whitespace-pre-wrap">{parts}</p>;
}

function ReviewableAnalysis({
  candidate,
  analysis,
  media,
  notify,
}: {
  candidate: CandidateDetail;
  analysis: Analysis;
  media: CandidateMedia | null;
  notify: (message: string) => void;
}) {
  const [reviewAnalysis, setReviewAnalysis] = useState(analysis);
  const reviewAnalysisRef = useRef(reviewAnalysis);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [decisionMode, setDecisionMode] = useState<Exclude<
    HiringDecision,
    'pending'
  > | null>(null);
  const [internalReason, setInternalReason] = useState('');
  const [candidateFeedback, setCandidateFeedback] = useState('');
  const [pasteEvents, setPasteEvents] = useState(0);
  const [typedCharacters, setTypedCharacters] = useState(0);
  const [saving, setSaving] = useState(false);
  const [decisionSaved, setDecisionSaved] = useState(
    candidate.hiringDecision !== 'pending',
  );
  const [error, setError] = useState('');
  const heartbeatBusy = useRef(false);
  const unlockingRecommendation = useRef(false);
  const reviewPanelRef = useRef<HTMLDivElement | null>(null);
  const [reviewPanelVisible, setReviewPanelVisible] = useState(false);
  const [evidenceClip, setEvidenceClip] = useState<EvidenceClip | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    reviewAnalysisRef.current = reviewAnalysis;
  }, [reviewAnalysis]);

  useEffect(() => {
    const panel = reviewPanelRef.current;
    if (!panel) return;
    const observer = new IntersectionObserver(
      ([entry]) =>
        setReviewPanelVisible(
          entry.isIntersecting && entry.intersectionRatio >= 0.1,
        ),
      { threshold: [0, 0.1, 1] },
    );
    observer.observe(panel);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!activeItemId) return;
    const item = reviewAnalysisRef.current.items.find(
      (entry) => entry.id === activeItemId,
    );
    if (!item || item.reviewComplete || !item.requiredReview) return;
    let closed = false;

    let timer = 0;
    const send = async (event: 'open' | 'heartbeat' | 'close') => {
      if (heartbeatBusy.current && event === 'heartbeat') return;
      heartbeatBusy.current = true;
      try {
        const progress = await api.trackAnalysisReview(candidate.id, {
          itemId: activeItemId,
          event,
          visible: reviewPanelVisible && document.visibilityState === 'visible',
          focused: document.hasFocus(),
        });
        if (!closed) {
          if (progress.allItemsComplete && !unlockingRecommendation.current) {
            unlockingRecommendation.current = true;
            try {
              const unlocked = await api.getCandidateAnalysis(candidate.id);
              if (!closed) setReviewAnalysis(unlocked);
            } finally {
              unlockingRecommendation.current = false;
            }
          }
          setReviewAnalysis((current) => ({
            ...current,
            reviewComplete: progress.allItemsComplete,
            items: current.items.map((entry) =>
              entry.id === progress.itemId
                ? {
                    ...entry,
                    reviewedSeconds: progress.reviewedSeconds,
                    reviewComplete: progress.reviewComplete,
                  }
                : entry,
            ),
          }));
          if (progress.reviewComplete && timer) window.clearInterval(timer);
        }
      } catch (caught) {
        if (!closed) setError(errorText(caught));
      } finally {
        heartbeatBusy.current = false;
      }
    };

    void send('open');
    timer = window.setInterval(() => void send('heartbeat'), 1000);
    const syncActivity = () => {
      const active =
        reviewPanelVisible &&
        document.visibilityState === 'visible' &&
        document.hasFocus();
      void send(active ? 'open' : 'close');
    };
    document.addEventListener('visibilitychange', syncActivity);
    window.addEventListener('focus', syncActivity);
    window.addEventListener('blur', syncActivity);
    return () => {
      closed = true;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', syncActivity);
      window.removeEventListener('focus', syncActivity);
      window.removeEventListener('blur', syncActivity);
      void api
        .trackAnalysisReview(candidate.id, {
          itemId: activeItemId,
          event: 'close',
          visible: document.visibilityState === 'visible',
          focused: document.hasFocus(),
        })
        .catch(() => undefined);
    };
  }, [activeItemId, candidate.id, reviewPanelVisible]);

  const requiredItems = reviewAnalysis.items.filter(
    (item) => item.requiredReview,
  );
  const completeCount = requiredItems.filter(
    (item) => item.reviewComplete,
  ).length;
  const activeItem = reviewAnalysis.items.find(
    (item) => item.id === activeItemId,
  );
  const videoByQuestionId = useMemo(
    () =>
      new Map(
        (media?.assets || [])
          .filter((asset) => asset.kind === 'video' && asset.questionId)
          .map((asset) => [asset.questionId as string, asset]),
      ),
    [media],
  );

  const playEvidenceClip = () => {
    if (!evidenceClip || !videoRef.current) return;
    videoRef.current.currentTime = evidenceClip.startSeconds;
    void videoRef.current.play().catch(() => undefined);
  };

  const preventCopiedReason = (
    event:
      | React.ClipboardEvent<HTMLTextAreaElement>
      | React.DragEvent<HTMLTextAreaElement>,
  ) => {
    event.preventDefault();
    setPasteEvents((count) => count + 1);
    notify('Внутреннюю причину нужно набрать вручную');
  };

  const submitDecision = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!decisionMode || saving || !reviewAnalysis.reviewComplete) return;
    const input: DecisionInput = {
      status: decisionMode,
      internalReason,
      candidateFeedback,
      internalReasonPasteEvents: pasteEvents,
      internalReasonTypedCharacters: typedCharacters,
    };
    setSaving(true);
    setError('');
    try {
      await api.saveCandidateDecision(candidate.id, input);
      setDecisionSaved(true);
      setDecisionMode(null);
      notify(
        decisionMode === 'rejected'
          ? 'Отказ и фидбэк сохранены'
          : 'Кандидат приглашён дальше',
      );
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <section className="surface-card p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">Материалы интервью</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Скачайте исходники или откройте конкретный ответ.
            </p>
          </div>
          <Badge variant="outline">{media?.assets.length || 0} файлов</Badge>
        </div>
        {media?.assets.length ? (
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            {media.assets.map((asset) => (
              <a
                key={asset.id}
                className="flex min-h-12 items-center gap-3 rounded-xl border px-3 text-sm font-medium hover:bg-muted"
                href={asset.downloadUrl}
                download={asset.filename}
              >
                <Download className="size-4 text-primary" aria-hidden="true" />
                <span className="min-w-0">
                  <span className="block truncate">{asset.filename}</span>
                  <span className="text-xs font-normal text-muted-foreground">
                    {asset.kind}
                  </span>
                </span>
              </a>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">
            Файлы ещё готовятся.
          </p>
        )}
      </section>

      <section className="surface-card p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">Проверка анализа</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Откройте каждый обязательный пункт минимум на 10 секунд.
            </p>
          </div>
          <Badge
            className={
              reviewAnalysis.reviewComplete
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-amber-50 text-amber-800'
            }
          >
            {completeCount} из {requiredItems.length}
          </Badge>
        </div>
        <Progress
          className="mt-4"
          value={
            requiredItems.length
              ? (completeCount / requiredItems.length) * 100
              : 100
          }
        />
        <div className="mt-5 grid gap-2 lg:grid-cols-[320px_minmax(0,1fr)]">
          <div className="space-y-2">
            {reviewAnalysis.items.map((item) => (
              <button
                key={item.id}
                className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left ${activeItemId === item.id ? 'border-primary bg-accent/50' : 'bg-background'}`}
                onClick={() => {
                  setActiveItemId(item.id);
                  window.requestAnimationFrame(() =>
                    reviewPanelRef.current?.scrollIntoView({
                      behavior: 'smooth',
                      block: 'nearest',
                    }),
                  );
                }}
              >
                <span
                  className={`grid size-8 shrink-0 place-items-center rounded-lg ${item.reviewComplete ? 'bg-emerald-50 text-emerald-700' : 'bg-muted text-muted-foreground'}`}
                >
                  {item.reviewComplete ? (
                    <Check className="size-4" />
                  ) : (
                    item.orderIndex + 1
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {item.title}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {item.requiredReview
                      ? `${Math.min(10, Math.floor(item.reviewedSeconds))}/10 сек`
                      : 'Дополнительно'}
                  </span>
                </span>
                <ChevronRight className="size-4 text-muted-foreground" />
              </button>
            ))}
          </div>
          <div
            ref={reviewPanelRef}
            className="min-h-72 rounded-2xl border bg-muted/20 p-5"
            aria-live="polite"
          >
            {activeItem ? (
              <article>
                <div className="flex items-center gap-2">
                  <Eye className="size-4 text-primary" />
                  <Badge variant="outline">{activeItem.kind}</Badge>
                </div>
                <h3 className="mt-4 text-lg font-semibold">
                  {activeItem.title}
                </h3>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-foreground/85">
                  {activeItem.body}
                </p>
                {activeItem.answerText ? (
                  <div className="mt-5 rounded-xl border-l-4 border-l-primary bg-background p-4 text-sm leading-7">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Ответ кандидата
                    </p>
                    <EvidenceAnswer
                      answerText={activeItem.answerText}
                      evidence={activeItem.evidence}
                      video={
                        activeItem.questionId
                          ? videoByQuestionId.get(activeItem.questionId)
                          : undefined
                      }
                      onPlay={setEvidenceClip}
                    />
                    {activeItem.evidence.some((entry) => entry.rationale) ? (
                      <div className="mt-4 space-y-2 border-t pt-3">
                        {activeItem.evidence
                          .filter((entry) => entry.rationale)
                          .map((entry, index) => (
                            <p
                              key={`${entry.start}-${entry.end}-${index}`}
                              className="text-xs text-muted-foreground"
                            >
                              <span className="font-semibold text-foreground">
                                {entry.label === 'incorrect'
                                  ? 'Ошибка'
                                  : entry.label === 'check'
                                    ? 'Требуется проверка'
                                    : 'Подтверждено'}
                                :{' '}
                              </span>
                              {entry.rationale}
                            </p>
                          ))}
                      </div>
                    ) : null}
                    {activeItem.evidence.some(
                      (entry) =>
                        (entry.label === 'incorrect' ||
                          entry.label === 'check') &&
                        (!activeItem.questionId ||
                          !videoByQuestionId.get(activeItem.questionId)
                            ?.playbackUrl ||
                          entry.clipStartSeconds === null ||
                          entry.clipEndSeconds === null),
                    ) ? (
                      <p className="mt-3 text-xs text-muted-foreground">
                        Временные метки для части этого ответа недоступны;
                        текстовая подсветка сохранена без возможности открыть
                        видеофрагмент.
                      </p>
                    ) : null}
                  </div>
                ) : activeItem.evidence.length ? (
                  <div className="mt-5 space-y-2">
                    {activeItem.evidence.map((entry, index) => (
                      <blockquote
                        key={index}
                        className="rounded-xl border-l-4 border-l-primary bg-background p-3 text-sm leading-relaxed"
                      >
                        {entry.quote}
                      </blockquote>
                    ))}
                  </div>
                ) : null}
                {activeItem.requiredReview && !activeItem.reviewComplete ? (
                  <p className="mt-5 text-xs text-muted-foreground">
                    Оставьте пункт открытым и держите вкладку активной ещё{' '}
                    {Math.max(0, Math.ceil(10 - activeItem.reviewedSeconds))}{' '}
                    сек.
                  </p>
                ) : null}
              </article>
            ) : (
              <div className="grid h-full place-items-center text-center text-sm text-muted-foreground">
                <p>Выберите первый пункт слева.</p>
              </div>
            )}
          </div>
        </div>
      </section>

      {reviewAnalysis.reviewComplete &&
      !reviewAnalysis.recommendationLocked &&
      reviewAnalysis.recommendation !== null &&
      reviewAnalysis.score !== null &&
      reviewAnalysis.confidence !== null &&
      reviewAnalysis.summary !== null ? (
        <section
          className={`recommendation-card ${reviewAnalysis.recommendation === 'fit' ? 'recommendation-fit' : reviewAnalysis.recommendation === 'not_fit' ? 'recommendation-risk' : 'recommendation-review'}`}
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-xs font-semibold">
              <Sparkles className="size-4" />
              Рекомендация AI — открыта после проверки
            </div>
            <h2 className="mt-3 text-2xl font-semibold">
              {reviewAnalysis.recommendation === 'fit'
                ? 'Позвать дальше'
                : reviewAnalysis.recommendation === 'not_fit'
                  ? 'Есть существенные разрывы'
                  : 'Нужна ручная проверка'}
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-relaxed">
              {reviewAnalysis.summary}
            </p>
            <p className="mt-3 text-xs opacity-70">
              Уверенность {Math.round(reviewAnalysis.confidence * 100)}%.
              Итоговое решение принимает человек.
            </p>
          </div>
          <div className="score-orbit">
            <span className="text-3xl font-semibold">
              {reviewAnalysis.score.toFixed(1)}
            </span>
            <span className="text-xs">из 10</span>
          </div>
        </section>
      ) : (
        <section className="surface-card flex items-center gap-4 p-5">
          <LockKeyhole className="size-5 text-muted-foreground" />
          <div>
            <h2 className="text-sm font-semibold">Итог AI пока скрыт</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Сначала изучите все обязательные пункты анализа.
            </p>
          </div>
        </section>
      )}

      {reviewAnalysis.reviewComplete &&
      !reviewAnalysis.recommendationLocked &&
      !decisionSaved ? (
        <section className="surface-card p-5 sm:p-6">
          <h2 className="font-semibold">Решение нанимающей команды</h2>
          {!decisionMode ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="destructive"
                onClick={() => setDecisionMode('rejected')}
              >
                Отказать
              </Button>
              <Button onClick={() => setDecisionMode('next_stage')}>
                Позвать дальше
              </Button>
            </div>
          ) : (
            <form className="mt-5 space-y-4" onSubmit={submitDecision}>
              <label className="field-label" htmlFor="internal-reason">
                Внутренняя причина {decisionMode === 'rejected' ? '*' : ''}
                <Textarea
                  id="internal-reason"
                  className="mt-2 min-h-28"
                  value={internalReason}
                  onChange={(e) => {
                    const next = e.target.value;
                    setTypedCharacters(
                      (count) =>
                        count +
                        Math.max(0, next.length - internalReason.length),
                    );
                    setInternalReason(next);
                  }}
                  onPaste={preventCopiedReason}
                  onDrop={preventCopiedReason}
                  placeholder="Введите своими словами — вставка и перетаскивание отключены"
                  required={decisionMode === 'rejected'}
                />
              </label>
              {pasteEvents ? (
                <div className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900">
                  Попытка вставки зафиксирована. Чтобы сохранить честную
                  внутреннюю причину, очистите поле и начните заново.
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="ml-2"
                    onClick={() => {
                      setInternalReason('');
                      setTypedCharacters(0);
                      setPasteEvents(0);
                    }}
                  >
                    Очистить
                  </Button>
                </div>
              ) : null}
              <label className="field-label" htmlFor="candidate-feedback">
                Фидбэк кандидату {decisionMode === 'rejected' ? '*' : ''}
                <Textarea
                  id="candidate-feedback"
                  className="mt-2 min-h-32"
                  value={candidateFeedback}
                  onChange={(e) => setCandidateFeedback(e.target.value)}
                  placeholder="Что подтверждено и чего не хватило для этой вакансии"
                  required={decisionMode === 'rejected'}
                />
              </label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setDecisionMode(null)}
                >
                  Отмена
                </Button>
                <Button
                  type="submit"
                  variant={
                    decisionMode === 'rejected' ? 'destructive' : 'default'
                  }
                  disabled={
                    saving ||
                    (decisionMode === 'rejected' &&
                      (internalReason.trim().length < 12 ||
                        candidateFeedback.trim().length < 30))
                  }
                >
                  {saving ? 'Сохраняем…' : 'Подтвердить решение'}
                </Button>
              </div>
            </form>
          )}
        </section>
      ) : null}
      {decisionSaved ? (
        <section className="surface-card flex items-center gap-3 p-5">
          <CheckCircle2 className="size-5 text-emerald-600" />
          <p className="text-sm font-medium">
            Решение сохранено и доступно кандидату.
          </p>
        </section>
      ) : null}
      {error ? (
        <p
          className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      <Dialog
        open={evidenceClip !== null}
        onOpenChange={(open) => {
          if (!open) {
            videoRef.current?.pause();
            setEvidenceClip(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Фрагмент ответа кандидата</DialogTitle>
            <DialogDescription>
              {evidenceClip?.quote || 'Выделенный фрагмент ответа'}
            </DialogDescription>
          </DialogHeader>
          {evidenceClip?.asset.playbackUrl ? (
            <video
              ref={videoRef}
              className="max-h-[65vh] w-full rounded-xl bg-black"
              controls
              preload="metadata"
              src={evidenceClip.asset.playbackUrl}
              onLoadedMetadata={playEvidenceClip}
              onTimeUpdate={(event) => {
                if (
                  evidenceClip &&
                  event.currentTarget.currentTime >= evidenceClip.endSeconds
                ) {
                  event.currentTarget.pause();
                  event.currentTarget.currentTime = evidenceClip.endSeconds;
                }
              }}
              onPlay={(event) => {
                if (
                  evidenceClip &&
                  (event.currentTarget.currentTime <
                    evidenceClip.startSeconds ||
                    event.currentTarget.currentTime >= evidenceClip.endSeconds)
                ) {
                  event.currentTarget.currentTime = evidenceClip.startSeconds;
                }
              }}
              onError={() => notify('Не удалось загрузить видеофрагмент')}
            >
              <track
                default
                kind="captions"
                src={clipCaptions(evidenceClip)}
                srcLang="ru"
                label="Расшифровка ответа"
              />
            </video>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={playEvidenceClip}>
              <RotateCcw data-icon="inline-start" />
              Повторить фрагмент
            </Button>
            <Button type="button" onClick={() => setEvidenceClip(null)}>
              Закрыть
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function CandidateWorkspace({
  candidateId,
  onBack,
  notify,
}: {
  candidateId: string;
  onBack: () => void;
  notify: (message: string) => void;
}) {
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [media, setMedia] = useState<CandidateMedia | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const detail = await api.getCandidate(candidateId, controller.signal);
        setCandidate(detail);
        setAnalysis(null);
        setMedia(null);
        if (
          detail.processingStatus === 'ready' ||
          detail.processingStatus === 'completed'
        ) {
          const [analysisResult, mediaResult] = await Promise.all([
            api.getCandidateAnalysis(candidateId, controller.signal),
            api
              .getCandidateMedia(candidateId, controller.signal)
              .catch(() => null),
          ]);
          setAnalysis(analysisResult);
          setMedia(mediaResult);
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
  }, [candidateId, reloadKey]);

  if (loading) return <Busy label="Открываем кандидата…" />;
  if (error || !candidate)
    return (
      <ErrorPanel
        message={error || 'Кандидат не найден.'}
        onRetry={() => setReloadKey((key) => key + 1)}
      />
    );

  const status = statusCopy(
    candidate.processingStatus,
    candidate.hiringDecision,
  );
  return (
    <div className="mx-auto max-w-[1120px] pb-16">
      <BackButton onClick={onBack} label="К кандидатам" />
      <div className="mb-6 flex flex-wrap items-center gap-4">
        <span className="grid size-14 place-items-center rounded-full bg-accent font-semibold text-accent-foreground">
          {initials(candidate.name)}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-semibold">{candidate.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {candidate.role} · {candidate.resumeFilename}
          </p>
        </div>
        <Badge className={status.className}>{status.label}</Badge>
      </div>
      {(candidate.processingStatus === 'ready' ||
        candidate.processingStatus === 'completed') &&
      analysis ? (
        <ReviewableAnalysis
          candidate={candidate}
          analysis={analysis}
          media={media}
          notify={notify}
        />
      ) : candidate.processingStatus === 'not_started' ||
        candidate.processingStatus === 'questions_draft' ||
        candidate.processingStatus === 'invited' ? (
        <QuestionApproval candidate={candidate} notify={notify} />
      ) : (
        <section className="surface-card p-8 text-center">
          <LoaderCircle className="mx-auto size-7 animate-spin text-primary" />
          <h2 className="mt-4 font-semibold">Интервью обрабатывается</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Транскрипт, медиа и анализ появятся здесь после завершения pipeline.
          </p>
          <Button
            variant="outline"
            className="mt-5"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            Обновить
          </Button>
        </section>
      )}
    </div>
  );
}
