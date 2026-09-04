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
  BriefcaseBusiness,
  Check,
  CheckCircle2,
  ChevronRight,
  Clipboard,
  Download,
  Eye,
  LoaderCircle,
  LockKeyhole,
  Plus,
  Save,
  ShieldCheck,
  Sparkles,
  Upload,
  UserPlus,
  Users,
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
  Approval,
  CandidateDetail,
  CandidateMedia,
  CandidateSummary,
  DecisionInput,
  HiringDecision,
  InterviewQuestion,
  PositionDetail,
  PositionSummary,
  ProcessingStatus,
} from '@/lib/types';

type HrView =
  | { type: 'dashboard' }
  | { type: 'create-position' }
  | { type: 'position'; positionId: string }
  | { type: 'candidate'; candidateId: string; positionId: string };

type HrAppProps = { notify: (message: string) => void };

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
  if (status === 'ready')
    return { label: 'Нужно решение', className: 'bg-amber-50 text-amber-800' };
  if (status === 'invited')
    return {
      label: 'Ссылка отправлена',
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

function CandidateStatus({ candidate }: { candidate: CandidateSummary }) {
  const copy = statusCopy(candidate.processingStatus, candidate.hiringDecision);
  return <Badge className={copy.className}>{copy.label}</Badge>;
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

function HrSidebar({
  view,
  onNavigate,
}: {
  view: HrView;
  onNavigate: (view: HrView) => void;
}) {
  return (
    <aside className="sidebar">
      <nav aria-label="Навигация рекрутера" className="space-y-1">
        <button
          className={`side-link ${view.type === 'dashboard' ? 'side-link-active' : ''}`}
          onClick={() => onNavigate({ type: 'dashboard' })}
        >
          <BriefcaseBusiness aria-hidden="true" /> Позиции
        </button>
        <button
          className="side-link"
          onClick={() => onNavigate({ type: 'create-position' })}
        >
          <Plus aria-hidden="true" /> Новая позиция
        </button>
      </nav>
      <div className="mt-auto rounded-2xl bg-[#1b1b20] p-4 text-white">
        <ShieldCheck className="mb-3 size-5" aria-hidden="true" />
        <p className="text-sm font-medium">Решение остаётся за командой</p>
        <p className="mt-1 text-xs leading-relaxed text-white/60">
          Итог AI откроется после проверки каждого пункта анализа.
        </p>
      </div>
    </aside>
  );
}

function Dashboard({
  positions,
  loading,
  error,
  onRetry,
  onOpen,
  onCreate,
}: {
  positions: PositionSummary[];
  loading: boolean;
  error: string;
  onRetry: () => void;
  onOpen: (id: string) => void;
  onCreate: () => void;
}) {
  if (loading) return <Busy label="Загружаем позиции…" />;
  if (error) return <ErrorPanel message={error} onRetry={onRetry} />;

  return (
    <div className="mx-auto max-w-[1120px]">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Рабочее пространство HR</p>
          <h1 className="page-title">Позиции найма</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Настройте интервью, добавьте резюме и согласуйте вопросы до отправки
            кандидату.
          </p>
        </div>
        <Button size="lg" onClick={onCreate}>
          <Plus data-icon="inline-start" /> Создать позицию
        </Button>
      </div>

      {positions.length ? (
        <div className="space-y-3">
          {positions.map((position) => (
            <button
              key={position.id}
              className="surface-card position-card group w-full text-left"
              onClick={() => onOpen(position.id)}
            >
              <span className="min-w-0 flex-1">
                <span className="mb-2 flex flex-wrap gap-2">
                  <Badge className="bg-emerald-50 text-emerald-700">
                    {position.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {formatDate(position.createdAt)}
                  </span>
                </span>
                <span className="block truncate text-xl font-semibold">
                  {position.title}
                </span>
                <span className="mt-1 block text-sm text-muted-foreground">
                  {position.level} · {position.location || 'Локация не указана'}
                </span>
                <span className="mt-3 block text-xs text-muted-foreground">
                  {position.questionCount} вопросов · {position.durationMinutes}{' '}
                  минут
                </span>
              </span>
              <span className="text-right max-sm:text-left">
                <span className="block text-xl font-semibold">
                  {position.candidateCount}
                </span>
                <span className="text-xs text-muted-foreground">
                  кандидатов
                </span>
              </span>
              <ChevronRight
                className="size-4 text-muted-foreground"
                aria-hidden="true"
              />
            </button>
          ))}
        </div>
      ) : (
        <div className="surface-card grid min-h-72 place-items-center p-8 text-center">
          <div>
            <BriefcaseBusiness
              className="mx-auto size-7 text-muted-foreground"
              aria-hidden="true"
            />
            <h2 className="mt-4 font-medium">Пока нет позиций</h2>
            <Button className="mt-5" onClick={onCreate}>
              Создать первую
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function FileField({
  id,
  label,
  hint,
  accept,
  file,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
}) {
  return (
    <label
      className="block rounded-2xl border border-dashed bg-muted/35 p-5"
      htmlFor={id}
      aria-label={label}
    >
      <span className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
          <Upload className="size-4" aria-hidden="true" />
        </span>
        <span>
          <span className="block text-sm font-medium">{label}</span>
          <span className="mt-1 block text-xs text-muted-foreground">
            {file ? file.name : hint}
          </span>
        </span>
      </span>
      <input
        id={id}
        className="mt-4 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-background file:px-3 file:py-2 file:font-medium"
        type="file"
        accept={accept}
        required
        onChange={(event) => onChange(event.target.files?.[0] || null)}
      />
    </label>
  );
}

function CreatePosition({
  onBack,
  onCreated,
}: {
  onBack: () => void;
  onCreated: (position: PositionDetail) => void;
}) {
  const [title, setTitle] = useState('');
  const [level, setLevel] = useState('');
  const [location, setLocation] = useState('');
  const [requirements, setRequirements] = useState('');
  const [seedQuestions, setSeedQuestions] = useState('');
  const [questionCount, setQuestionCount] = useState(6);
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [maxFollowUpQuestions, setMaxFollowUpQuestions] = useState(2);
  const [vacancy, setVacancy] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!vacancy || saving) return;
    setSaving(true);
    setError('');
    try {
      const position = await api.createPosition({
        title,
        level,
        location,
        requirements: requirements
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean),
        questionCount,
        durationMinutes,
        maxFollowUpQuestions,
        seedQuestions: seedQuestions
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean),
        vacancy,
      });
      onCreated(position);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl">
      <BackButton onClick={onBack} label="К позициям" />
      <p className="eyebrow">Новая позиция</p>
      <h1 className="page-title">Настройка интервью</h1>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        Вакансия задаёт контекст, требования становятся критериями, а готовые
        вопросы можно оставить пустыми.
      </p>

      <form className="mt-8 space-y-4" onSubmit={submit}>
        <section className="form-section space-y-4">
          <h2 className="font-semibold">Позиция и файл вакансии</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <label
              className="field-label sm:col-span-2"
              htmlFor="position-title"
            >
              Название *
              <Input
                id="position-title"
                className="mt-2"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </label>
            <label className="field-label" htmlFor="position-level">
              Уровень
              <Input
                id="position-level"
                className="mt-2"
                value={level}
                onChange={(e) => setLevel(e.target.value)}
              />
            </label>
            <label className="field-label" htmlFor="position-location">
              Локация и формат
              <Input
                id="position-location"
                className="mt-2"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </label>
          </div>
          <label className="field-label" htmlFor="max-follow-ups">
            Максимум уточняющих вопросов
            <Input
              id="max-follow-ups"
              className="mt-2"
              type="number"
              min={0}
              max={10}
              value={maxFollowUpQuestions}
              onChange={(e) => setMaxFollowUpQuestions(Number(e.target.value))}
              required
            />
          </label>
          <FileField
            id="vacancy-file"
            label="Файл вакансии *"
            hint="PDF, DOCX или TXT"
            accept=".pdf,.docx,.txt"
            file={vacancy}
            onChange={setVacancy}
          />
        </section>

        <section className="form-section space-y-4">
          <h2 className="font-semibold">Ограничения интервью</h2>
          <label className="field-label" htmlFor="position-requirements">
            Требования к кандидату *
            <Textarea
              id="position-requirements"
              className="mt-2 min-h-40"
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
              placeholder="Одно требование на строку"
              required
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="field-label" htmlFor="question-count">
              Количество вопросов
              <Input
                id="question-count"
                className="mt-2"
                type="number"
                min={1}
                max={20}
                value={questionCount}
                onChange={(e) => setQuestionCount(Number(e.target.value))}
                required
              />
            </label>
            <label className="field-label" htmlFor="duration-minutes">
              Продолжительность, минут
              <Input
                id="duration-minutes"
                className="mt-2"
                type="number"
                min={5}
                max={120}
                value={durationMinutes}
                onChange={(e) => setDurationMinutes(Number(e.target.value))}
                required
              />
            </label>
          </div>
          <label className="field-label" htmlFor="seed-questions">
            Готовые вопросы · необязательно
            <Textarea
              id="seed-questions"
              className="mt-2 min-h-36"
              value={seedQuestions}
              onChange={(e) => setSeedQuestions(e.target.value)}
              placeholder="По одному на строку. AI дополнит список до заданного количества."
            />
          </label>
        </section>

        {error ? (
          <p
            className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800"
            role="alert"
          >
            {error}
          </p>
        ) : null}
        <div className="sticky-form-actions">
          <Button type="button" variant="ghost" onClick={onBack}>
            Отмена
          </Button>
          <Button
            type="submit"
            disabled={
              saving || !vacancy || !title.trim() || !requirements.trim()
            }
          >
            {saving ? (
              <LoaderCircle className="animate-spin" data-icon="inline-start" />
            ) : null}
            {saving ? 'Создаём…' : 'Создать позицию'}
          </Button>
        </div>
      </form>
    </div>
  );
}

function AddCandidateDialog({
  open,
  positionId,
  onOpenChange,
  onAdded,
}: {
  open: boolean;
  positionId: string;
  onOpenChange: (open: boolean) => void;
  onAdded: (candidate: CandidateDetail) => void;
}) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('');
  const [resume, setResume] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!resume || saving) return;
    setSaving(true);
    setError('');
    try {
      const candidate = await api.addCandidate(positionId, {
        name,
        email,
        role,
        resume,
      });
      onAdded(candidate);
      onOpenChange(false);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-2xl p-5 sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Добавить кандидата</DialogTitle>
          <DialogDescription>
            После загрузки резюме AI подготовит персонализированный черновик
            вопросов.
          </DialogDescription>
        </DialogHeader>
        <form id="candidate-form" className="space-y-4" onSubmit={submit}>
          <label className="field-label" htmlFor="candidate-name">
            Имя *
            <Input
              id="candidate-name"
              className="mt-2"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="field-label" htmlFor="candidate-email">
              Email
              <Input
                id="candidate-email"
                className="mt-2"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="field-label" htmlFor="candidate-role">
              Текущая роль
              <Input
                id="candidate-role"
                className="mt-2"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              />
            </label>
          </div>
          <FileField
            id="resume-file"
            label="Резюме *"
            hint="PDF, DOCX или TXT"
            accept=".pdf,.docx,.txt"
            file={resume}
            onChange={setResume}
          />
          {error ? (
            <p
              className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800"
              role="alert"
            >
              {error}
            </p>
          ) : null}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            type="submit"
            form="candidate-form"
            disabled={!resume || !name.trim() || saving}
          >
            {saving ? 'Генерируем вопросы…' : 'Загрузить и продолжить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PositionView({
  positionId,
  onBack,
  onCandidate,
}: {
  positionId: string;
  onBack: () => void;
  onCandidate: (candidateId: string) => void;
}) {
  const [position, setPosition] = useState<PositionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getPosition(positionId, controller.signal)
      .then((data) => {
        setPosition(data);
        setError('');
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [positionId, reloadKey]);

  if (loading) return <Busy label="Открываем позицию…" />;
  if (error || !position)
    return (
      <ErrorPanel
        message={error || 'Позиция не найдена.'}
        onRetry={() => setReloadKey((key) => key + 1)}
      />
    );

  return (
    <div className="mx-auto max-w-[1120px]">
      <BackButton onClick={onBack} label="К позициям" />
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <Badge className="bg-emerald-50 text-emerald-700">
            {position.status}
          </Badge>
          <h1 className="page-title !mt-3">{position.title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {position.level} · {position.location}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {position.questionCount} вопросов · до{' '}
            {position.maxFollowUpQuestions} уточнений ·{' '}
            {position.durationMinutes} минут · {position.vacancyFilename}
          </p>
        </div>
        <Button size="lg" onClick={() => setAddOpen(true)}>
          <UserPlus data-icon="inline-start" />
          Добавить кандидата
        </Button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="surface-card" aria-labelledby="candidates-heading">
          <div className="border-b p-5">
            <h2 id="candidates-heading" className="font-semibold">
              Кандидаты
            </h2>
          </div>
          {position.candidates.length ? (
            <div className="p-2 sm:p-3">
              {position.candidates.map((candidate) => (
                <button
                  key={candidate.id}
                  className="candidate-row w-full text-left"
                  onClick={() => onCandidate(candidate.id)}
                >
                  <span className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
                    {initials(candidate.name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {candidate.name}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {candidate.role}
                    </span>
                  </span>
                  <CandidateStatus candidate={candidate} />
                  <ChevronRight
                    className="size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                </button>
              ))}
            </div>
          ) : (
            <div className="grid min-h-64 place-items-center p-8 text-center">
              <div>
                <Users className="mx-auto size-6 text-muted-foreground" />
                <p className="mt-3 text-sm">Загрузите первое резюме</p>
              </div>
            </div>
          )}
        </section>
        <aside className="space-y-4">
          <section className="surface-card p-5">
            <h2 className="text-sm font-semibold">О вакансии</h2>
            <p className="mt-3 line-clamp-6 text-xs leading-relaxed text-muted-foreground">
              {position.description}
            </p>
          </section>
          <section className="surface-card p-5">
            <h2 className="text-sm font-semibold">Требования</h2>
            <ul className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
              {position.requirements.map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
          </section>
          <section className="surface-card p-5">
            <h2 className="text-sm font-semibold">Вопросы от HR</h2>
            <p className="mt-2 text-xs text-muted-foreground">
              {position.seedQuestions.length
                ? position.seedQuestions.join(' · ')
                : 'Не заданы — AI сформирует весь список.'}
            </p>
          </section>
        </aside>
      </div>

      <AddCandidateDialog
        open={addOpen}
        positionId={position.id}
        onOpenChange={setAddOpen}
        onAdded={(candidate) => {
          setPosition((current) =>
            current
              ? { ...current, candidates: [...current.candidates, candidate] }
              : current,
          );
          onCandidate(candidate.id);
        }}
      />
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
                    {question.kind === 'provided' ? 'От HR' : 'AI'}
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

function evidenceLabel(evidence: Record<string, unknown>) {
  const quote = evidence.quote || evidence.text || evidence.transcript;
  if (typeof quote === 'string') return quote;
  return Object.entries(evidence)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' · ');
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
                {activeItem.evidence.length ? (
                  <div className="mt-5 space-y-2">
                    {activeItem.evidence.map((entry, index) => (
                      <blockquote
                        key={index}
                        className="rounded-xl border-l-4 border-l-primary bg-background p-3 text-sm leading-relaxed"
                      >
                        {evidenceLabel(entry)}
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
                  placeholder="Что подтверждено и чего не хватило для этой позиции"
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
    </div>
  );
}

function CandidateWorkspace({
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

export function HrApp({ notify }: HrAppProps) {
  const [view, setView] = useState<HrView>({ type: 'dashboard' });
  const [positions, setPositions] = useState<PositionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .listPositions(controller.signal)
      .then((items) => {
        setPositions(items);
        setError('');
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [reloadKey]);

  const content = useMemo(() => {
    if (view.type === 'create-position') {
      return (
        <CreatePosition
          onBack={() => setView({ type: 'dashboard' })}
          onCreated={(position) => {
            setPositions((items) => [...items, position]);
            setView({ type: 'position', positionId: position.id });
            notify(`Позиция «${position.title}» создана`);
          }}
        />
      );
    }
    if (view.type === 'position') {
      return (
        <PositionView
          positionId={view.positionId}
          onBack={() => {
            setView({ type: 'dashboard' });
            setReloadKey((key) => key + 1);
          }}
          onCandidate={(candidateId) =>
            setView({
              type: 'candidate',
              positionId: view.positionId,
              candidateId,
            })
          }
        />
      );
    }
    if (view.type === 'candidate') {
      return (
        <CandidateWorkspace
          candidateId={view.candidateId}
          onBack={() =>
            setView({ type: 'position', positionId: view.positionId })
          }
          notify={notify}
        />
      );
    }
    return (
      <Dashboard
        positions={positions}
        loading={loading}
        error={error}
        onRetry={() => setReloadKey((key) => key + 1)}
        onOpen={(positionId) => setView({ type: 'position', positionId })}
        onCreate={() => setView({ type: 'create-position' })}
      />
    );
  }, [error, loading, notify, positions, view]);

  return (
    <div className="app-grid">
      <HrSidebar view={view} onNavigate={setView} />
      <main className="min-w-0 px-5 pb-14 pt-7 sm:px-8 xl:px-12">
        <div className="mobile-product-nav">
          <button onClick={() => setView({ type: 'dashboard' })}>
            <BriefcaseBusiness />
            Позиции
          </button>
          <button onClick={() => setView({ type: 'create-position' })}>
            <Plus />
            Новая
          </button>
        </div>
        {content}
      </main>
    </div>
  );
}
