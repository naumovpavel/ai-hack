'use client';

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type SyntheticEvent,
} from 'react';
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  Clipboard,
  FileText,
  Layers3,
  LoaderCircle,
  MessageSquare,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Upload,
  UserPlus,
  Users,
} from 'lucide-react';
import { CandidateWorkspace } from './candidate-workspace';
import { DeleteResourceButton } from './delete-resource-button';
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
import { Textarea } from '@/components/ui/textarea';
import { api } from '@/lib/api';
import { copyText } from '@/lib/clipboard';
import type {
  Approval,
  CandidateDraft,
  CandidateSummary,
  ContextDocument,
  EditableQuestion,
  InterviewPlan,
  InterviewPlanDetail,
  InterviewPlanDraft,
  InterviewTemplate,
  VacancyDetail,
  VacancyDraft,
  VacancyFields,
  VacancyTemplate,
} from '@/lib/types';

type View =
  | {
      type:
        | 'vacancies'
        | 'context'
        | 'vacancy-templates'
        | 'interview-templates'
        | 'candidates';
    }
  | { type: 'create-vacancy'; templateId?: string }
  | { type: 'vacancy'; vacancyId: string }
  | { type: 'create-interview'; vacancyId: string; canSkip?: boolean }
  | { type: 'interview'; interviewId: string; vacancyId: string }
  | {
      type: 'candidate';
      candidateId: string;
      interviewId?: string;
      vacancyId?: string;
    };

type Notify = (message: string) => void;
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : 'Не удалось выполнить действие. Попробуйте ещё раз.';
const fieldClass =
  'mt-2 flex h-10 w-full rounded-xl border border-input bg-background px-3 text-sm font-normal shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 disabled:opacity-50';

function useResource<T>(loader: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    loader(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setData(value);
          setError('');
        }
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [loader, revision]);
  return {
    data,
    setData,
    loading,
    error,
    reload: () => {
      setLoading(true);
      setRevision((value) => value + 1);
    },
  };
}

function Busy({
  title = 'Загружаем…',
  description,
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div
      className="surface-card grid min-h-64 place-items-center p-8 text-center"
      aria-live="polite"
      aria-busy="true"
    >
      <div>
        <LoaderCircle
          className="mx-auto size-8 animate-spin text-primary"
          aria-hidden="true"
        />
        <h2 className="mt-5 font-semibold">{title}</h2>
        {description ? (
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
    </div>
  );
}
function ErrorMessage({ message }: { message: string }) {
  return message ? (
    <p className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800" role="alert">
      {message}
    </p>
  ) : null;
}
function ErrorPanel({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="surface-card space-y-4 p-6">
      <ErrorMessage message={message} />
      <Button variant="outline" onClick={retry}>
        Повторить
      </Button>
    </div>
  );
}
function Back({
  onClick,
  label = 'К вакансиям',
}: {
  onClick: () => void;
  label?: string;
}) {
  return (
    <Button variant="ghost" className="-ml-2 mb-6" onClick={onClick}>
      <ArrowLeft data-icon="inline-start" />
      {label}
    </Button>
  );
}
function Heading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1 className="page-title">{title}</h1>
        {description ? (
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground sm:text-base">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
function Empty({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="grid min-h-64 place-items-center p-8 text-center">
      <div>
        <div className="mx-auto mb-5 flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
          {icon}
        </div>
        <h2 className="font-semibold">{title}</h2>
        {description ? (
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
        {action ? <div className="mt-5">{action}</div> : null}
      </div>
    </div>
  );
}
function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder = 'Выберите',
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <label className="field-label">
      {label}
      <select
        aria-label={label}
        className={fieldClass}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
function FilePicker({
  label,
  onFile,
  multiple = false,
  disabled = false,
}: {
  label: string;
  onFile: (files: File[]) => void;
  multiple?: boolean;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-primary/25 bg-primary/[0.025] px-6 py-12 text-center">
      <span className="mb-5 flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Upload className="size-6" />
      </span>
      <Button
        type="button"
        size="lg"
        disabled={disabled}
        onClick={() => input.current?.click()}
      >
        <Upload data-icon="inline-start" />
        {label}
      </Button>
      <p className="mt-3 text-xs text-muted-foreground">
        PDF, DOCX или TXT · до 50 МБ
      </p>
      <input
        ref={input}
        aria-label={label}
        type="file"
        accept=".pdf,.docx,.txt"
        multiple={multiple}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          event.target.value = '';
          const invalid = files.find(
            (file) =>
              file.size > 50 * 1024 * 1024 ||
              !/\.(pdf|docx|txt)$/i.test(file.name),
          );
          if (invalid) {
            setError(
              `Файл «${invalid.name}» должен быть PDF, DOCX или TXT размером до 50 МБ.`,
            );
            return;
          }
          setError('');
          if (files.length) onFile(files);
        }}
      />
      {error ? (
        <p className="mt-4 text-sm text-rose-700" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
function StringRows({
  label,
  values,
  onChange,
  addLabel = 'Добавить пункт',
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  addLabel?: string;
}) {
  return (
    <div>
      <p className="field-label mb-3">{label}</p>
      <div className="space-y-2">
        {values.map((value, index) => (
          <div key={index} className="flex items-start gap-2">
            <span className="mt-3 w-5 shrink-0 text-right text-xs text-muted-foreground">
              {index + 1}
            </span>
            <Textarea
              aria-label={`${label}, пункт ${index + 1}`}
              className="min-h-12 flex-1"
              value={value}
              onChange={(event) =>
                onChange(
                  values.map((item, row) =>
                    row === index ? event.target.value : item,
                  ),
                )
              }
            />
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label={`Удалить пункт ${index + 1}`}
              className="mt-1 shrink-0"
              onClick={() => onChange(values.filter((_, row) => row !== index))}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        ))}
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-3"
        onClick={() => onChange([...values, ''])}
      >
        <Plus data-icon="inline-start" />
        {addLabel}
      </Button>
    </div>
  );
}
function VacancyEditor({
  value,
  onChange,
}: {
  value: VacancyFields;
  onChange: (value: VacancyFields) => void;
}) {
  return (
    <div className="space-y-5">
      <label className="field-label" htmlFor="vacancy-title">
        Название вакансии
        <Input
          id="vacancy-title"
          aria-label="Название вакансии"
          className="mt-2"
          value={value.title}
          required
          onChange={(event) =>
            onChange({ ...value, title: event.target.value })
          }
        />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="field-label" htmlFor="vacancy-role">
          Роль
          <Input
            id="vacancy-role"
            aria-label="Роль"
            className="mt-2"
            value={value.role}
            required
            onChange={(event) =>
              onChange({ ...value, role: event.target.value })
            }
          />
        </label>
        <label className="field-label" htmlFor="vacancy-level">
          Уровень / грейд
          <Input
            id="vacancy-level"
            aria-label="Уровень / грейд"
            className="mt-2"
            value={value.level}
            required
            onChange={(event) =>
              onChange({ ...value, level: event.target.value })
            }
          />
        </label>
      </div>
      <label className="field-label" htmlFor="vacancy-description">
        Описание вакансии
        <Textarea
          id="vacancy-description"
          aria-label="Описание вакансии"
          className="mt-2 min-h-40"
          value={value.description}
          required
          onChange={(event) =>
            onChange({ ...value, description: event.target.value })
          }
        />
      </label>
      <StringRows
        label="Требования к кандидату"
        values={value.requirements}
        onChange={(requirements) => onChange({ ...value, requirements })}
        addLabel="Добавить требование"
      />
    </div>
  );
}
function validVacancy(value: VacancyFields | null) {
  return Boolean(
    value?.title.trim() &&
    value.role.trim() &&
    value.level.trim() &&
    value.description.trim() &&
    value.requirements.some((item) => item.trim()),
  );
}
function cleanVacancy<T extends VacancyFields>(value: T): T {
  return {
    ...value,
    title: value.title.trim(),
    role: value.role.trim(),
    level: value.level.trim(),
    description: value.description.trim(),
    requirements: value.requirements.map((item) => item.trim()).filter(Boolean),
  };
}
function QuestionsEditor({
  questions,
  onChange,
  personalized = false,
  maxQuestions = 20,
}: {
  questions: EditableQuestion[];
  onChange: (questions: EditableQuestion[]) => void;
  personalized?: boolean;
  maxQuestions?: number;
}) {
  const prefix = personalized ? 'Персонализированный вопрос' : 'Вопрос';
  return (
    <div className="space-y-3">
      {questions.map((question, index) => (
        <div key={index} className="rounded-2xl border bg-background p-4">
          <div className="flex items-start gap-3">
            <span className="mt-2 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <Textarea
                aria-label={`${prefix} ${index + 1}`}
                className="min-h-20"
                value={question.text}
                minLength={3}
                maxLength={4000}
                required
                onChange={(event) =>
                  onChange(
                    questions.map((item, row) =>
                      row === index
                        ? { ...item, text: event.target.value }
                        : item,
                    ),
                  )
                }
              />
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label
                  className="text-xs text-muted-foreground"
                  htmlFor={`question-topic-${index}`}
                >
                  Тема
                  <Input
                    id={`question-topic-${index}`}
                    aria-label={`Тема вопроса ${index + 1}`}
                    className="mt-1"
                    value={question.topic || ''}
                    maxLength={240}
                    onChange={(event) =>
                      onChange(
                        questions.map((item, row) =>
                          row === index
                            ? { ...item, topic: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                </label>
                <label
                  className="text-xs text-muted-foreground"
                  htmlFor={`question-competency-${index}`}
                >
                  Что проверяем
                  <Input
                    id={`question-competency-${index}`}
                    aria-label={`Критерий вопроса ${index + 1}`}
                    className="mt-1"
                    value={question.competency || ''}
                    maxLength={240}
                    onChange={(event) =>
                      onChange(
                        questions.map((item, row) =>
                          row === index
                            ? { ...item, competency: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                </label>
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Удалить вопрос ${index + 1}`}
              onClick={() =>
                onChange(questions.filter((_, row) => row !== index))
              }
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </div>
      ))}
      {!questions.length ? (
        <p className="py-3 text-sm text-muted-foreground">
          {personalized
            ? 'Добавьте персонализированный вопрос по опыту кандидата.'
            : 'Добавьте первый вопрос.'}
        </p>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={questions.length >= maxQuestions}
        onClick={() =>
          onChange([...questions, { text: '', topic: '', competency: '' }])
        }
      >
        <Plus data-icon="inline-start" />
        Добавить вопрос
      </Button>
    </div>
  );
}
function dateLabel(value: string) {
  return new Date(value).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
  });
}
function candidateStatus(candidate: CandidateSummary) {
  if (candidate.hiringDecision === 'rejected')
    return ['Отказ', 'bg-rose-50 text-rose-700'];
  if (candidate.hiringDecision === 'next_stage')
    return ['Следующий этап', 'bg-emerald-50 text-emerald-700'];
  if (
    candidate.processingStatus === 'ready' ||
    candidate.processingStatus === 'completed'
  )
    return ['Нужно решение', 'bg-amber-50 text-amber-800'];
  if (candidate.processingStatus === 'invited')
    return ['Приглашён', 'bg-blue-50 text-blue-700'];
  if (candidate.processingStatus === 'in_progress')
    return ['Проходит интервью', 'bg-blue-50 text-blue-700'];
  if (
    candidate.processingStatus === 'questions_draft' ||
    candidate.processingStatus === 'not_started'
  )
    return ['Черновик', 'bg-violet-50 text-violet-700'];
  if (candidate.processingStatus === 'error')
    return ['Ошибка обработки', 'bg-rose-50 text-rose-700'];
  return ['Обрабатывается', 'bg-violet-50 text-violet-700'];
}
function CandidateRows({
  candidates,
  onOpen,
  onDeleted,
  global = false,
}: {
  candidates: CandidateSummary[];
  onOpen: (candidate: CandidateSummary) => void;
  onDeleted: (candidate: CandidateSummary) => void;
  global?: boolean;
}) {
  return (
    <div className="p-2 sm:p-3">
      {candidates.map((candidate) => {
        const [label, color] = candidateStatus(candidate);
        return (
          <div key={candidate.id} className="flex items-center gap-2">
            <button
              className="candidate-row min-w-0 flex-1 flex-wrap text-left"
              onClick={() => onOpen(candidate)}
            >
              <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
                {candidate.name
                  .split(/\s+/)
                  .slice(0, 2)
                  .map((name) => name[0])
                  .join('')}
              </span>
              <span className="min-w-[140px] flex-1">
                <span className="block text-sm font-semibold">
                  {candidate.name}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {candidate.role}
                </span>
              </span>
              {global ? (
                <span className="min-w-[180px] flex-1">
                  <span className="block text-sm">
                    {candidate.vacancyTitle || 'Вакансия'}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {candidate.interviewName || 'Интервью'}
                  </span>
                </span>
              ) : null}
              <Badge className={color}>{label}</Badge>
              <ChevronRight
                className="size-4 text-muted-foreground"
                aria-hidden="true"
              />
            </button>
            <DeleteResourceButton
              compact
              kind="candidate"
              id={candidate.id}
              name={candidate.name}
              onDeleted={() => onDeleted(candidate)}
            />
          </div>
        );
      })}
    </div>
  );
}

function VacanciesPage({ navigate }: { navigate: (view: View) => void }) {
  const resource = useResource(
    useCallback((signal: AbortSignal) => api.listVacancies(signal), []),
  );
  return (
    <>
      <Heading
        eyebrow="Рабочее пространство HR"
        title="Вакансии"
        description="Создавайте вакансии, настраивайте интервью и знакомьтесь с кандидатами."
        action={
          <Button
            size="lg"
            onClick={() => navigate({ type: 'create-vacancy' })}
          >
            <Plus data-icon="inline-start" />
            Создать вакансию
          </Button>
        }
      />
      {resource.loading ? (
        <Busy />
      ) : resource.error ? (
        <ErrorPanel message={resource.error} retry={resource.reload} />
      ) : (
        <section className="surface-card">
          {resource.data?.length ? (
            <div className="p-2 sm:p-3">
              {resource.data.map((vacancy) => (
                <button
                  key={vacancy.id}
                  className="candidate-row w-full flex-wrap text-left"
                  onClick={() =>
                    navigate({ type: 'vacancy', vacancyId: vacancy.id })
                  }
                >
                  <span className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                    <BriefcaseBusiness className="size-5" />
                  </span>
                  <span className="min-w-[160px] flex-1">
                    <span className="block font-semibold">{vacancy.title}</span>
                    <span className="mt-1 block text-sm text-muted-foreground">
                      {vacancy.role} · {vacancy.level}
                    </span>
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Интервью: {vacancy.interviewCount} · Кандидатов:{' '}
                    {vacancy.candidateCount}
                  </span>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </button>
              ))}
            </div>
          ) : (
            <Empty
              icon={<BriefcaseBusiness />}
              title="Пока нет вакансий"
              description="Загрузите описание или начните с готового IT-шаблона."
              action={
                <Button onClick={() => navigate({ type: 'create-vacancy' })}>
                  Создать первую вакансию
                </Button>
              }
            />
          )}
        </section>
      )}
    </>
  );
}

function CompanyContextPage({ notify }: { notify: Notify }) {
  const resource = useResource(
    useCallback((signal: AbortSignal) => api.listCompanyContext(signal), []),
  );
  const [uploads, setUploads] = useState<
    {
      filename: string;
      state: 'pending' | 'processing' | 'ready' | 'error';
      error?: string;
    }[]
  >([]);
  const [uploading, setUploading] = useState(false);
  const upload = async (files: File[]) => {
    setUploading(true);
    setUploads(
      files.map((file) => ({ filename: file.name, state: 'pending' })),
    );
    for (let index = 0; index < files.length; index++) {
      setUploads((rows) =>
        rows.map((row, i) =>
          i === index ? { ...row, state: 'processing' } : row,
        ),
      );
      try {
        const document = await api.uploadCompanyContext(files[index]);
        resource.setData((items) => [...(items || []), document]);
        setUploads((rows) =>
          rows.map((row, i) =>
            i === index ? { ...row, state: 'ready' } : row,
          ),
        );
      } catch (error) {
        setUploads((rows) =>
          rows.map((row, i) =>
            i === index
              ? { ...row, state: 'error', error: errorText(error) }
              : row,
          ),
        );
      }
    }
    setUploading(false);
    notify('Обработка документов завершена');
  };
  return (
    <>
      <Heading
        eyebrow="Компания"
        title="Общий контекст"
        description="Карты грейдов, компетенции и принципы компании. Они учитываются в вакансиях, шаблонах и вопросах интервью."
      />
      <section className="surface-card p-5 sm:p-6">
        <FilePicker
          label="Загрузить документы"
          multiple
          disabled={uploading}
          onFile={(files) => void upload(files)}
        />
        <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
          После загрузки AI подготовит текстовое представление документа и
          адаптирует шаблоны вакансий и интервью под компанию.
        </p>
      </section>
      {uploads.length ? (
        <section className="surface-card mt-5 divide-y px-5" aria-live="polite">
          {uploads.map((upload, index) => (
            <div key={index} className="flex items-start gap-3 py-4">
              {upload.state === 'ready' ? (
                <Check className="mt-0.5 size-4 text-emerald-600" />
              ) : upload.state === 'error' ? (
                <FileText className="mt-0.5 size-4 text-rose-600" />
              ) : (
                <LoaderCircle
                  className={`mt-0.5 size-4 text-primary ${upload.state === 'processing' ? 'animate-spin' : ''}`}
                />
              )}
              <div className="min-w-0">
                <p className="break-words text-sm font-medium">
                  {upload.filename}
                </p>
                <p
                  className={`mt-1 text-xs ${upload.state === 'error' ? 'text-rose-700' : 'text-muted-foreground'}`}
                >
                  {upload.state === 'ready'
                    ? 'Контекст сохранён, шаблоны обновлены'
                    : upload.state === 'processing'
                      ? 'Обрабатываем документ и адаптируем шаблоны…'
                      : upload.state === 'pending'
                        ? 'Ожидает обработки'
                        : upload.error}
                </p>
              </div>
            </div>
          ))}
        </section>
      ) : null}
      <div className="mb-4 mt-8 flex items-center gap-3">
        <h2 className="text-lg font-semibold">Документы компании</h2>
        <Badge variant="secondary">{resource.data?.length || 0}</Badge>
      </div>
      {resource.loading ? (
        <Busy />
      ) : resource.error ? (
        <ErrorPanel message={resource.error} retry={resource.reload} />
      ) : resource.data?.length ? (
        <div className="space-y-3">
          {resource.data.map((document: ContextDocument) => (
            <details key={document.id} className="surface-card group p-5">
              <summary className="flex cursor-pointer list-none items-center gap-3">
                <FileText className="size-5 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 break-words text-sm font-semibold">
                  {document.filename}
                </span>
                <Badge className="bg-emerald-50 text-emerald-700">Готов</Badge>
                <span className="hidden text-xs text-muted-foreground sm:block">
                  {dateLabel(document.createdAt)}
                </span>
                <ChevronRight className="size-4 transition-transform group-open:rotate-90" />
              </summary>
              <div className="mt-5 border-t pt-5">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Текстовое представление
                </h3>
                <p className="max-h-[480px] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed">
                  {document.text}
                </p>
              </div>
            </details>
          ))}
        </div>
      ) : (
        <section className="surface-card">
          <Empty
            icon={<BookOpen />}
            title="Добавьте контекст компании"
            description="Например, карту грейдов или описание компетенций. Новые документы дополнят общий контекст."
          />
        </section>
      )}
    </>
  );
}

function VacancyTemplatesPage({
  navigate,
  notify,
}: {
  navigate: (view: View) => void;
  notify: Notify;
}) {
  const resource = useResource(
    useCallback((signal: AbortSignal) => api.listVacancyTemplates(signal), []),
  );
  const [role, setRole] = useState('');
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<VacancyTemplate | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const items = resource.data || [];
  const filtered = items.filter(
    (item) =>
      (!role || item.role === role) &&
      (!level || item.level === level) &&
      `${item.title} ${item.description}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const save = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError('');
    try {
      const updated = await api.updateVacancyTemplate(
        editing.id,
        cleanVacancy(editing),
      );
      resource.setData(
        (data) =>
          data?.map((item) => (item.id === updated.id ? updated : item)) || [],
      );
      setEditing(null);
      notify('Шаблон вакансии сохранён');
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <Heading
        eyebrow="Библиотека компании"
        title="Шаблоны вакансий"
        description="Общие IT-шаблоны для разных ролей и грейдов. Документы компании помогают адаптировать их под вашу команду."
      />
      <div className="surface-card mb-5 grid gap-4 p-5 sm:grid-cols-3">
        <label className="field-label" htmlFor="template-search">
          Поиск
          <Input
            id="template-search"
            aria-label="Поиск шаблонов"
            className="mt-2"
            placeholder="Название или описание"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <SelectField
          label="Роль"
          value={role}
          onChange={setRole}
          placeholder="Все роли"
          options={Array.from(new Set(items.map((item) => item.role))).map(
            (value) => ({ value, label: value }),
          )}
        />
        <SelectField
          label="Грейд"
          value={level}
          onChange={setLevel}
          placeholder="Все грейды"
          options={Array.from(new Set(items.map((item) => item.level))).map(
            (value) => ({ value, label: value }),
          )}
        />
      </div>
      {resource.loading ? (
        <Busy />
      ) : resource.error ? (
        <ErrorPanel message={resource.error} retry={resource.reload} />
      ) : filtered.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {filtered.map((template) => (
            <article
              className="surface-card flex flex-col p-6"
              key={template.id}
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{template.level}</Badge>
                <span className="text-xs text-muted-foreground">
                  {template.role}
                </span>
                {template.adapted ? (
                  <span className="ml-auto flex items-center gap-1 text-xs text-primary">
                    <Sparkles className="size-3" />
                    Для компании
                  </span>
                ) : null}
              </div>
              <h2 className="mt-4 text-lg font-semibold">{template.title}</h2>
              <p className="mb-6 mt-3 line-clamp-3 text-sm leading-relaxed text-muted-foreground">
                {template.description}
              </p>
              <div className="mt-auto flex flex-wrap gap-2">
                <Button
                  onClick={() =>
                    navigate({
                      type: 'create-vacancy',
                      templateId: template.id,
                    })
                  }
                >
                  Создать вакансию
                  <ArrowUpRight data-icon="inline-end" />
                </Button>
                <Button
                  variant="outline"
                  aria-label={`Редактировать шаблон ${template.title}`}
                  onClick={() => {
                    setEditing(template);
                    setError('');
                  }}
                >
                  <Pencil data-icon="inline-start" />
                  Редактировать
                </Button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <section className="surface-card">
          <Empty
            icon={<Search />}
            title="Шаблоны не найдены"
            description="Попробуйте выбрать другую роль или грейд."
          />
        </section>
      )}
      <Dialog
        open={Boolean(editing)}
        onOpenChange={(open) => {
          if (!saving && !open) setEditing(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Редактировать шаблон вакансии</DialogTitle>
            <DialogDescription>
              Изменения будут доступны для новых вакансий компании.
            </DialogDescription>
          </DialogHeader>
          {editing ? (
            <form
              id="vacancy-template-form"
              className="space-y-5"
              onSubmit={save}
            >
              <VacancyEditor
                value={editing}
                onChange={(fields) => setEditing({ ...editing, ...fields })}
              />
              <ErrorMessage message={error} />
            </form>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => setEditing(null)}
            >
              Отмена
            </Button>
            <Button
              type="submit"
              form="vacancy-template-form"
              disabled={saving || !validVacancy(editing)}
            >
              {saving ? 'Сохраняем…' : 'Сохранить шаблон'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function InterviewTemplatesPage({ notify }: { notify: Notify }) {
  const resource = useResource(
    useCallback(
      (signal: AbortSignal) => api.listInterviewTemplates(signal),
      [],
    ),
  );
  const [editing, setEditing] = useState<InterviewTemplate | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const save = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError('');
    try {
      const updated = await api.updateInterviewTemplate(editing.id, {
        name: editing.name.trim(),
        description: editing.description.trim(),
        evaluates: editing.evaluates.map((item) => item.trim()).filter(Boolean),
      });
      resource.setData(
        (items) =>
          items?.map((item) => (item.id === updated.id ? updated : item)) || [],
      );
      setEditing(null);
      notify('Шаблон интервью сохранён');
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <Heading
        eyebrow="Библиотека компании"
        title="Шаблоны интервью"
        description="Название, описание и критерии задаются здесь и применяются при создании интервью для вакансий."
      />
      {resource.loading ? (
        <Busy />
      ) : resource.error ? (
        <ErrorPanel message={resource.error} retry={resource.reload} />
      ) : (
        <div className="space-y-5">
          {resource.data?.map((template) => (
            <article key={template.id} className="surface-card p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-3 flex items-center gap-2 text-primary">
                    <MessageSquare className="size-5" />
                    {template.adapted ? (
                      <span className="text-xs font-medium">
                        Адаптирован для компании
                      </span>
                    ) : null}
                  </div>
                  <h2 className="text-xl font-semibold">{template.name}</h2>
                </div>
                <Button
                  variant="outline"
                  onClick={() => {
                    setEditing(template);
                    setError('');
                  }}
                >
                  <Pencil data-icon="inline-start" />
                  Редактировать
                </Button>
              </div>
              <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                {template.description}
              </p>
              <h3 className="mb-3 mt-6 text-sm font-semibold">
                Что проверяется
              </h3>
              <ul className="grid gap-3 sm:grid-cols-2">
                {template.evaluates.map((item, index) => (
                  <li key={index} className="flex gap-2 text-sm">
                    <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                    {item}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
      <Dialog
        open={Boolean(editing)}
        onOpenChange={(open) => {
          if (!saving && !open) setEditing(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Редактировать шаблон интервью</DialogTitle>
            <DialogDescription>
              Эти настройки общие для компании. Новые интервью будут
              использовать обновлённый шаблон.
            </DialogDescription>
          </DialogHeader>
          {editing ? (
            <form
              id="interview-template-form"
              className="space-y-5"
              onSubmit={save}
            >
              <label className="field-label" htmlFor="interview-template-name">
                Название интервью
                <Input
                  id="interview-template-name"
                  aria-label="Название интервью"
                  className="mt-2"
                  value={editing.name}
                  required
                  onChange={(event) =>
                    setEditing({ ...editing, name: event.target.value })
                  }
                />
              </label>
              <label
                className="field-label"
                htmlFor="interview-template-description"
              >
                Описание интервью
                <Textarea
                  id="interview-template-description"
                  aria-label="Описание интервью"
                  className="mt-2 min-h-32"
                  value={editing.description}
                  required
                  onChange={(event) =>
                    setEditing({ ...editing, description: event.target.value })
                  }
                />
              </label>
              <StringRows
                label="Что проверяется"
                values={editing.evaluates}
                onChange={(evaluates) => setEditing({ ...editing, evaluates })}
              />
              <ErrorMessage message={error} />
            </form>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => setEditing(null)}
            >
              Отмена
            </Button>
            <Button
              type="submit"
              form="interview-template-form"
              disabled={
                saving ||
                !editing?.name.trim() ||
                !editing.description.trim() ||
                !editing.evaluates.some((item) => item.trim())
              }
            >
              {saving ? 'Сохраняем…' : 'Сохранить шаблон'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function CreateVacancyPage({
  templateId,
  navigate,
  notify,
}: {
  templateId?: string;
  navigate: (view: View) => void;
  notify: Notify;
}) {
  const [mode, setMode] = useState<'upload' | 'template'>(
    templateId ? 'template' : 'upload',
  );
  const [role, setRole] = useState('');
  const [level, setLevel] = useState('');
  const [draft, setDraft] = useState<VacancyDraft | null>(null);
  const [fileName, setFileName] = useState('');
  const [processing, setProcessing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const templates = useResource(
    useCallback(
      async (signal: AbortSignal) => {
        const items = await api.listVacancyTemplates(signal);
        const template = items.find((item) => item.id === templateId);
        if (template && !signal.aborted) {
          setRole(template.role);
          setLevel(template.level);
          setDraft({ ...template, templateId: template.id });
        }
        return items;
      },
      [templateId],
    ),
  );
  const setTemplate = (nextRole: string, nextLevel: string) => {
    setRole(nextRole);
    setLevel(nextLevel);
    const selected = templates.data?.find(
      (item) => item.role === nextRole && item.level === nextLevel,
    );
    setDraft(
      selected && nextRole && nextLevel
        ? { ...selected, templateId: selected.id }
        : null,
    );
    setError('');
  };
  const changeMode = (next: 'upload' | 'template') => {
    if (next === mode) return;
    controller.current?.abort();
    setMode(next);
    setDraft(null);
    setRole('');
    setLevel('');
    setProcessing(false);
    setError('');
    setFileName('');
  };
  const parse = async (file: File) => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setProcessing(true);
    setError('');
    setDraft(null);
    setFileName(file.name);
    try {
      const result = await api.parseVacancy(file, request.signal);
      if (!request.signal.aborted) setDraft(result);
    } catch (caught) {
      if (!request.signal.aborted) setError(errorText(caught));
    } finally {
      if (!request.signal.aborted) setProcessing(false);
    }
  };
  const create = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft || saving) return;
    setSaving(true);
    setError('');
    try {
      const vacancy = await api.createVacancy(cleanVacancy(draft));
      notify(`Вакансия «${vacancy.title}» создана`);
      navigate({
        type: 'create-interview',
        vacancyId: vacancy.id,
        canSkip: true,
      });
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };
  const all = templates.data || [];
  return (
    <div className="mx-auto max-w-[900px]">
      <Back onClick={() => navigate({ type: 'vacancies' })} />
      <Heading eyebrow="Новая вакансия" title="Создание вакансии" />
      <div
        role="tablist"
        aria-label="Способ создания вакансии"
        className="mb-6 grid grid-cols-2 rounded-2xl bg-muted p-1.5"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'upload'}
          className={`flex min-h-11 items-center justify-center gap-2 rounded-xl px-3 text-sm font-semibold transition ${mode === 'upload' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
          onClick={() => changeMode('upload')}
        >
          <Upload className="size-4" />
          Загрузить
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'template'}
          className={`flex min-h-11 items-center justify-center gap-2 rounded-xl px-3 text-sm font-semibold transition ${mode === 'template' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
          onClick={() => changeMode('template')}
        >
          <Layers3 className="size-4" />
          Создать из шаблона
        </button>
      </div>
      {mode === 'upload' && !draft && !processing ? (
        <section className="surface-card p-5 sm:p-6">
          <FilePicker
            label="Загрузить файл вакансии"
            onFile={(files) => void parse(files[0])}
          />
        </section>
      ) : null}
      {mode === 'template' ? (
        templates.loading ? (
          <Busy title="Загружаем шаблоны…" />
        ) : templates.error ? (
          <ErrorPanel message={templates.error} retry={templates.reload} />
        ) : (
          <section className="surface-card mb-5 grid gap-5 p-6 sm:grid-cols-2">
            <SelectField
              label="Роль"
              value={role}
              onChange={(value) => setTemplate(value, level)}
              options={Array.from(new Set(all.map((item) => item.role))).map(
                (value) => ({ value, label: value }),
              )}
              placeholder="Выберите роль"
            />
            <SelectField
              label="Грейд"
              value={level}
              onChange={(value) => setTemplate(role, value)}
              options={Array.from(
                new Set(
                  all
                    .filter((item) => !role || item.role === role)
                    .map((item) => item.level),
                ),
              ).map((value) => ({ value, label: value }))}
              placeholder="Выберите грейд"
            />
            {role && level && !draft ? (
              <p className="text-sm text-muted-foreground sm:col-span-2">
                Для этой роли и грейда шаблон пока не найден.
              </p>
            ) : null}
          </section>
        )
      ) : null}
      {processing ? (
        <Busy
          title="Готовим вакансию"
          description={`Читаем ${fileName}, учитываем общий контекст компании и выделяем требования к кандидату.`}
        />
      ) : null}
      {draft ? (
        <form className="space-y-5" onSubmit={create}>
          <section className="surface-card p-5 sm:p-6">
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-primary">
                <Sparkles className="size-4" />
                {mode === 'upload'
                  ? 'Описание готово к проверке'
                  : 'Шаблон выбран'}
              </div>
              {mode === 'upload' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  onClick={() => {
                    setDraft(null);
                    setFileName('');
                  }}
                >
                  Другой файл
                </Button>
              ) : null}
            </div>
            <VacancyEditor
              value={draft}
              onChange={(fields) => setDraft({ ...draft, ...fields })}
            />
          </section>
          <ErrorMessage message={error} />
          <div className="sticky-form-actions">
            <Button
              type="button"
              variant="ghost"
              disabled={saving}
              onClick={() => navigate({ type: 'vacancies' })}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={saving || !validVacancy(draft)}>
              {saving ? (
                <LoaderCircle
                  className="animate-spin"
                  data-icon="inline-start"
                />
              ) : null}
              {saving ? 'Создаём…' : 'Создать вакансию'}
            </Button>
          </div>
        </form>
      ) : error ? (
        <div className="mt-4">
          <ErrorMessage message={error} />
        </div>
      ) : null}
    </div>
  );
}

function VacancyOverview({
  vacancyId,
  navigate,
  notify,
}: {
  vacancyId: string;
  navigate: (view: View) => void;
  notify: Notify;
}) {
  const resource = useResource(
    useCallback(
      (signal: AbortSignal) => api.getVacancy(vacancyId, signal),
      [vacancyId],
    ),
  );
  const [editing, setEditing] = useState<VacancyFields | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const save = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError('');
    try {
      const updated = await api.updateVacancy(vacancyId, cleanVacancy(editing));
      resource.setData(updated);
      setEditing(null);
      notify('Вакансия обновлена');
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };
  if (resource.loading) return <Busy title="Открываем вакансию…" />;
  if (resource.error || !resource.data)
    return (
      <ErrorPanel
        message={resource.error || 'Вакансия не найдена'}
        retry={resource.reload}
      />
    );
  const vacancy: VacancyDetail = resource.data;
  return (
    <>
      <Back onClick={() => navigate({ type: 'vacancies' })} />
      <Heading
        eyebrow="Вакансия"
        title={vacancy.title}
        description={`${vacancy.role} · ${vacancy.level}`}
        action={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setEditing(vacancy);
                setError('');
              }}
            >
              <Pencil data-icon="inline-start" />
              Редактировать
            </Button>
            <DeleteResourceButton
              kind="vacancy"
              id={vacancy.id}
              name={vacancy.title}
              interviewCount={vacancy.interviewCount}
              candidateCount={vacancy.candidateCount}
              onDeleted={() => {
                notify('Вакансия удалена');
                navigate({ type: 'vacancies' });
              }}
            />
          </div>
        }
      />
      <section className="surface-card p-6 sm:p-7">
        <div className="grid gap-7 lg:grid-cols-2">
          <div>
            <h2 className="mb-4 text-base font-semibold">Описание вакансии</h2>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
              {vacancy.description}
            </p>
          </div>
          <div>
            <h2 className="mb-4 text-base font-semibold">
              Требования к кандидату
            </h2>
            <ul className="space-y-3">
              {vacancy.requirements.map((requirement, index) => (
                <li
                  className="flex gap-2 text-sm leading-relaxed text-muted-foreground"
                  key={index}
                >
                  <Check className="mt-1 size-4 shrink-0 text-primary" />
                  {requirement}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
      <section className="surface-card mt-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5 sm:p-6">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold">Интервью</h2>
            <Badge variant="secondary">{vacancy.interviews.length}</Badge>
          </div>
          <Button
            onClick={() => navigate({ type: 'create-interview', vacancyId })}
          >
            <Plus data-icon="inline-start" />
            Добавить интервью
          </Button>
        </div>
        {vacancy.interviews.length ? (
          <div className="p-3">
            {vacancy.interviews.map((interview: InterviewPlan) => (
              <button
                key={interview.id}
                className="candidate-row w-full flex-wrap text-left"
                onClick={() =>
                  navigate({
                    type: 'interview',
                    interviewId: interview.id,
                    vacancyId,
                  })
                }
              >
                <span className="flex size-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                  <MessageSquare className="size-5" />
                </span>
                <span className="min-w-[180px] flex-1">
                  <span className="block text-sm font-semibold">
                    {interview.name}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {interview.questions.length} общих вопросов ·{' '}
                    {interview.durationMinutes} минут
                  </span>
                </span>
                <span className="text-xs text-muted-foreground">
                  Кандидатов: {interview.candidateCount}
                </span>
                <ChevronRight className="size-4 text-muted-foreground" />
              </button>
            ))}
          </div>
        ) : (
          <Empty
            icon={<MessageSquare />}
            title="Добавьте первое интервью"
            description="Выберите шаблон, проверьте вопросы и настройте длительность."
          />
        )}
      </section>
      <Dialog
        open={Boolean(editing)}
        onOpenChange={(open) => {
          if (!open && !saving) setEditing(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Редактировать вакансию</DialogTitle>
            <DialogDescription>
              Обновлённое описание будет учитываться при подготовке новых
              интервью.
            </DialogDescription>
          </DialogHeader>
          {editing ? (
            <form id="edit-vacancy-form" onSubmit={save} className="space-y-4">
              <VacancyEditor value={editing} onChange={setEditing} />
              <ErrorMessage message={error} />
            </form>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => setEditing(null)}
            >
              Отмена
            </Button>
            <Button
              type="submit"
              form="edit-vacancy-form"
              disabled={saving || !validVacancy(editing)}
            >
              {saving ? 'Сохраняем…' : 'Сохранить изменения'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function TemplateSummary({
  template,
}: {
  template: Pick<InterviewTemplate, 'name' | 'description' | 'evaluates'>;
}) {
  return (
    <div>
      <h2 className="text-lg font-semibold">{template.name}</h2>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
        {template.description}
      </p>
      <h3 className="mb-3 mt-5 text-sm font-semibold">Что проверяется</h3>
      <ul className="grid gap-3 sm:grid-cols-2">
        {template.evaluates.map((item, index) => (
          <li key={index} className="flex gap-2 text-sm">
            <Check className="mt-0.5 size-4 shrink-0 text-primary" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
function CreateInterviewPage({
  vacancyId,
  canSkip,
  navigate,
  notify,
}: {
  vacancyId: string;
  canSkip?: boolean;
  navigate: (view: View) => void;
  notify: Notify;
}) {
  const templates = useResource(
    useCallback(
      (signal: AbortSignal) => api.listInterviewTemplates(signal),
      [],
    ),
  );
  const [templateId, setTemplateId] = useState('');
  const [draft, setDraft] = useState<InterviewPlanDraft | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const selected = templates.data?.find(
    (template) => template.id === templateId,
  );
  const prepare = async (id: string) => {
    controller.current?.abort();
    setTemplateId(id);
    setDraft(null);
    setError('');
    if (!id) {
      setPreparing(false);
      return;
    }
    const request = new AbortController();
    controller.current = request;
    setPreparing(true);
    try {
      const generated = await api.prepareInterview(
        vacancyId,
        id,
        request.signal,
      );
      if (!request.signal.aborted) setDraft(generated);
    } catch (caught) {
      if (!request.signal.aborted) setError(errorText(caught));
    } finally {
      if (!request.signal.aborted) setPreparing(false);
    }
  };
  const create = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft) return;
    setSaving(true);
    setError('');
    try {
      const interview = await api.createInterviewPlan(vacancyId, {
        ...draft,
        questions: draft.questions
          .map((question) => ({ ...question, text: question.text.trim() }))
          .filter((question) => question.text),
      });
      notify('Интервью создано');
      navigate({ type: 'interview', interviewId: interview.id, vacancyId });
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="mx-auto max-w-[940px]">
      <Back
        label="К вакансии"
        onClick={() => navigate({ type: 'vacancy', vacancyId })}
      />
      <Heading
        eyebrow={canSkip ? 'Вакансия создана' : 'Новое интервью'}
        title="Добавление интервью"
        description="Выберите тип интервью. AI подготовит вопросы с учётом вакансии и общего контекста компании."
        action={
          canSkip ? (
            <Button
              variant="outline"
              onClick={() => navigate({ type: 'vacancy', vacancyId })}
            >
              Пропустить пока
              <ArrowUpRight data-icon="inline-end" />
            </Button>
          ) : null
        }
      />
      {templates.loading ? (
        <Busy title="Загружаем типы интервью…" />
      ) : templates.error ? (
        <ErrorPanel message={templates.error} retry={templates.reload} />
      ) : (
        <section className="surface-card mb-5 p-6">
          <SelectField
            label="Тип интервью"
            value={templateId}
            onChange={(id) => void prepare(id)}
            disabled={saving}
            placeholder="Выберите тип интервью"
            options={(templates.data || []).map((template) => ({
              value: template.id,
              label: template.name,
            }))}
          />
          {selected ? (
            <div className="mt-6 border-t pt-6">
              <TemplateSummary template={selected} />
              <p className="mt-5 text-xs text-muted-foreground">
                Название, описание и критерии редактируются в разделе «Шаблоны
                интервью».
              </p>
            </div>
          ) : null}
        </section>
      )}
      {preparing ? (
        <Busy
          title="Готовим вопросы и настройки интервью"
          description="Составляем общий пул вопросов по вакансии, критериям интервью и документам компании."
        />
      ) : null}
      {draft ? (
        <form onSubmit={create} className="space-y-5">
          <section className="surface-card p-5 sm:p-6">
            <div className="mb-5">
              <h2 className="text-lg font-semibold">
                Общий пул вопросов{' '}
                <span className="ml-2 text-muted-foreground">
                  {draft.questions.length}
                </span>
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Эти вопросы получат все кандидаты этого интервью. Каждый пункт
                можно отредактировать.
              </p>
            </div>
            <QuestionsEditor
              questions={draft.questions}
              onChange={(questions) => setDraft({ ...draft, questions })}
            />
          </section>
          <section className="surface-card p-5 sm:p-6">
            <h2 className="mb-5 text-lg font-semibold">Настройки интервью</h2>
            <div className="grid gap-5 sm:grid-cols-3">
              <label className="field-label" htmlFor="max-followups">
                Максимум уточняющих вопросов
                <Input
                  id="max-followups"
                  aria-label="Максимум уточняющих вопросов"
                  className="mt-2"
                  type="number"
                  min={0}
                  max={10}
                  value={draft.maxFollowUpQuestions}
                  required
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      maxFollowUpQuestions: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label className="field-label" htmlFor="max-personalized">
                Максимум персонализированных вопросов
                <Input
                  id="max-personalized"
                  aria-label="Максимум персонализированных вопросов"
                  className="mt-2"
                  type="number"
                  min={0}
                  max={10}
                  value={draft.maxPersonalizedQuestions}
                  required
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      maxPersonalizedQuestions: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label className="field-label" htmlFor="interview-duration">
                Лимит времени, минут
                <Input
                  id="interview-duration"
                  aria-label="Лимит времени, минут"
                  className="mt-2"
                  type="number"
                  min={5}
                  max={120}
                  value={draft.durationMinutes}
                  required
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      durationMinutes: Number(event.target.value),
                    })
                  }
                />
              </label>
            </div>
          </section>
          <ErrorMessage message={error} />
          <div className="sticky-form-actions">
            <Button
              type="button"
              variant="ghost"
              disabled={saving}
              onClick={() => navigate({ type: 'vacancy', vacancyId })}
            >
              Отмена
            </Button>
            <Button
              type="submit"
              disabled={
                saving ||
                !draft.questions.length ||
                draft.questions.some((question) => !question.text.trim())
              }
            >
              {saving ? 'Создаём…' : 'Создать интервью'}
            </Button>
          </div>
        </form>
      ) : error ? (
        <div className="space-y-3">
          <ErrorMessage message={error} />
          <Button variant="outline" onClick={() => void prepare(templateId)}>
            Повторить генерацию
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function AddCandidateDialog({
  open,
  interview,
  onClose,
  onSaved,
  notify,
}: {
  open: boolean;
  interview: InterviewPlanDetail;
  onClose: () => void;
  onSaved: (approval: Approval) => void;
  notify: Notify;
}) {
  const [draft, setDraft] = useState<CandidateDraft | null>(null);
  const [processing, setProcessing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const close = () => {
    if (saving) return;
    controller.current?.abort();
    onClose();
  };
  const prepare = async (file: File) => {
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    setProcessing(true);
    setDraft(null);
    setError('');
    try {
      const result = await api.prepareCandidate(
        interview.id,
        file,
        request.signal,
      );
      if (!request.signal.aborted)
        setDraft({ ...result, email: result.email || '' });
    } catch (caught) {
      if (!request.signal.aborted) setError(errorText(caught));
    } finally {
      if (!request.signal.aborted) setProcessing(false);
    }
  };
  const save = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft) return;
    setSaving(true);
    setError('');
    try {
      const result = await api.savePreparedCandidate(interview.id, {
        ...draft,
        name: draft.name.trim(),
        role: draft.role.trim(),
        questions: draft.questions
          .map((question) => ({ ...question, text: question.text.trim() }))
          .filter((question) => question.text),
      });
      const copied = await copyText(result.inviteUrl);
      notify(
        copied
          ? 'Кандидат добавлен. Ссылка на интервью скопирована'
          : 'Кандидат добавлен. Выделите и скопируйте ссылку над списком кандидатов',
      );
      onSaved(result);
      onClose();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) close();
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Добавить кандидата</DialogTitle>
          <DialogDescription>
            Загрузите резюме. AI подготовит профиль и персонализированные
            вопросы для интервью «{interview.name}».
          </DialogDescription>
        </DialogHeader>
        {processing ? (
          <Busy
            title="Готовим вопросы для кандидата"
            description="Изучаем резюме и сопоставляем опыт с вакансией и общим пулом вопросов."
          />
        ) : !draft ? (
          <FilePicker
            label="Загрузить резюме"
            onFile={(files) => void prepare(files[0])}
          />
        ) : (
          <form
            id="prepared-candidate-form"
            onSubmit={save}
            className="space-y-6"
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <label
                className="field-label sm:col-span-2"
                htmlFor="prepared-candidate-name"
              >
                Имя кандидата
                <Input
                  id="prepared-candidate-name"
                  aria-label="Имя кандидата"
                  className="mt-2"
                  value={draft.name}
                  required
                  onChange={(event) =>
                    setDraft({ ...draft, name: event.target.value })
                  }
                />
              </label>
              <label className="field-label" htmlFor="prepared-candidate-email">
                Email
                <Input
                  id="prepared-candidate-email"
                  aria-label="Email кандидата"
                  type="email"
                  className="mt-2"
                  value={draft.email}
                  onChange={(event) =>
                    setDraft({ ...draft, email: event.target.value })
                  }
                />
              </label>
              <label
                className="field-label"
                htmlFor="prepared-candidate-telegram"
              >
                Telegram
                <Input
                  id="prepared-candidate-telegram"
                  className="mt-2"
                  placeholder="@username"
                  value={draft.telegramUsername || ''}
                  onChange={(event) =>
                    setDraft({ ...draft, telegramUsername: event.target.value })
                  }
                />
                <span className="mt-2 block text-sm font-normal text-muted-foreground">
                  Уведомим кандидата, если он уже запускал нашего бота.
                </span>
              </label>
              <label className="field-label" htmlFor="prepared-candidate-role">
                Текущая роль
                <Input
                  id="prepared-candidate-role"
                  aria-label="Текущая роль кандидата"
                  className="mt-2"
                  value={draft.role}
                  onChange={(event) =>
                    setDraft({ ...draft, role: event.target.value })
                  }
                />
              </label>
            </div>
            <section>
              <h3 className="mb-2 font-semibold">
                Персонализированные вопросы
              </h3>
              <p className="mb-4 text-sm text-muted-foreground">
                Дополнят {interview.questions.length} общих вопросов интервью.
                Максимум — {interview.maxPersonalizedQuestions}.
              </p>
              {interview.maxPersonalizedQuestions > 0 ? (
                <QuestionsEditor
                  personalized
                  maxQuestions={interview.maxPersonalizedQuestions}
                  questions={draft.questions}
                  onChange={(questions) => setDraft({ ...draft, questions })}
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  По настройкам интервью кандидат получит только общий пул
                  вопросов.
                </p>
              )}
              {draft.questions.length > interview.maxPersonalizedQuestions ? (
                <p className="mt-3 text-sm text-rose-700">
                  Уберите лишние вопросы: максимум{' '}
                  {interview.maxPersonalizedQuestions}.
                </p>
              ) : null}
            </section>
          </form>
        )}
        <ErrorMessage message={error} />
        <DialogFooter>
          <Button variant="outline" disabled={saving} onClick={close}>
            Отмена
          </Button>
          {draft ? (
            <Button
              type="submit"
              form="prepared-candidate-form"
              disabled={
                saving ||
                !draft.name.trim() ||
                draft.questions.some((question) => !question.text.trim()) ||
                draft.questions.length > interview.maxPersonalizedQuestions
              }
            >
              {saving ? 'Сохраняем…' : 'Сохранить и скопировать ссылку'}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function InterviewOverview({
  interviewId,
  vacancyId,
  navigate,
  notify,
}: {
  interviewId: string;
  vacancyId: string;
  navigate: (view: View) => void;
  notify: Notify;
}) {
  const resource = useResource(
    useCallback(
      (signal: AbortSignal) => api.getInterviewPlan(interviewId, signal),
      [interviewId],
    ),
  );
  const [addOpen, setAddOpen] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  if (resource.loading && !resource.data)
    return <Busy title="Открываем интервью…" />;
  if (resource.error || !resource.data)
    return (
      <ErrorPanel
        message={resource.error || 'Интервью не найдено'}
        retry={resource.reload}
      />
    );
  const interview = resource.data;
  return (
    <>
      <Back
        label="К вакансии"
        onClick={() => navigate({ type: 'vacancy', vacancyId })}
      />
      <Heading
        eyebrow={interview.vacancy.title}
        title={interview.name}
        description={`${interview.questions.length} общих вопросов · до ${interview.maxPersonalizedQuestions} персонализированных · до ${interview.maxFollowUpQuestions} уточняющих · ${interview.durationMinutes} минут`}
        action={
          <DeleteResourceButton
            kind="interview"
            id={interview.id}
            name={interview.name}
            candidateCount={interview.candidateCount}
            onDeleted={() => {
              notify('Интервью удалено');
              navigate({ type: 'vacancy', vacancyId });
            }}
          />
        }
      />
      <section className="surface-card p-6">
        <TemplateSummary template={interview} />
      </section>
      <section className="surface-card mt-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5 sm:p-6">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold">Кандидаты</h2>
            <Badge variant="secondary">{interview.candidates.length}</Badge>
          </div>
          <Button onClick={() => setAddOpen(true)}>
            <UserPlus data-icon="inline-start" />
            Добавить кандидата
          </Button>
        </div>
        {approval ? (
          <div className="m-4 rounded-2xl border border-emerald-200 bg-emerald-50/50 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-emerald-800">
              <Check className="size-4" />
              Кандидат добавлен — приглашение готово
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Input
                aria-label="Ссылка на интервью кандидата"
                className="min-w-[160px] flex-1 bg-white text-xs"
                readOnly
                value={approval.inviteUrl}
                onFocus={(event) => event.target.select()}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  const copied = await copyText(approval.inviteUrl);
                  notify(
                    copied
                      ? 'Ссылка скопирована'
                      : 'Выделите и скопируйте ссылку из поля',
                  );
                }}
              >
                <Clipboard data-icon="inline-start" />
                Скопировать
              </Button>
            </div>
          </div>
        ) : null}
        {interview.candidates.length ? (
          <CandidateRows
            candidates={interview.candidates}
            onDeleted={(candidate) => {
              if (approval?.candidateId === candidate.id) setApproval(null);
              notify('Кандидат удалён');
              resource.reload();
            }}
            onOpen={(candidate) =>
              navigate({
                type: 'candidate',
                candidateId: candidate.id,
                interviewId,
                vacancyId,
              })
            }
          />
        ) : (
          <Empty
            icon={<Users />}
            title="Пока нет кандидатов"
            description="Загрузите резюме, проверьте персонализированные вопросы и получите ссылку на интервью."
          />
        )}
      </section>
      <details className="surface-card group mt-6 p-6">
        <summary className="flex cursor-pointer list-none items-center justify-between font-semibold">
          Общий пул вопросов · {interview.questions.length}
          <ChevronRight className="size-5 transition-transform group-open:rotate-90" />
        </summary>
        <ol className="mt-5 divide-y">
          {interview.questions.map((question, index) => (
            <li key={index} className="flex gap-4 py-4">
              <span className="text-sm text-muted-foreground">
                {index + 1}.
              </span>
              <div>
                <p className="text-sm leading-relaxed">{question.text}</p>
                {question.topic ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {question.topic}
                    {question.competency ? ` · ${question.competency}` : ''}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      </details>
      {addOpen ? (
        <AddCandidateDialog
          open
          interview={interview}
          onClose={() => setAddOpen(false)}
          onSaved={(result) => {
            setApproval(result);
            resource.reload();
          }}
          notify={notify}
        />
      ) : null}
    </>
  );
}

function CandidatesPage({
  navigate,
  notify,
}: {
  navigate: (view: View) => void;
  notify: Notify;
}) {
  const [search, setSearch] = useState('');
  const resource = useResource(
    useCallback((signal: AbortSignal) => api.listCandidates('', signal), []),
  );
  const candidates = (resource.data || []).filter((candidate) =>
    candidate.name
      .toLocaleLowerCase('ru-RU')
      .includes(search.toLocaleLowerCase('ru-RU')),
  );
  return (
    <>
      <Heading
        eyebrow="Все вакансии и интервью"
        title="Кандидаты"
        description="Текущий статус каждого кандидата и результаты интервью в одном месте."
      />
      <div className="relative mb-5 max-w-xl">
        <Search className="absolute left-3 top-3 size-4 text-muted-foreground" />
        <Input
          aria-label="Поиск кандидатов по имени"
          placeholder="Поиск по имени"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-10 pl-10"
        />
      </div>
      {resource.loading ? (
        <Busy />
      ) : resource.error ? (
        <ErrorPanel message={resource.error} retry={resource.reload} />
      ) : (
        <section className="surface-card">
          {candidates.length ? (
            <CandidateRows
              global
              candidates={candidates}
              onDeleted={() => {
                notify('Кандидат удалён');
                resource.reload();
              }}
              onOpen={(candidate) =>
                navigate({ type: 'candidate', candidateId: candidate.id })
              }
            />
          ) : (
            <Empty
              icon={<Users />}
              title={search ? 'Кандидаты не найдены' : 'Пока нет кандидатов'}
              description={
                search
                  ? 'Попробуйте изменить поисковый запрос.'
                  : 'Добавьте кандидата в интервью нужной вакансии.'
              }
            />
          )}
        </section>
      )}
    </>
  );
}

export function HrApp({ notify }: { notify: Notify }) {
  const [view, setView] = useState<View>({ type: 'vacancies' });
  const navigate = (next: View) => {
    setView(next);
    window.scrollTo({ top: 0, behavior: 'instant' });
  };
  const mainGroup =
    view.type === 'vacancy' ||
    view.type === 'create-vacancy' ||
    view.type === 'create-interview' ||
    view.type === 'interview' ||
    (view.type === 'candidate' && view.interviewId)
      ? 'vacancies'
      : view.type === 'candidate'
        ? 'candidates'
        : view.type;
  const navItems = [
    { type: 'vacancies' as const, label: 'Вакансии', icon: BriefcaseBusiness },
    { type: 'candidates' as const, label: 'Кандидаты', icon: Users },
    { type: 'context' as const, label: 'Общий контекст', icon: BookOpen },
    {
      type: 'vacancy-templates' as const,
      label: 'Шаблоны вакансий',
      icon: Layers3,
    },
    {
      type: 'interview-templates' as const,
      label: 'Шаблоны интервью',
      icon: MessageSquare,
    },
  ];
  let content: ReactNode;
  if (view.type === 'context') content = <CompanyContextPage notify={notify} />;
  else if (view.type === 'vacancy-templates')
    content = <VacancyTemplatesPage navigate={navigate} notify={notify} />;
  else if (view.type === 'interview-templates')
    content = <InterviewTemplatesPage notify={notify} />;
  else if (view.type === 'create-vacancy')
    content = (
      <CreateVacancyPage
        key={view.templateId || 'new'}
        templateId={view.templateId}
        navigate={navigate}
        notify={notify}
      />
    );
  else if (view.type === 'vacancy')
    content = (
      <VacancyOverview
        key={view.vacancyId}
        vacancyId={view.vacancyId}
        navigate={navigate}
        notify={notify}
      />
    );
  else if (view.type === 'create-interview')
    content = (
      <CreateInterviewPage
        key={view.vacancyId}
        vacancyId={view.vacancyId}
        canSkip={view.canSkip}
        navigate={navigate}
        notify={notify}
      />
    );
  else if (view.type === 'interview')
    content = (
      <InterviewOverview
        key={view.interviewId}
        interviewId={view.interviewId}
        vacancyId={view.vacancyId}
        navigate={navigate}
        notify={notify}
      />
    );
  else if (view.type === 'candidates')
    content = <CandidatesPage navigate={navigate} notify={notify} />;
  else if (view.type === 'candidate')
    content = (
      <CandidateWorkspace
        key={view.candidateId}
        candidateId={view.candidateId}
        notify={notify}
        onBack={() =>
          navigate(
            view.interviewId && view.vacancyId
              ? {
                  type: 'interview',
                  interviewId: view.interviewId,
                  vacancyId: view.vacancyId,
                }
              : { type: 'candidates' },
          )
        }
      />
    );
  else content = <VacanciesPage navigate={navigate} />;
  return (
    <div className="app-grid">
      <aside className="sidebar">
        <nav aria-label="Навигация рекрутера" className="space-y-1">
          {navItems.map(({ type, label, icon: Icon }, index) => (
            <button
              key={type}
              aria-current={mainGroup === type ? 'page' : undefined}
              className={`side-link ${mainGroup === type ? 'side-link-active' : ''} ${index === 2 ? 'mt-5' : ''}`}
              onClick={() => navigate({ type })}
            >
              <Icon aria-hidden="true" />
              {label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 px-5 pb-16 pt-7 sm:px-8 xl:px-12">
        <div className="mobile-product-nav !flex-wrap">
          {navItems.map(({ type, label, icon: Icon }) => (
            <button
              key={type}
              aria-current={mainGroup === type ? 'page' : undefined}
              className={mainGroup === type ? 'text-primary' : ''}
              onClick={() => navigate({ type })}
            >
              <Icon />
              {label}
            </button>
          ))}
        </div>
        <div className="mx-auto max-w-[1120px]">{content}</div>
      </main>
    </div>
  );
}
