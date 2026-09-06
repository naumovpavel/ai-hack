'use client';

import { useEffect, useState } from 'react';
import {
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  Clipboard,
  LoaderCircle,
  Save,
} from 'lucide-react';

import { HumanFirstReview } from './human-first-review';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { api, ApiError } from '@/lib/api';
import { copyText } from '@/lib/clipboard';
import type {
  Analysis,
  Approval,
  CandidateDetail,
  CandidateMedia,
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
      if (!(await copyText(approval.inviteUrl)))
        throw new Error('Clipboard unavailable');
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
              <Input
                aria-label="Ссылка на интервью"
                className="mt-2"
                value={approval.inviteUrl}
                readOnly
                onFocus={(event) => event.currentTarget.select()}
              />
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
        <HumanFirstReview
          key={analysis.id}
          candidate={candidate}
          analysis={analysis}
          media={media}
          notify={notify}
          onDecision={(decision) =>
            setCandidate((current) =>
              current
                ? {
                    ...current,
                    hiringDecision: decision.status,
                  }
                : current,
            )
          }
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
