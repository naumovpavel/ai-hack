'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, LoaderCircle } from 'lucide-react';
import { Brand } from './shared';
import { researchDemoSteps as examples } from './research-demo';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api';
import {
  researchApi,
  type Baseline,
  type Followup,
  type ResearchSession,
} from '@/lib/research-api';
import {
  REASON_OPTIONS,
  type ReasonGroup,
  type YesNo,
} from '@/lib/research-catalog';

const STORAGE_KEY = 'signal.research.v2';
const ANSWER_KEYS = {
  trust: 'trust',
  readiness: 'readiness',
  experience: 'experienceLiked',
  solution: 'solutionLiked',
} as const;
type Draft = {
  hadInterview?: YesNo;
  hadAiInterview?: YesNo;
  experienceLiked?: YesNo;
  trust?: YesNo;
  readiness?: YesNo;
  solutionLiked?: YesNo;
  experienceFactors: string[];
  experienceReason: string;
  trustFactors: string[];
  trustReason: string;
  readinessFactors: string[];
  readinessReason: string;
  solutionFactors: string[];
  solutionReason: string;
};
const emptyDraft = (): Draft => ({
  experienceFactors: [],
  experienceReason: '',
  trustFactors: [],
  trustReason: '',
  readinessFactors: [],
  readinessReason: '',
  solutionFactors: [],
  solutionReason: '',
});
const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : 'Не удалось сохранить ответы. Попробуйте ещё раз.';

function newParticipantToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function readDraft(value: unknown): Draft {
  const draft = emptyDraft();
  if (!value || typeof value !== 'object') return draft;
  const saved = value as Record<string, unknown>;
  for (const key of [
    'hadInterview',
    'hadAiInterview',
    'experienceLiked',
    'trust',
    'readiness',
    'solutionLiked',
  ] as const) {
    if (saved[key] === 'yes' || saved[key] === 'no') draft[key] = saved[key];
  }
  for (const group of Object.keys(ANSWER_KEYS) as ReasonGroup[]) {
    const answer = draft[ANSWER_KEYS[group]];
    const factorsKey = `${group}Factors` as const;
    const reasonKey = `${group}Reason` as const;
    if (answer) {
      const savedFactors = saved[factorsKey];
      draft[factorsKey] = REASON_OPTIONS[group][answer]
        .map((option) => option.id)
        .filter(
          (id) => Array.isArray(savedFactors) && savedFactors.includes(id),
        );
      if (typeof saved[reasonKey] === 'string')
        draft[reasonKey] = saved[reasonKey].slice(0, 2000);
    }
  }
  return draft;
}
function hasReason(draft: Draft, group: ReasonGroup) {
  return Boolean(
    draft[`${group}Factors`].length || draft[`${group}Reason`].trim(),
  );
}

function Choice({
  id,
  title,
  value,
  onChange,
}: {
  id: string;
  title: string;
  value?: YesNo;
  onChange: (value: YesNo) => void;
}) {
  return (
    <fieldset className="space-y-4">
      <legend
        id={`${id}-label`}
        className="text-base font-medium leading-relaxed"
      >
        {title}
      </legend>
      <RadioGroup
        aria-labelledby={`${id}-label`}
        value={value ?? ''}
        onValueChange={(next) => onChange(next as YesNo)}
        className="grid grid-cols-2 gap-3"
      >
        {(['yes', 'no'] as const).map((key) => (
          <label
            key={key}
            htmlFor={`${id}-${key}`}
            className={`flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 ${value === key ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'}`}
          >
            <RadioGroupItem id={`${id}-${key}`} value={key} />
            {key === 'yes' ? 'Да' : 'Нет'}
          </label>
        ))}
      </RadioGroup>
    </fieldset>
  );
}
function BranchQuestion({
  group,
  title,
  draft,
  onAnswer,
  onFactors,
  onReason,
}: {
  group: ReasonGroup;
  title: string;
  draft: Draft;
  onAnswer: (group: ReasonGroup, value: YesNo) => void;
  onFactors: (group: ReasonGroup, value: string[]) => void;
  onReason: (group: ReasonGroup, value: string) => void;
}) {
  const answer = draft[ANSWER_KEYS[group]];
  const selected = draft[`${group}Factors`];
  return (
    <div className="space-y-5">
      <Choice
        id={group}
        title={title}
        value={answer}
        onChange={(value) => onAnswer(group, value)}
      />
      {answer && (
        <fieldset className="space-y-3 border-l-2 border-primary/25 pl-4 sm:pl-5">
          <legend className="mb-2 text-base font-medium">
            {answer === 'yes' ? 'Почему да?' : 'Почему нет?'}
          </legend>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Выберите подходящие причины или напишите свой ответ. Можно выбрать
            несколько вариантов и дополнить их.
          </p>
          <div className="grid gap-2">
            {REASON_OPTIONS[group][answer].map((option) => (
              <label
                key={option.id}
                htmlFor={`${group}-factor-${option.id}`}
                className={`flex min-h-12 cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 ${selected.includes(option.id) ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'}`}
              >
                <Checkbox
                  id={`${group}-factor-${option.id}`}
                  className="mt-1"
                  checked={selected.includes(option.id)}
                  onCheckedChange={(checked) =>
                    onFactors(
                      group,
                      REASON_OPTIONS[group][answer]
                        .map((item) => item.id)
                        .filter((id) =>
                          id === option.id
                            ? Boolean(checked)
                            : selected.includes(id),
                        ),
                    )
                  }
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
          <label
            htmlFor={`${group}-reason`}
            className="block pt-2 text-sm font-medium"
          >
            Другая причина или дополнение
          </label>
          <Textarea
            id={`${group}-reason`}
            value={draft[`${group}Reason`]}
            maxLength={2000}
            onChange={(event) => onReason(group, event.target.value)}
            placeholder="Напишите своими словами. Необязательно, если выбрали причину выше"
            className="min-h-24 text-base md:text-base"
          />
        </fieldset>
      )}
    </div>
  );
}

export function ResearchSurvey() {
  const [token, setToken] = useState('');
  const tokenRef = useRef('');
  const [session, setSession] = useState<ResearchSession | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [storageWarning, setStorageWarning] = useState(false);
  const [example, setExample] = useState(0);
  const [reviewingDemo, setReviewingDemo] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const savedStage =
    session?.status === 'complete'
      ? 3
      : session?.status === 'demo'
        ? 2
        : session
          ? 1
          : 0;
  const stage = reviewingDemo && savedStage === 2 ? 1 : savedStage;

  useEffect(() => {
    let cancelled = false;
    const restore = async () => {
      setLoading(true);
      setRestoreFailed(false);
      setError('');
      let saved: { token?: string; draft?: unknown; stage?: number } = {};
      try {
        const parsed: unknown = JSON.parse(
          localStorage.getItem(STORAGE_KEY) || '{}',
        );
        if (parsed && typeof parsed === 'object') saved = parsed;
      } catch {
        setStorageWarning(true);
      }
      try {
        const secret =
          typeof saved.token === 'string' &&
          /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
            saved.token,
          )
            ? saved.token
            : tokenRef.current || newParticipantToken();
        tokenRef.current = secret;
        setToken(secret);
        try {
          localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ ...saved, token: secret }),
          );
        } catch {
          setStorageWarning(true);
        }
        const result = await researchApi.session(secret);
        if (cancelled) return;
        setSession(result);
        if (saved.draft && saved.stage === (result.status === 'demo' ? 2 : 1))
          setDraft(readDraft(saved.draft));
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.status === 404) {
          if (saved.draft && saved.stage === 0)
            setDraft(readDraft(saved.draft));
        } else {
          setError(message(caught));
          setRestoreFailed(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void restore();
    return () => {
      cancelled = true;
    };
  }, [revision]);

  useEffect(() => {
    if (!token || loading || restoreFailed) return;
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          token,
          draft: savedStage === 3 ? undefined : draft,
          stage: savedStage,
        }),
      );
    } catch {
      queueMicrotask(() => setStorageWarning(true));
    }
  }, [token, draft, savedStage, loading, restoreFailed]);
  useEffect(() => {
    if (!loading) {
      heading.current?.focus();
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
  }, [stage, example, loading]);

  const onAnswer = (group: ReasonGroup, value: YesNo) =>
    setDraft((previous) =>
      previous[ANSWER_KEYS[group]] === value
        ? previous
        : {
            ...previous,
            [ANSWER_KEYS[group]]: value,
            [`${group}Factors`]: [],
            [`${group}Reason`]: '',
          },
    );
  const onFactors = (group: ReasonGroup, value: string[]) =>
    setDraft((previous) => ({ ...previous, [`${group}Factors`]: value }));
  const onReason = (group: ReasonGroup, value: string) =>
    setDraft((previous) => ({ ...previous, [`${group}Reason`]: value }));
  const question = (group: ReasonGroup, title: string) => (
    <BranchQuestion
      group={group}
      title={title}
      draft={draft}
      onAnswer={onAnswer}
      onFactors={onFactors}
      onReason={onReason}
    />
  );
  const setExperience = (
    key: 'hadInterview' | 'hadAiInterview',
    value: YesNo,
  ) =>
    setDraft((previous) =>
      previous[key] === value
        ? previous
        : {
            ...previous,
            [key]: value,
            hadAiInterview:
              key === 'hadInterview'
                ? value === 'no'
                  ? 'no'
                  : undefined
                : value,
            experienceLiked: undefined,
            experienceFactors: [],
            experienceReason: '',
          },
    );

  const save = async () => {
    if (busy) return;
    if (stage === 0 || stage === 2) {
      if (
        !draft.trust ||
        !draft.readiness ||
        !hasReason(draft, 'trust') ||
        !hasReason(draft, 'readiness')
      ) {
        setError(
          'Ответьте «Да» или «Нет» на вопросы о доверии и готовности. Для каждого выберите причину или напишите свой ответ.',
        );
        return;
      }
      if (
        stage === 0 &&
        (!consent ||
          !draft.hadInterview ||
          !draft.hadAiInterview ||
          (draft.hadAiInterview === 'yes' &&
            (!draft.experienceLiked || !hasReason(draft, 'experience'))))
      ) {
        setError(
          'Ответьте на вопросы об опыте и подтвердите участие в исследовании.',
        );
        return;
      }
      if (
        stage === 2 &&
        (!draft.solutionLiked || !hasReason(draft, 'solution'))
      ) {
        setError(
          'Укажите, понравился ли показанный формат, и выберите причину или напишите свой ответ.',
        );
        return;
      }
    }
    setBusy(true);
    setError('');
    try {
      const opinion = {
        trust: draft.trust!,
        trustFactors: draft.trustFactors,
        trustReason: draft.trustReason.trim(),
        readiness: draft.readiness!,
        readinessFactors: draft.readinessFactors,
        readinessReason: draft.readinessReason.trim(),
      };
      let next: ResearchSession;
      if (stage === 0)
        next = await researchApi.baseline(token, {
          ...opinion,
          hadInterview: draft.hadInterview!,
          hadAiInterview: draft.hadAiInterview!,
          experienceLiked:
            draft.hadAiInterview === 'yes' ? draft.experienceLiked! : null,
          experienceFactors:
            draft.hadAiInterview === 'yes' ? draft.experienceFactors : [],
          experienceReason:
            draft.hadAiInterview === 'yes' ? draft.experienceReason.trim() : '',
        } satisfies Baseline);
      else if (stage === 1) next = await researchApi.demo(token);
      else
        next = await researchApi.complete(token, {
          ...opinion,
          solutionLiked: draft.solutionLiked!,
          solutionFactors: draft.solutionFactors,
          solutionReason: draft.solutionReason.trim(),
        } satisfies Followup);
      setSession(next);
      setReviewingDemo(false);
      setDraft(emptyDraft());
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-dvh bg-background">
      <header className="topbar justify-between gap-4">
        <Link href="/" aria-label="Slopy — на главную">
          <Brand />
        </Link>
        <span className="text-sm text-muted-foreground">
          Исследование опыта кандидатов
        </span>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-12">
        <ol
          className="mb-9 grid grid-cols-3 gap-3"
          aria-label="Этапы исследования"
        >
          {['Ваш опыт', 'Пример работы', 'Ваше мнение'].map((label, index) => (
            <li
              key={label}
              aria-current={stage === index ? 'step' : undefined}
              className={`border-t-2 pt-3 ${stage >= index ? 'border-primary' : 'border-border text-muted-foreground'}`}
            >
              <span className="flex items-center gap-2 text-sm">
                {stage > index ? (
                  <Check className="size-4 text-accent-foreground" />
                ) : (
                  <span>{index + 1}.</span>
                )}
                {label}
              </span>
            </li>
          ))}
        </ol>
        {loading ? (
          <output className="flex min-h-64 items-center justify-center gap-3">
            <LoaderCircle className="size-5 animate-spin" />
            Загружаем опрос…
          </output>
        ) : restoreFailed ? (
          <section className="surface-card space-y-4 p-6">
            <h1 className="text-2xl font-semibold">
              Не удалось восстановить опрос
            </h1>
            <p role="alert">{error}</p>
            <p className="text-sm text-muted-foreground">
              Сохранённый черновик остаётся в браузере. Повторите загрузку,
              когда соединение восстановится.
            </p>
            <Button onClick={() => setRevision((value) => value + 1)}>
              Повторить загрузку
            </Button>
          </section>
        ) : (
          <>
            <h1
              ref={heading}
              tabIndex={-1}
              className="text-3xl font-semibold tracking-tight outline-none sm:text-4xl"
            >
              {
                [
                  'Как вы относитесь к интервью с ИИ?',
                  'Посмотрите, как работает Slopy',
                  'Что вы думаете после знакомства?',
                  'Спасибо за участие',
                ][stage]
              }
            </h1>
            <p className="mt-4 text-base leading-relaxed text-muted-foreground">
              {
                [
                  'Участие без входа в Telegram. Два коротких опроса и знакомство с сервисом. Здесь нет правильных ответов — нам важно ваше мнение.',
                  'От подготовки до обратной связи: покажем темы, пробное интервью, разбор ответов и работу HR. В примерах используются вымышленные ответы, чтобы объяснить процесс.',
                  'Ответьте на те же вопросы с учётом увиденного. Ваше мнение могло измениться или остаться прежним.',
                  'Оба опроса сохранены. Ваши ответы помогут нам понять отношение к интервью с ИИ и то, как на него влияет знакомство с сервисом.',
                ][stage]
              }
            </p>
            {storageWarning && stage < 3 && (
              <output className="mt-4 block rounded-xl bg-muted p-4 text-sm">
                Браузер не позволяет сохранить прогресс на этом устройстве.
                Пройдите опрос, не закрывая страницу.
              </output>
            )}
            {stage === 0 || stage === 2 ? (
              <form
                className="mt-8 space-y-8"
                onSubmit={(event) => {
                  event.preventDefault();
                  void save();
                }}
              >
                <fieldset
                  disabled={busy}
                  className="surface-card space-y-8 p-5 sm:p-8"
                >
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Здесь и далее: интервью при отборе на работу, в котором ИИ
                    задаёт вопросы и/или анализирует ваши ответы.
                  </p>
                  {stage === 0 && (
                    <>
                      <Choice
                        id="interview-experience"
                        title="Проходили ли вы собеседования при устройстве на работу?"
                        value={draft.hadInterview}
                        onChange={(value) =>
                          setExperience('hadInterview', value)
                        }
                      />
                      {draft.hadInterview === 'yes' && (
                        <Choice
                          id="ai-experience"
                          title="Проходили ли вы интервью с ИИ?"
                          value={draft.hadAiInterview}
                          onChange={(value) =>
                            setExperience('hadAiInterview', value)
                          }
                        />
                      )}
                      {draft.hadAiInterview === 'yes' && (
                        <div className="space-y-3">
                          <p className="text-sm text-muted-foreground">
                            Вспомните последнее интервью с ИИ, которое вы
                            проходили.
                          </p>
                          {question('experience', 'Вам понравился этот опыт?')}
                        </div>
                      )}
                      <div className="border-t" />
                    </>
                  )}
                  {question(
                    'trust',
                    'Доверяете ли вы интервью с ИИ как первому этапу отбора на работу?',
                  )}
                  <div className="border-t" />
                  {question(
                    'readiness',
                    'Готовы ли вы пройти интервью с ИИ на интересующую вас вакансию?',
                  )}
                  {stage === 2 && (
                    <div className="border-t pt-8">
                      {question(
                        'solution',
                        'Вам понравился показанный формат интервью?',
                      )}
                    </div>
                  )}
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Ответьте на каждый вопрос. Если готовые причины не подходят,
                    напишите свой ответ. Не указывайте имена, контакты и другие
                    личные данные.
                  </p>
                  {stage === 0 && (
                    <label
                      htmlFor="research-consent"
                      className="flex cursor-pointer items-start gap-3 rounded-xl bg-muted/60 p-4"
                    >
                      <Checkbox
                        id="research-consent"
                        checked={consent}
                        onCheckedChange={(checked) =>
                          setConsent(Boolean(checked))
                        }
                        className="mt-1"
                      />
                      <span className="text-sm leading-relaxed">
                        Участвую добровольно и согласен(на) на сохранение
                        ответов для исследования. Имя и контакты не
                        запрашиваются; ответы двух опросов связываются случайным
                        кодом. Ответы доступны только организатору исследования.
                      </span>
                    </label>
                  )}
                </fieldset>
                {error && (
                  <p
                    role="alert"
                    className="rounded-xl bg-destructive/10 p-4 text-destructive"
                  >
                    {error}
                  </p>
                )}
                <div className="flex flex-wrap items-center justify-between gap-4">
                  {stage === 2 ? (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => {
                        setReviewingDemo(true);
                        setExample(0);
                        setError('');
                      }}
                    >
                      <ArrowLeft className="size-4" />
                      Ещё раз посмотреть пример
                    </Button>
                  ) : (
                    <p className="max-w-xs text-sm leading-relaxed text-muted-foreground">
                      После перехода к примерам ответы первого опроса изменить
                      нельзя.
                    </p>
                  )}
                  <Button
                    type="submit"
                    size="lg"
                    disabled={busy}
                    className="w-full sm:w-auto"
                  >
                    {busy && <LoaderCircle className="size-4 animate-spin" />}
                    {stage === 0
                      ? 'Сохранить и посмотреть примеры'
                      : 'Завершить опрос'}
                    <ArrowRight className="size-4" />
                  </Button>
                </div>
              </form>
            ) : null}
            {stage === 1 && (
              <section className="mt-8">
                <div className="surface-card p-5 sm:p-8">
                  <div className="mb-5 flex items-center gap-3 text-accent-foreground">
                    {(() => {
                      const Icon = examples[example].icon;
                      return <Icon className="size-5" />;
                    })()}
                    <span className="text-sm font-medium">
                      Шаг {example + 1} из {examples.length}
                    </span>
                  </div>
                  <h2 className="text-2xl font-semibold">
                    {examples[example].title}
                  </h2>
                  <p className="mt-3 leading-relaxed text-muted-foreground">
                    {examples[example].intro}
                  </p>
                  <div className="my-6 border-t" />
                  {examples[example].content}
                </div>
                {error && (
                  <p
                    role="alert"
                    className="mt-5 rounded-xl bg-destructive/10 p-4 text-destructive"
                  >
                    {error}
                  </p>
                )}
                <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                  <Button
                    variant="ghost"
                    disabled={example === 0 || busy}
                    onClick={() => setExample((previous) => previous - 1)}
                  >
                    <ArrowLeft className="size-4" />
                    Назад
                  </Button>
                  <Button
                    size="lg"
                    disabled={busy}
                    onClick={() => {
                      if (example < examples.length - 1)
                        setExample((previous) => previous + 1);
                      else if (reviewingDemo) {
                        setReviewingDemo(false);
                        setError('');
                      } else void save();
                    }}
                  >
                    {busy && <LoaderCircle className="size-4 animate-spin" />}
                    {example < examples.length - 1
                      ? 'Дальше'
                      : reviewingDemo
                        ? 'Вернуться к ответам'
                        : 'Перейти ко второму опросу'}
                    <ArrowRight className="size-4" />
                  </Button>
                </div>
              </section>
            )}
            {stage === 3 && (
              <div className="surface-card mt-8 p-8">
                <span className="grid size-12 place-items-center rounded-full bg-primary/10 text-accent-foreground">
                  <Check className="size-6" />
                </span>
                <h2 className="mt-5 text-xl font-semibold">
                  Исследование завершено
                </h2>
                <p className="mt-3 leading-relaxed text-muted-foreground">
                  Можно закрыть эту страницу. Повторное открытие ссылки в этом
                  браузере не создаст новый ответ.
                </p>
                <Link
                  href="/"
                  className="mt-6 inline-flex min-h-11 items-center gap-2 font-medium text-accent-foreground"
                >
                  На главную Slopy
                  <ArrowRight className="size-4" />
                </Link>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
