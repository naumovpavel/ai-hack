'use client';

import { useRef, useState, type SyntheticEvent } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleHelp,
  Download,
  LoaderCircle,
  LockKeyhole,
  Sparkles,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { api } from '@/lib/api';
import { AnswerEvidence } from './answer-evidence';
import type {
  Analysis,
  CandidateDetail,
  CandidateMedia,
  Decision,
  HiringDecision,
  QuestionRating,
} from '@/lib/types';

type Status = Exclude<HiringDecision, 'pending'>;
const statusLabels: Record<Status, string> = {
  next_stage: 'Позвать дальше',
  rejected: 'Отказать',
};
const ratings = [
  { value: 'positive', label: 'Достаточный ответ', icon: Check },
  { value: 'negative', label: 'Недостаточный ответ', icon: X },
  { value: 'uncertain', label: 'Не могу оценить', icon: CircleHelp },
] as const;
const ratingLabel = (value: QuestionRating | null) =>
  ratings.find((item) => item.value === value)?.label || 'Без оценки';

function DecisionChoices({
  value,
  onChange,
  disabled,
}: {
  value: Status | null;
  onChange: (value: Status) => void;
  disabled: boolean;
}) {
  return (
    <fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-2">
      <legend className="mb-3 text-sm font-medium">
        Решение о следующем этапе
      </legend>
      {(['next_stage', 'rejected'] as const).map((status) => (
        <label
          key={status}
          className={`flex min-h-14 cursor-pointer items-center gap-3 rounded-xl border p-4 text-sm transition-colors focus-within:ring-2 focus-within:ring-ring ${value === status ? 'border-primary bg-primary/5' : 'hover:bg-muted'}`}
        >
          <input
            type="radio"
            name="independent-decision"
            value={status}
            checked={value === status}
            onChange={() => onChange(status)}
            className="size-4 accent-primary"
          />
          {statusLabels[status]}
        </label>
      ))}
    </fieldset>
  );
}

export function HumanFirstReview({
  candidate,
  analysis,
  media,
  notify,
  onDecision,
}: {
  candidate: CandidateDetail;
  analysis: Analysis;
  media: CandidateMedia | null;
  notify: (message: string) => void;
  onDecision: (decision: Decision) => void;
}) {
  const [review, setReview] = useState(analysis);
  const [activeIndex, setActiveIndex] = useState(
    Math.max(
      0,
      analysis.questions.findIndex((q) => !q.rating),
    ),
  );
  const [summaryOpen, setSummaryOpen] = useState(analysis.reviewComplete);
  const [status, setStatus] = useState<Status | null>(
    analysis.initialDecision?.status || null,
  );
  const [feedback, setFeedback] = useState(
    analysis.initialDecision?.candidateFeedback || '',
  );
  const [finalStatus, setFinalStatus] = useState<Status | null>(
    analysis.finalDecision?.status || analysis.initialDecision?.status || null,
  );
  const [finalFeedback, setFinalFeedback] = useState(
    analysis.finalDecision?.candidateFeedback ||
      analysis.initialDecision?.candidateFeedback ||
      '',
  );
  const [changeReason, setChangeReason] = useState(analysis.changeReason);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState('');
  const [saveNotice, setSaveNotice] = useState('');
  const headingRef = useRef<HTMLHeadingElement>(null);
  const step =
    review.finalDecision || !review.recommendationLocked
      ? 3
      : summaryOpen
        ? 2
        : 1;
  const question = review.questions[activeIndex];
  const completeCount = review.questions.filter(
    (q) => q.rating !== null,
  ).length;
  const initial = review.initialDecision;
  const aiStatus: Status | null =
    review.recommendation === 'fit'
      ? 'next_stage'
      : review.recommendation === 'not_fit'
        ? 'rejected'
        : null;
  const adoptingOpposite =
    !!initial &&
    !!aiStatus &&
    finalStatus === aiStatus &&
    finalStatus !== initial.status;
  const questionVideo = media?.assets.find(
    (asset) =>
      asset.questionId === question?.questionId &&
      asset.kind === 'video' &&
      asset.playbackUrl,
  );
  const questionAudio = media?.assets.find(
    (asset) =>
      asset.questionId === question?.questionId && asset.kind === 'audio',
  );

  const moveFocus = () =>
    window.requestAnimationFrame(() => {
      headingRef.current?.focus({ preventScroll: true });
      headingRef.current?.scrollIntoView({
        block: 'nearest',
        behavior: 'instant',
      });
    });
  const openQuestion = (index: number) => {
    setActiveIndex(index);
    setSummaryOpen(false);
    setError('');
    moveFocus();
  };
  const run = async (operation: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError('');
    try {
      await operation();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Не удалось сохранить. Попробуйте ещё раз.',
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const rate = (rating: QuestionRating) => {
    if (!question) return;
    setSaveNotice('');
    void run(async () => {
      setReview(
        await api.rateInterviewQuestion(
          candidate.id,
          question.questionId,
          rating,
        ),
      );
      setSaveNotice('Оценка сохранена');
    });
  };
  const reveal = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!status || !feedback.trim() || !review.reviewComplete) return;
    void run(async () => {
      const updated = await api.revealAiRecommendation(candidate.id, {
        status,
        candidateFeedback: feedback.trim(),
      });
      setReview(updated);
      setFinalStatus(updated.initialDecision!.status);
      setFinalFeedback(updated.initialDecision!.candidateFeedback);
      moveFocus();
    });
  };
  const publish = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !finalStatus ||
      !finalFeedback.trim() ||
      (adoptingOpposite && !changeReason.trim())
    )
      return;
    void run(async () => {
      const decision = await api.saveCandidateDecision(candidate.id, {
        status: finalStatus,
        candidateFeedback: finalFeedback.trim(),
        internalReason: initial?.internalReason || '',
        changeReason: adoptingOpposite ? changeReason.trim() : '',
      });
      setReview((current) => ({
        ...current,
        finalDecision: decision,
        changeReason: adoptingOpposite ? changeReason.trim() : '',
      }));
      onDecision(decision);
      notify('Решение и фидбэк доступны кандидату');
      moveFocus();
    });
  };

  return (
    <div className="space-y-5">
      <ol
        aria-label="Этапы оценки"
        className="grid grid-cols-3 gap-2 rounded-2xl border bg-card p-3 sm:gap-4 sm:p-4"
      >
        {['Ответы кандидата', 'Ваше решение', 'Сверка с ИИ'].map(
          (label, index) => (
            <li
              key={label}
              aria-current={step === index + 1 ? 'step' : undefined}
              className={`flex min-w-0 items-center gap-2 text-sm ${step === index + 1 ? 'font-semibold text-foreground' : 'text-muted-foreground'}`}
            >
              <span
                className={`grid size-7 shrink-0 place-items-center rounded-full text-sm ${step > index + 1 || review.finalDecision ? 'bg-primary/10 text-primary' : step === index + 1 ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}
              >
                {step > index + 1 || review.finalDecision ? (
                  <Check className="size-4" aria-hidden="true" />
                ) : (
                  index + 1
                )}
              </span>
              <span className="break-words">{label}</span>
            </li>
          ),
        )}
      </ol>

      {error ? (
        <div
          role="alert"
          className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
        >
          {error}
          <span className="mt-1 block">
            Повторите действие, когда соединение восстановится.
          </span>
        </div>
      ) : null}

      {step === 1 ? (
        <section className="surface-card">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b p-5 sm:p-6">
            <div>
              <h2
                ref={headingRef}
                tabIndex={-1}
                className="text-lg font-semibold outline-none"
              >
                Оцените ответы
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                По каждому вопросу — достаточно ли ответа для этой вакансии.
              </p>
            </div>
            <span className="rounded-full bg-muted px-3 py-1 text-sm tabular-nums">
              {completeCount} из {review.questions.length} оценено
            </span>
          </div>
          {!question ? (
            <p className="p-6 text-muted-foreground">
              В интервью пока нет вопросов для оценки.
            </p>
          ) : (
            <div className="grid lg:grid-cols-[250px_minmax(0,1fr)]">
              <nav
                aria-label="Вопросы интервью"
                className="max-h-64 overflow-y-auto border-b bg-muted/30 p-3 lg:max-h-[650px] lg:border-r lg:border-b-0"
              >
                {review.questions.map((item, index) => (
                  <button
                    type="button"
                    key={item.questionId}
                    disabled={busy}
                    onClick={() => openQuestion(index)}
                    aria-current={index === activeIndex ? 'true' : undefined}
                    className={`mb-1 flex min-h-14 w-full gap-3 rounded-xl p-3 text-left focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60 ${index === activeIndex ? 'bg-background shadow-sm ring-1 ring-border' : 'hover:bg-muted'}`}
                  >
                    <span
                      className={`grid size-6 shrink-0 place-items-center rounded-full text-sm ${item.rating ? 'bg-primary/10 text-primary' : 'bg-background text-muted-foreground'}`}
                    >
                      {item.rating ? (
                        <Check className="size-3.5" aria-hidden="true" />
                      ) : (
                        index + 1
                      )}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">
                        {item.text}
                        {item.kind === 'follow_up' ? ' · уточнение' : ''}
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {ratingLabel(item.rating)}
                      </span>
                    </span>
                  </button>
                ))}
              </nav>
              <div className="min-w-0 p-5 sm:p-6">
                <p className="text-sm text-muted-foreground">
                  Вопрос {activeIndex + 1} из {review.questions.length}
                </p>
                <h3 className="mt-2 text-xl leading-relaxed font-semibold">
                  {question.text}
                </h3>
                <div className="mt-5">
                  <AnswerEvidence
                    key={question.questionId}
                    answer={question}
                    items={review.items.filter(
                      (item) => item.questionId === question.questionId,
                    )}
                    media={media}
                    notify={notify}
                  />
                </div>
                {questionVideo || questionAudio ? (
                  <details
                    key={question.questionId}
                    className="mt-4 rounded-xl border p-4"
                  >
                    <summary className="cursor-pointer text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">
                      Посмотреть запись ответа
                    </summary>
                    {questionVideo ? (
                      <video
                        className="mt-4 max-h-80 w-full rounded-lg bg-black"
                        controls
                        preload="none"
                        src={questionVideo.playbackUrl!}
                        aria-label={`Запись ответа на вопрос ${activeIndex + 1}`}
                      >
                        <track
                          kind="captions"
                          srcLang="ru"
                          label="Текст ответа"
                          src={`data:text/vtt;charset=utf-8,${encodeURIComponent(`WEBVTT\n\n00:00:00.000 --> 23:59:59.000\n${question.answerText || ''}\n`)}`}
                        />
                      </video>
                    ) : (
                      <audio
                        className="mt-4 w-full"
                        controls
                        preload="none"
                        src={questionAudio!.downloadUrl}
                        aria-label="Аудиозапись ответа"
                      >
                        <track
                          kind="captions"
                          srcLang="ru"
                          label="Текст ответа"
                          src={`data:text/vtt;charset=utf-8,${encodeURIComponent(`WEBVTT\n\n00:00:00.000 --> 23:59:59.000\n${question.answerText || ''}\n`)}`}
                        />
                      </audio>
                    )}
                  </details>
                ) : null}
                <fieldset disabled={busy} className="mt-6">
                  <legend className="mb-3 text-sm font-semibold">
                    Ваша оценка ответа
                  </legend>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {ratings.map(({ value, label, icon: Icon }) => (
                      <label
                        key={value}
                        className={`flex min-h-14 cursor-pointer items-center gap-2 rounded-xl border p-3 text-sm focus-within:ring-2 focus-within:ring-ring ${question.rating === value ? 'border-primary bg-primary/5' : 'hover:bg-muted'}`}
                      >
                        <input
                          type="radio"
                          name={`rating-${question.questionId}`}
                          checked={question.rating === value}
                          onChange={() => rate(value)}
                          className="size-4 shrink-0 accent-primary"
                        />
                        <Icon
                          className="hidden size-4 shrink-0 xl:block"
                          aria-hidden="true"
                        />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div
                  aria-live="polite"
                  className="mt-3 flex min-h-5 items-center gap-2 text-sm text-muted-foreground"
                >
                  {busy ? (
                    <>
                      <LoaderCircle
                        className="size-4 animate-spin"
                        aria-hidden="true"
                      />
                      Сохраняем оценку…
                    </>
                  ) : question.rating ? (
                    <>
                      <Check className="size-4" aria-hidden="true" />
                      {saveNotice || 'Оценка сохранена'}
                    </>
                  ) : (
                    'Выберите оценку, чтобы продолжить.'
                  )}
                </div>
                <div className="mt-6 flex flex-wrap justify-between gap-3 border-t pt-5">
                  <Button
                    type="button"
                    variant="ghost"
                    className="min-h-11"
                    disabled={busy || activeIndex === 0}
                    onClick={() => openQuestion(activeIndex - 1)}
                  >
                    <ArrowLeft aria-hidden="true" />
                    Назад
                  </Button>
                  <Button
                    type="button"
                    className="min-h-11"
                    disabled={busy || !question.rating}
                    onClick={() => {
                      if (activeIndex < review.questions.length - 1)
                        openQuestion(activeIndex + 1);
                      else if (!review.reviewComplete)
                        openQuestion(
                          review.questions.findIndex((q) => !q.rating),
                        );
                      else {
                        setSummaryOpen(true);
                        moveFocus();
                      }
                    }}
                  >
                    {activeIndex < review.questions.length - 1
                      ? 'Следующий вопрос'
                      : review.reviewComplete
                        ? 'К итоговому решению'
                        : 'К вопросу без оценки'}
                    <ArrowRight aria-hidden="true" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </section>
      ) : null}

      {step === 2 ? (
        <section className="surface-card p-5 sm:p-7">
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="text-xl font-semibold outline-none"
          >
            Ваше решение по кандидату
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Все ответы оценены. Зафиксируйте своё решение и фидбэк перед
            сравнением с ИИ.
          </p>
          <div className="my-6 divide-y rounded-xl border px-4">
            {review.questions.map((item, index) => (
              <div
                key={item.questionId}
                className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"
              >
                <span>
                  {index + 1}. {item.text} · {ratingLabel(item.rating)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  className="min-h-11"
                  disabled={busy}
                  aria-label={`Изменить оценку вопроса ${index + 1}`}
                  onClick={() => openQuestion(index)}
                >
                  Изменить
                </Button>
              </div>
            ))}
          </div>
          <form onSubmit={reveal} className="space-y-6">
            <DecisionChoices
              value={status}
              onChange={setStatus}
              disabled={busy}
            />
            <div>
              <label
                htmlFor="initial-feedback"
                className="text-sm font-semibold"
              >
                Фидбэк кандидату{' '}
                <span className="font-normal text-muted-foreground">
                  · обязательно
                </span>
              </label>
              <Textarea
                id="initial-feedback"
                className="mt-2 min-h-36 text-base"
                placeholder="Что удалось подтвердить в ответах и почему вы приняли это решение"
                value={feedback}
                onChange={(event) => setFeedback(event.target.value)}
                required
                maxLength={10000}
                disabled={busy}
              />
              <p className="mt-2 text-sm text-muted-foreground">
                Кандидат увидит фидбэк после окончательного подтверждения.
              </p>
            </div>
            <div className="flex items-start gap-3 rounded-xl bg-muted/50 p-4 text-sm text-muted-foreground">
              <LockKeyhole
                className="mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
              <p>
                Первоначальная оценка сохранится. На следующем шаге можно
                оставить решение или изменить его после сравнения с ИИ.
              </p>
            </div>
            <div className="flex flex-wrap justify-between gap-3">
              <Button
                type="button"
                variant="ghost"
                className="min-h-11"
                disabled={busy}
                onClick={() => openQuestion(activeIndex)}
              >
                <ArrowLeft aria-hidden="true" />К ответам
              </Button>
              <Button
                type="submit"
                className="h-auto min-h-11 whitespace-normal px-4 py-3"
                disabled={busy || !status || !feedback.trim()}
              >
                {busy
                  ? 'Сохраняем решение…'
                  : 'Сохранить и посмотреть рекомендацию ИИ'}
                <ArrowRight aria-hidden="true" />
              </Button>
            </div>
          </form>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="space-y-5">
          <div>
            <h2
              ref={headingRef}
              tabIndex={-1}
              className="text-xl font-semibold outline-none"
            >
              {review.finalDecision
                ? 'Решение подтверждено'
                : 'Сравните решения'}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {review.finalDecision
                ? 'Кандидату доступны окончательное решение и фидбэк.'
                : 'Первоначальное решение сохранено. Последнее слово за вами.'}
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="surface-card p-5 sm:p-6">
              <div className="flex items-center gap-2 text-sm font-medium">
                <CheckCircle2
                  className="size-4 text-primary"
                  aria-hidden="true"
                />
                Ваше решение до рекомендации ИИ
              </div>
              <p className="mt-4 text-2xl font-semibold">
                {initial ? statusLabels[initial.status] : 'Ранее подтверждено'}
              </p>
              <p className="mt-3 whitespace-pre-wrap break-words text-base leading-7">
                {initial?.candidateFeedback ||
                  review.finalDecision?.candidateFeedback}
              </p>
            </div>
            <div className="surface-card p-5 sm:p-6">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Sparkles className="size-4 text-primary" aria-hidden="true" />
                Рекомендация ИИ
              </div>
              <p className="mt-4 text-2xl font-semibold">
                {aiStatus
                  ? statusLabels[aiStatus]
                  : 'Нужна дополнительная проверка'}
              </p>
              <p className="mt-3 whitespace-pre-wrap break-words text-base leading-7">
                {review.summary}
              </p>
              {review.score !== null ? (
                <p className="mt-4 text-sm text-muted-foreground">
                  Оценка ИИ: {review.score.toFixed(1)} из 10
                </p>
              ) : null}
            </div>
          </div>
          {!review.finalDecision && initial ? (
            <form
              onSubmit={publish}
              className="surface-card space-y-5 p-5 sm:p-6"
            >
              <fieldset disabled={busy}>
                <legend className="mb-3 font-semibold">
                  Какое решение подтвердить?
                </legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label
                    aria-label="Оставить своё решение"
                    className={`flex min-h-16 cursor-pointer items-center gap-3 rounded-xl border p-4 text-sm focus-within:ring-2 focus-within:ring-ring ${finalStatus === initial.status ? 'border-primary bg-primary/5' : 'hover:bg-muted'}`}
                  >
                    <input
                      type="radio"
                      name="final-decision"
                      checked={finalStatus === initial.status}
                      onChange={() => {
                        setFinalStatus(initial.status);
                      }}
                      className="size-4 accent-primary"
                    />
                    <span>
                      <span className="block font-medium">
                        Оставить своё решение
                      </span>
                      <span className="mt-1 block text-muted-foreground">
                        {statusLabels[initial.status]}
                      </span>
                    </span>
                  </label>
                  {aiStatus && aiStatus !== initial.status ? (
                    <label
                      aria-label="Принять рекомендацию ИИ"
                      className={`flex min-h-16 cursor-pointer items-center gap-3 rounded-xl border p-4 text-sm focus-within:ring-2 focus-within:ring-ring ${finalStatus === aiStatus ? 'border-primary bg-primary/5' : 'hover:bg-muted'}`}
                    >
                      <input
                        type="radio"
                        name="final-decision"
                        checked={finalStatus === aiStatus}
                        onChange={() => setFinalStatus(aiStatus)}
                        className="size-4 accent-primary"
                      />
                      <span>
                        <span className="block font-medium">
                          Принять рекомендацию ИИ
                        </span>
                        <span className="mt-1 block text-muted-foreground">
                          {statusLabels[aiStatus]}
                        </span>
                      </span>
                    </label>
                  ) : (
                    <div className="flex items-center rounded-xl bg-muted/40 p-4 text-sm text-muted-foreground">
                      {aiStatus
                        ? 'ИИ рекомендует то же решение.'
                        : 'ИИ не даёт однозначной рекомендации. Вы можете подтвердить своё решение или вернуться к материалам ниже.'}
                    </div>
                  )}
                </div>
              </fieldset>
              {adoptingOpposite ? (
                <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
                  <label
                    htmlFor="change-reason"
                    className="text-sm font-semibold"
                  >
                    Почему вы изменили решение?
                  </label>
                  <p
                    id="change-reason-help"
                    className="mt-1 text-sm text-muted-foreground"
                  >
                    Какой аргумент ИИ повлиял на вашу оценку? Это внутренний
                    комментарий, кандидат его не увидит.
                  </p>
                  <Textarea
                    id="change-reason"
                    aria-describedby="change-reason-help"
                    className="mt-3 min-h-24 bg-background text-base"
                    value={changeReason}
                    onChange={(event) => setChangeReason(event.target.value)}
                    placeholder="Объясните, что убедило вас пересмотреть первоначальное решение"
                    required
                    maxLength={10000}
                    disabled={busy}
                  />
                </div>
              ) : null}
              <div>
                <label
                  htmlFor="final-feedback"
                  className="text-sm font-semibold"
                >
                  Фидбэк, который увидит кандидат
                </label>
                <Textarea
                  id="final-feedback"
                  className="mt-2 min-h-32 text-base"
                  value={finalFeedback}
                  onChange={(event) => setFinalFeedback(event.target.value)}
                  required
                  maxLength={10000}
                  disabled={busy}
                />
                {adoptingOpposite ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    Проверьте, что фидбэк соответствует новому решению.
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-5">
                <p className="text-sm text-muted-foreground">
                  После подтверждения результат появится у кандидата.
                </p>
                <Button
                  type="submit"
                  className="h-auto min-h-11 whitespace-normal px-4 py-3"
                  disabled={
                    busy ||
                    !finalFeedback.trim() ||
                    (adoptingOpposite && !changeReason.trim())
                  }
                >
                  {busy
                    ? 'Подтверждаем…'
                    : `Подтвердить: ${finalStatus ? statusLabels[finalStatus].toLowerCase() : 'решение'}`}
                  <Check aria-hidden="true" />
                </Button>
              </div>
            </form>
          ) : null}
          {review.finalDecision ? (
            <div className="surface-card border-primary/30 p-5 sm:p-6">
              <div className="flex items-center gap-2">
                <CheckCircle2
                  className="size-5 text-primary"
                  aria-hidden="true"
                />
                <h3 className="font-semibold">
                  {statusLabels[review.finalDecision.status]}
                </h3>
              </div>
              <p className="mt-3 whitespace-pre-wrap break-words text-base leading-7">
                {review.finalDecision.candidateFeedback}
              </p>
              {review.changeReason ? (
                <div className="mt-4 border-t pt-4">
                  <p className="text-sm font-medium">
                    Причина изменения · только для команды
                  </p>
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">
                    {review.changeReason}
                  </p>
                </div>
              ) : null}
            </div>
          ) : null}
          <details className="surface-card p-5">
            <summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-ring">
              Ответы и ваши оценки · {review.questions.length}
            </summary>
            <div className="mt-4 divide-y">
              {review.questions.map((item, index) => (
                <div key={item.questionId} className="py-4">
                  <p className="font-medium">
                    {index + 1}. {item.text}
                  </p>
                  <p className="mt-2 whitespace-pre-wrap break-words text-base leading-7">
                    {item.answerText || 'Записанного ответа нет.'}
                  </p>
                  <p className="mt-3 text-sm text-muted-foreground">
                    Ваша оценка: {ratingLabel(item.rating)}
                  </p>
                </div>
              ))}
            </div>
          </details>
          <details className="surface-card p-5">
            <summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-ring">
              Подробный анализ ИИ
            </summary>
            <AnswerEvidence
              items={review.items}
              media={media}
              notify={notify}
            />
          </details>
        </section>
      ) : null}

      {step < 3 ? (
        <p className="flex items-center gap-2 px-1 text-sm text-muted-foreground">
          <LockKeyhole className="size-4 shrink-0" aria-hidden="true" />
          Рекомендация ИИ откроется после вашего решения и фидбэка.
        </p>
      ) : null}
      {media?.assets.length ? (
        <details className="rounded-xl border bg-card p-4">
          <summary className="cursor-pointer text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">
            Скачать материалы интервью
          </summary>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {media.assets.map((asset) => (
              <a
                key={asset.id}
                href={asset.downloadUrl}
                download={asset.filename}
                className="flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
              >
                <Download className="size-4 shrink-0" aria-hidden="true" />
                <span className="min-w-0 break-all">{asset.filename}</span>
              </a>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
