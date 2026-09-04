'use client';

import { useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  Clock3,
  LayoutDashboard,
  ListChecks,
  MessageSquareQuote,
  Plus,
  ShieldCheck,
  Sparkles,
  Target,
  UserPlus,
  Users,
  WandSparkles,
} from 'lucide-react';

import { Avatar, BackButton, StatusPill } from '@/components/product/shared';
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
import { mockApi } from '@/lib/mock-api';
import {
  getCandidateStatus,
  type AnalysisResult,
  type Candidate,
  type EvidenceLabel,
  type HumanDecisionRecord,
  type Position,
} from '@/lib/mock-data';

type HrView =
  | { type: 'dashboard' }
  | { type: 'create-position' }
  | { type: 'position'; positionId: string }
  | { type: 'candidate'; positionId: string; candidateId: string };

type HrAppProps = {
  positions: Position[];
  setPositions: Dispatch<SetStateAction<Position[]>>;
  notify: (message: string) => void;
};

function HrSidebar({
  view,
  positions,
  onNavigate,
}: {
  view: HrView;
  positions: Position[];
  onNavigate: (view: HrView) => void;
}) {
  const candidateCount = positions.reduce(
    (total, position) => total + position.candidates.length,
    0,
  );
  const onDashboard = view.type === 'dashboard' || view.type === 'create-position';

  return (
    <aside className="sidebar">
      <nav aria-label="Навигация рекрутера" className="space-y-1">
        <button
          className={`side-link ${onDashboard ? 'side-link-active' : ''}`}
          onClick={() => onNavigate({ type: 'dashboard' })}
        >
          <LayoutDashboard aria-hidden="true" />
          Обзор
        </button>
        <button
          className={`side-link ${view.type === 'position' ? 'side-link-active' : ''}`}
          onClick={() => onNavigate({ type: 'dashboard' })}
        >
          <BriefcaseBusiness aria-hidden="true" />
          Позиции
          <span className="ml-auto text-xs opacity-65">{positions.length}</span>
        </button>
        <button
          className={`side-link ${view.type === 'candidate' ? 'side-link-active' : ''}`}
          onClick={() => {
            const firstPosition = positions[0];
            if (firstPosition) {
              onNavigate({ type: 'position', positionId: firstPosition.id });
            }
          }}
        >
          <Users aria-hidden="true" />
          Кандидаты
          <span className="ml-auto text-xs opacity-65">{candidateCount}</span>
        </button>
      </nav>

      <div className="mt-auto rounded-2xl bg-[#1b1b20] p-4 text-white">
        <div className="mb-3 grid size-9 place-items-center rounded-xl bg-white/10">
          <Sparkles className="size-4" aria-hidden="true" />
        </div>
        <p className="text-sm font-medium">AI готовит evidence</p>
        <p className="mt-1 text-xs leading-relaxed text-white/60">
          Финальное решение всегда принимает нанимающая команда.
        </p>
      </div>
    </aside>
  );
}

function MobileHrNav({ onNavigate }: { onNavigate: (view: HrView) => void }) {
  return (
    <div className="mobile-product-nav" aria-label="Навигация рекрутера">
      <button onClick={() => onNavigate({ type: 'dashboard' })}>
        <LayoutDashboard aria-hidden="true" /> Обзор
      </button>
      <button onClick={() => onNavigate({ type: 'create-position' })}>
        <Plus aria-hidden="true" /> Позиция
      </button>
    </div>
  );
}

function HrDashboard({
  positions,
  onNavigate,
}: {
  positions: Position[];
  onNavigate: (view: HrView) => void;
}) {
  const allCandidates = positions.flatMap((position) => position.candidates);
  const awaitingCount = allCandidates.filter(
    (candidate) => getCandidateStatus(candidate) === 'awaiting_decision',
  ).length;
  const needsInterviewCount = allCandidates.filter(
    (candidate) => getCandidateStatus(candidate) === 'needs_interview',
  ).length;

  return (
    <div className="mx-auto max-w-[1120px]">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Рабочее пространство рекрутера</p>
          <h1 className="page-title">Добрый вечер, Юлия</h1>
          <p className="mt-2 max-w-2xl text-[15px] text-muted-foreground">
            {awaitingCount
              ? `${awaitingCount} кандидат ждёт вашего решения.`
              : 'Новых решений пока нет.'}{' '}
            {needsInterviewCount ? `Ещё ${needsInterviewCount} нужно пройти интервью.` : ''}
          </p>
        </div>
        <Button
          size="lg"
          className="h-11 rounded-xl px-4 shadow-sm"
          onClick={() => onNavigate({ type: 'create-position' })}
        >
          <Plus data-icon="inline-start" />
          Создать позицию
        </Button>
      </div>

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        {[
          { value: positions.length, label: 'Активные позиции', icon: BriefcaseBusiness },
          { value: allCandidates.length, label: 'Всего кандидатов', icon: Users },
          { value: awaitingCount, label: 'Требуют решения', icon: Clock3 },
        ].map(({ value, label, icon: Icon }) => (
          <div key={label} className="metric-card">
            <span className="metric-icon">
              <Icon aria-hidden="true" />
            </span>
            <span>
              <span className="block text-2xl font-semibold tracking-[-0.04em]">{value}</span>
              <span className="text-xs text-muted-foreground">{label}</span>
            </span>
          </div>
        ))}
      </div>

      <section aria-labelledby="positions-heading">
        <div className="mb-3 flex items-center justify-between px-1">
          <h2 id="positions-heading" className="text-sm font-semibold">
            Позиции найма
          </h2>
          <span className="text-xs text-muted-foreground">Обновлено сейчас</span>
        </div>

        <div className="space-y-3">
          {positions.map((position) => {
            const ready = position.candidates.filter(
              (candidate) => candidate.processingStatus === 'ready',
            ).length;
            return (
              <button
                key={position.id}
                className="surface-card position-card group w-full text-left"
                onClick={() => onNavigate({ type: 'position', positionId: position.id })}
              >
                <div className="min-w-0 flex-1">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge className="bg-emerald-50 text-emerald-700">Активна</Badge>
                    <span className="text-xs text-muted-foreground">Создана {position.createdAt}</span>
                  </div>
                  <h3 className="truncate text-xl font-semibold tracking-[-0.025em]">
                    {position.title}
                  </h3>
                  <p className="mt-1 truncate text-sm text-muted-foreground">
                    {position.level} · {position.location || 'Локация не указана'}
                  </p>
                </div>
                <div className="grid shrink-0 grid-cols-2 gap-6 text-right max-sm:hidden">
                  <span>
                    <span className="block text-lg font-semibold">{position.candidates.length}</span>
                    <span className="text-[11px] text-muted-foreground">кандидатов</span>
                  </span>
                  <span>
                    <span className="block text-lg font-semibold">{ready}</span>
                    <span className="text-[11px] text-muted-foreground">AI-отчётов</span>
                  </span>
                </div>
                <span className="grid size-10 shrink-0 place-items-center rounded-full bg-muted transition group-hover:bg-accent group-hover:text-accent-foreground">
                  <ChevronRight className="size-4" aria-hidden="true" />
                </span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function CreatePositionView({
  example,
  onCancel,
  onCreated,
  notify,
}: {
  example: Position | undefined;
  onCancel: () => void;
  onCreated: (position: Position) => void;
  notify: (message: string) => void;
}) {
  const [title, setTitle] = useState('');
  const [level, setLevel] = useState('');
  const [location, setLocation] = useState('');
  const [description, setDescription] = useState('');
  const [requirements, setRequirements] = useState('');
  const [questions, setQuestions] = useState('');
  const [saving, setSaving] = useState(false);

  const isValid =
    title.trim().length > 2 &&
    description.trim().length > 20 &&
    requirements.trim().length > 10 &&
    questions.trim().length > 10;

  const fillExample = () => {
    if (!example) return;
    setTitle(example.title);
    setLevel(example.level);
    setLocation(example.location);
    setDescription(example.description);
    setRequirements(example.requirements.join('\n'));
    setQuestions(example.questions.join('\n'));
    notify('Форма заполнена примером из датасета AI-анализа');
  };

  const submit = async (event: React.SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isValid || saving) return;
    setSaving(true);
    const position = await mockApi.createPosition({
      title: title.trim(),
      level: level.trim() || 'Уровень не указан',
      location: location.trim(),
      description: description.trim(),
      requirements: requirements
        .split('\n')
        .map((item) => item.trim())
        .filter(Boolean),
      questions: questions
        .split('\n')
        .map((item) => item.trim())
        .filter(Boolean),
    });
    setSaving(false);
    onCreated(position);
  };

  return (
    <div className="mx-auto max-w-4xl">
      <BackButton onClick={onCancel} label="К позициям" />
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Новая позиция</p>
          <h1 className="page-title">Настройте интервью</h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Сейчас все входы текстовые. Вакансия, требования и вопросы отправятся в те же
            поля будущих backend-ручек.
          </p>
        </div>
        <Button variant="outline" size="lg" className="h-10 rounded-xl" onClick={fillExample}>
          <WandSparkles data-icon="inline-start" />
          Заполнить примером
        </Button>
      </div>

      <form onSubmit={submit} className="space-y-4">
        <section className="form-section">
          <div className="form-section-heading">
            <span className="form-step">1</span>
            <div>
              <h2>Основное</h2>
              <p>Название, грейд и формат работы.</p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="field-label sm:col-span-2" htmlFor="position-title">
              Название позиции <span aria-hidden="true">*</span>
              <Input
                id="position-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Например, Middle+ Python Developer"
                className="mt-2 h-11 rounded-xl"
                required
              />
            </label>
            <label className="field-label" htmlFor="position-level">
              Уровень
              <Input
                id="position-level"
                value={level}
                onChange={(event) => setLevel(event.target.value)}
                placeholder="Middle+"
                className="mt-2 h-11 rounded-xl"
              />
            </label>
            <label className="field-label" htmlFor="position-location">
              Локация и формат
              <Input
                id="position-location"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="Москва · удалённо"
                className="mt-2 h-11 rounded-xl"
              />
            </label>
          </div>
        </section>

        <section className="form-section">
          <div className="form-section-heading">
            <span className="form-step">2</span>
            <div>
              <h2>Вакансия и требования</h2>
              <p>AI использует их как контекст, а не как автономный фильтр.</p>
            </div>
          </div>
          <div className="space-y-4">
            <label className="field-label" htmlFor="position-description">
              Описание вакансии <span aria-hidden="true">*</span>
              <Textarea
                id="position-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Задачи, команда, продукт и контекст роли"
                className="mt-2 min-h-32 rounded-xl leading-relaxed"
                required
              />
            </label>
            <label className="field-label" htmlFor="position-requirements">
              Требования к кандидату <span aria-hidden="true">*</span>
              <Textarea
                id="position-requirements"
                value={requirements}
                onChange={(event) => setRequirements(event.target.value)}
                placeholder={'Каждое требование — с новой строки\nPython от 5 лет\nОпыт с Kafka'}
                className="mt-2 min-h-40 rounded-xl leading-relaxed"
                required
              />
              <span className="field-hint">Одна строка — один критерий будущей rubric.</span>
            </label>
          </div>
        </section>

        <section className="form-section">
          <div className="form-section-heading">
            <span className="form-step">3</span>
            <div>
              <h2>Готовые вопросы</h2>
              <p>Общее ядро для всех кандидатов этой позиции.</p>
            </div>
          </div>
          <label className="field-label" htmlFor="position-questions">
            Вопросы интервью <span aria-hidden="true">*</span>
            <Textarea
              id="position-questions"
              value={questions}
              onChange={(event) => setQuestions(event.target.value)}
              placeholder={'Каждый вопрос — с новой строки\nРасскажите про продакшн-сервис...'}
              className="mt-2 min-h-52 rounded-xl leading-relaxed"
              required
            />
            <span className="field-hint">Рекомендуется 5–7 основных вопросов.</span>
          </label>
        </section>

        <div className="sticky-form-actions">
          <Button type="button" variant="ghost" size="lg" onClick={onCancel}>
            Отмена
          </Button>
          <Button type="submit" size="lg" className="h-11 rounded-xl px-5" disabled={!isValid || saving}>
            {saving ? 'Создаём…' : 'Создать позицию'}
          </Button>
        </div>
      </form>
    </div>
  );
}

function AddCandidateDialog({
  open,
  onOpenChange,
  onAdd,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (candidate: Candidate) => void;
}) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('Python-разработчик');
  const [resume, setResume] = useState('');
  const [saving, setSaving] = useState(false);
  const valid = name.trim().length > 2 && resume.trim().length > 20;

  const submit = async (event: React.SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    const candidate = await mockApi.addCandidate({
      name: name.trim(),
      email: email.trim() || 'candidate@example.test',
      role: role.trim() || 'Кандидат',
      resume: resume.trim(),
    });
    setSaving(false);
    onAdd(candidate);
    onOpenChange(false);
    setName('');
    setEmail('');
    setResume('');
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl rounded-2xl p-5">
        <DialogHeader>
          <div className="mb-1 grid size-10 place-items-center rounded-xl bg-accent text-accent-foreground">
            <UserPlus className="size-5" aria-hidden="true" />
          </div>
          <DialogTitle className="text-xl tracking-[-0.02em]">Добавить кандидата</DialogTitle>
          <DialogDescription>
            Резюме хранится как отдельный источник. Факты из него не считаются подтверждёнными без ответа.
          </DialogDescription>
        </DialogHeader>
        <form id="add-candidate-form" onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="field-label" htmlFor="candidate-name">
              Имя кандидата <span aria-hidden="true">*</span>
              <Input
                id="candidate-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-2 h-11 rounded-xl"
                placeholder="Имя и фамилия"
                required
              />
            </label>
            <label className="field-label" htmlFor="candidate-email">
              Email
              <Input
                id="candidate-email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="mt-2 h-11 rounded-xl"
                placeholder="name@example.com"
                type="email"
              />
            </label>
          </div>
          <label className="field-label" htmlFor="candidate-role">
            Текущая роль
            <Input
              id="candidate-role"
              value={role}
              onChange={(event) => setRole(event.target.value)}
              className="mt-2 h-11 rounded-xl"
            />
          </label>
          <label className="field-label" htmlFor="candidate-resume">
            Резюме <span aria-hidden="true">*</span>
            <Textarea
              id="candidate-resume"
              value={resume}
              onChange={(event) => setResume(event.target.value)}
              className="mt-2 min-h-40 rounded-xl leading-relaxed"
              placeholder="Вставьте текст резюме кандидата"
              required
            />
          </label>
        </form>
        <DialogFooter className="-mx-5 -mb-5 px-5">
          <Button type="button" variant="outline" size="lg" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button type="submit" form="add-candidate-form" size="lg" disabled={!valid || saving}>
            {saving ? 'Добавляем…' : 'Добавить кандидата'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PositionView({
  position,
  onBack,
  onOpenCandidate,
  onAddCandidate,
  notify,
}: {
  position: Position;
  onBack: () => void;
  onOpenCandidate: (candidateId: string) => void;
  onAddCandidate: (candidate: Candidate) => void;
  notify: (message: string) => void;
}) {
  const [addOpen, setAddOpen] = useState(false);
  const readyCount = position.candidates.filter(
    (candidate) => candidate.processingStatus === 'ready',
  ).length;

  return (
    <div className="mx-auto max-w-[1120px]">
      <BackButton onClick={onBack} label="К позициям" />
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <Badge className="bg-emerald-50 text-emerald-700">Активна</Badge>
            <span className="text-xs text-muted-foreground">Создана {position.createdAt}</span>
          </div>
          <h1 className="page-title !mt-0">{position.title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {position.level} · {position.location || 'Локация не указана'}
          </p>
        </div>
        <Button size="lg" className="h-11 rounded-xl" onClick={() => setAddOpen(true)}>
          <UserPlus data-icon="inline-start" />
          Добавить кандидата
        </Button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_310px]">
        <section className="surface-card" aria-labelledby="candidate-list-heading">
          <div className="flex items-center justify-between border-b p-5 sm:p-6">
            <div>
              <h2 id="candidate-list-heading" className="text-base font-semibold">
                Кандидаты
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {position.candidates.length} всего · {readyCount} с готовым AI-анализом
              </p>
            </div>
          </div>

          {position.candidates.length ? (
            <div className="p-2 sm:p-3">
              {position.candidates.map((candidate) => {
                const status = getCandidateStatus(candidate);
                return (
                  <button
                    key={candidate.id}
                    className="candidate-row group w-full text-left"
                    onClick={() => onOpenCandidate(candidate.id)}
                  >
                    <Avatar initials={candidate.initials} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{candidate.name}</span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {candidate.role}
                      </span>
                    </span>
                    {candidate.analysis ? (
                      <span className="hidden text-right sm:block">
                        <span className="block text-sm font-semibold tabular-nums">
                          {candidate.analysis.score.toFixed(1)}
                        </span>
                        <span className="text-[11px] text-muted-foreground">AI-оценка</span>
                      </span>
                    ) : null}
                    <StatusPill status={status} />
                    <ArrowUpRight
                      className="size-4 text-muted-foreground transition group-hover:text-foreground"
                      aria-hidden="true"
                    />
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="grid min-h-72 place-items-center p-8 text-center">
              <div>
                <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-muted">
                  <Users className="size-5 text-muted-foreground" aria-hidden="true" />
                </span>
                <h3 className="mt-4 font-medium">Кандидатов пока нет</h3>
                <p className="mt-1 text-sm text-muted-foreground">Добавьте резюме первого кандидата.</p>
                <Button className="mt-4" onClick={() => setAddOpen(true)}>
                  Добавить кандидата
                </Button>
              </div>
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <div className="surface-card p-5">
            <div className="mb-4 flex items-center gap-2">
              <Target className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold">О позиции</h2>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{position.description}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {position.requirements.slice(0, 4).map((requirement) => (
                <span key={requirement} className="rounded-lg bg-muted px-2.5 py-1.5 text-[11px] font-medium">
                  {requirement.split(',')[0]}
                </span>
              ))}
            </div>
          </div>

          <div className="surface-card p-5">
            <div className="mb-3 flex items-center gap-2">
              <ListChecks className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold">Вопросы</h2>
              <span className="ml-auto text-xs text-muted-foreground">{position.questions.length}</span>
            </div>
            <ol className="space-y-3">
              {position.questions.slice(0, 3).map((question, index) => (
                <li key={question} className="flex gap-2.5 text-xs leading-relaxed text-muted-foreground">
                  <span className="grid size-5 shrink-0 place-items-center rounded-md bg-muted text-[10px] font-semibold text-foreground">
                    {index + 1}
                  </span>
                  <span className="line-clamp-2">{question}</span>
                </li>
              ))}
            </ol>
            {position.questions.length > 3 ? (
              <Button
                variant="ghost"
                size="sm"
                className="mt-3 -ml-2"
                onClick={() => notify(`В интервью ${position.questions.length} основных вопросов`)}
              >
                Показать все
              </Button>
            ) : null}
          </div>
        </aside>
      </div>

      <AddCandidateDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onAdd={(candidate) => {
          onAddCandidate(candidate);
          notify(`${candidate.name} добавлен в позицию`);
        }}
      />
    </div>
  );
}

const evidenceCopy: Record<
  EvidenceLabel,
  { label: string; className: string }
> = {
  confirmed: {
    label: 'Подтверждено',
    className: 'bg-emerald-50 text-emerald-700',
  },
  incorrect: {
    label: 'Ошибка',
    className: 'bg-rose-50 text-rose-700',
  },
  check: {
    label: 'Проверить',
    className: 'bg-amber-50 text-amber-800',
  },
};

function AnalysisOverview({ analysis }: { analysis: AnalysisResult }) {
  const recommendation = {
    fit: {
      title: 'Рекомендуем позвать дальше',
      text: 'Ключевые must-have компетенции подтверждены. Остались вопросы, которые удобно проверить с командой.',
      tone: 'recommendation-fit',
    },
    manual_review: {
      title: 'Нужна дополнительная проверка',
      text: 'База релевантна, но данных недостаточно для уверенного вывода по нескольким обязательным критериям.',
      tone: 'recommendation-review',
    },
    not_fit: {
      title: 'Есть существенные разрывы',
      text: 'Рекомендация основана только на job-related evidence и требует решения человека.',
      tone: 'recommendation-risk',
    },
  }[analysis.recommendation];

  return (
    <>
      <section className={`recommendation-card ${recommendation.tone}`}>
        <div className="relative z-10 min-w-0 flex-1">
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold">
            <Sparkles className="size-4" aria-hidden="true" />
            Рекомендация AI
          </div>
          <h2 className="text-2xl font-semibold tracking-[-0.035em]">{recommendation.title}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed opacity-75">{recommendation.text}</p>
          <p className="mt-4 max-w-3xl text-sm leading-relaxed">{analysis.summary}</p>
        </div>
        <div className="score-orbit" aria-label={`AI-оценка ${analysis.score} из 10`}>
          <span className="text-3xl font-semibold tracking-[-0.06em]">{analysis.score}</span>
          <span className="text-[10px] opacity-65">из 10</span>
        </div>
      </section>

      <div className="ai-disclosure">
        <ShieldCheck className="size-4 shrink-0 text-primary" aria-hidden="true" />
        <p>
          AI подготовил материалы для решения, но не принимает кадровое решение. Уверенность анализа —{' '}
          <strong>{Math.round(analysis.confidence * 100)}%</strong>.
        </p>
      </div>

      <section className="surface-card p-5 sm:p-6" aria-labelledby="criteria-heading">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 id="criteria-heading" className="text-base font-semibold">Оценка по критериям</h2>
            <p className="mt-1 text-xs text-muted-foreground">Must-have и непроверенные навыки разделены.</p>
          </div>
          <Badge variant="outline">{analysis.criteria.length} критериев</Badge>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {analysis.criteria.map((criterion) => (
            <article key={criterion.id} className="criterion-card">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-medium">{criterion.name}</h3>
                    {criterion.required ? (
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-primary">must-have</span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{criterion.summary}</p>
                </div>
                <span className="text-base font-semibold tabular-nums">
                  {criterion.score === null ? '—' : criterion.score.toFixed(1)}
                </span>
              </div>
              <Progress
                value={criterion.score === null ? 0 : criterion.score * 10}
                className={`mt-4 ${
                  criterion.status === 'confirmed'
                    ? '[&_[data-slot=progress-indicator]]:bg-emerald-500'
                    : criterion.status === 'partial'
                      ? '[&_[data-slot=progress-indicator]]:bg-amber-500'
                      : '[&_[data-slot=progress-indicator]]:bg-zinc-300'
                }`}
                aria-label={`${criterion.name}: ${criterion.score ?? 'не оценено'}`}
              />
              <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
                <span>
                  {criterion.status === 'unknown'
                    ? 'Не проверено'
                    : `${criterion.evidenceCount} evidence-фрагмента`}
                </span>
                <span>{criterion.status === 'confirmed' ? 'Подтверждено' : criterion.status === 'partial' ? 'Частично' : 'Unknown'}</span>
              </div>
            </article>
          ))}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
        <section className="insight-card insight-positive">
          <CheckCircle2 aria-hidden="true" />
          <h2>Сильные стороны</h2>
          <ul>
            {analysis.strengths.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
        <section className="insight-card insight-warning">
          <AlertTriangle aria-hidden="true" />
          <h2>Зоны проверки</h2>
          <ul>
            {analysis.growthAreas.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
        <section className="insight-card insight-neutral">
          <Target aria-hidden="true" />
          <h2>Недостаточно данных</h2>
          <ul>
            {analysis.unknowns.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}

function EvidenceSection({
  analysis,
  notify,
}: {
  analysis: AnalysisResult;
  notify: (message: string) => void;
}) {
  return (
    <section className="surface-card p-5 sm:p-6" aria-labelledby="evidence-heading">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="evidence-heading" className="text-base font-semibold">Ответы и доказательства</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Каждый вывод связан с вопросом, цитатой и критерием.
          </p>
        </div>
        <Badge variant="outline">{analysis.answers.length} ответа разобрано</Badge>
      </div>

      <div className="space-y-2">
        {analysis.answers.map((answer, index) => (
          <details key={answer.id} className="evidence-answer">
            <summary>
              <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-muted text-xs font-semibold">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{answer.topic}</span>
                <span className="block truncate text-xs text-muted-foreground">{answer.question}</span>
              </span>
              <span className="text-xs tabular-nums text-muted-foreground">{answer.duration}</span>
              <ChevronRight className="details-chevron size-4 text-muted-foreground" aria-hidden="true" />
            </summary>
            <div className="evidence-body">
              <div>
                <p className="evidence-kicker">Фрагмент транскрипта</p>
                <p className="mt-2 text-sm leading-7 text-muted-foreground">{answer.transcript}</p>
              </div>

              {answer.evidence.map((evidence) => {
                const copy = evidenceCopy[evidence.label];
                return (
                  <article key={evidence.id} className="evidence-quote">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <Badge className={copy.className}>{copy.label}</Badge>
                      <span className="text-[10px] text-muted-foreground">
                        Уверенность {Math.round(evidence.confidence * 100)}%
                      </span>
                    </div>
                    <blockquote>«{evidence.quote}»</blockquote>
                    <p>{evidence.rationale}</p>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mt-2 -ml-2"
                      onClick={() => notify(`Открыт фрагмент ответа на ${evidence.timestamp}`)}
                    >
                      <MessageSquareQuote data-icon="inline-start" />
                      Фрагмент · {evidence.timestamp}
                    </Button>
                  </article>
                );
              })}

              {answer.missingAspects.length ? (
                <div className="missing-aspects">
                  <p className="text-xs font-semibold">Не раскрыто в ответе</p>
                  <ul>
                    {answer.missingAspects.map((aspect) => (
                      <li key={aspect}>{aspect}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </details>
        ))}
      </div>
      <p className="mt-4 text-[10px] leading-relaxed text-muted-foreground">
        Цитаты адаптированы из датасета анализа. Медиатаймкоды в этой демонстрации замоканы;
        фактический pipeline сохраняет символьные offsets.
      </p>
    </section>
  );
}

function RejectionDialog({
  open,
  onOpenChange,
  analysis,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  analysis: AnalysisResult;
  onSubmit: (reason: string, feedback: string) => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [feedback, setFeedback] = useState(
    `Спасибо за интервью. В ответах была хорошая техническая база, но для этой позиции нам не хватило подтверждённой глубины в следующих областях: ${analysis.growthAreas
      .slice(0, 2)
      .join(' ')}`,
  );
  const [saving, setSaving] = useState(false);
  const valid = reason.trim().length >= 12 && feedback.trim().length >= 30;

  const submit = async (event: React.SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    await onSubmit(reason.trim(), feedback.trim());
    setSaving(false);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl rounded-2xl p-5">
        <DialogHeader>
          <div className="mb-1 grid size-10 place-items-center rounded-xl bg-rose-50 text-rose-700">
            <AlertTriangle className="size-5" aria-hidden="true" />
          </div>
          <DialogTitle className="text-xl tracking-[-0.02em]">Обоснуйте отказ</DialogTitle>
          <DialogDescription>
            Решение принимает человек. Причина обязательна, а feedback должен опираться только на
            профессиональные evidence из интервью.
          </DialogDescription>
        </DialogHeader>
        <form id="reject-candidate-form" onSubmit={submit} className="space-y-4">
          <label className="field-label" htmlFor="rejection-reason">
            Внутренняя причина решения <span aria-hidden="true">*</span>
            <Textarea
              id="rejection-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Какие требования позиции не подтверждены?"
              className="mt-2 min-h-24 rounded-xl leading-relaxed"
              required
            />
            <span className="field-hint">Минимум 12 символов. Не используйте внешность, акцент или антифрод-события.</span>
          </label>
          <label className="field-label" htmlFor="candidate-feedback">
            Фидбэк кандидату <span aria-hidden="true">*</span>
            <Textarea
              id="candidate-feedback"
              value={feedback}
              onChange={(event) => setFeedback(event.target.value)}
              className="mt-2 min-h-36 rounded-xl leading-relaxed"
              required
            />
          </label>
        </form>
        <DialogFooter className="-mx-5 -mb-5 px-5">
          <Button type="button" variant="outline" size="lg" onClick={() => onOpenChange(false)}>
            Вернуться
          </Button>
          <Button
            type="submit"
            form="reject-candidate-form"
            variant="destructive"
            size="lg"
            disabled={!valid || saving}
          >
            {saving ? 'Сохраняем…' : 'Подтвердить отказ'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CandidateResultView({
  candidate,
  onBack,
  onDecision,
  notify,
}: {
  candidate: Candidate;
  onBack: () => void;
  onDecision: (record: HumanDecisionRecord) => void;
  notify: (message: string) => void;
}) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [savingDecision, setSavingDecision] = useState(false);
  const status = getCandidateStatus(candidate);
  const analysis = candidate.analysis;

  const decideNext = async () => {
    if (savingDecision) return;
    setSavingDecision(true);
    const record = await mockApi.saveDecision(
      'next_stage',
      'Must-have компетенции подтверждены; вопросы по CI/CD перенесены на разговор с командой.',
      'Команда хочет продолжить знакомство. На следующем этапе обсудим ваш личный вклад в CI/CD и Kubernetes.',
    );
    setSavingDecision(false);
    onDecision(record);
    notify(`${candidate.name} приглашён на следующий этап`);
  };

  if (!analysis) {
    return (
      <div className="mx-auto max-w-4xl">
        <BackButton onClick={onBack} label="К кандидатам" />
        <div className="surface-card p-7 text-center sm:p-12">
          <Avatar initials={candidate.initials} size="lg" />
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.03em]">{candidate.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{candidate.role}</p>
          <div className="mt-5 flex justify-center"><StatusPill status={status} /></div>
          <p className="mx-auto mt-5 max-w-lg text-sm leading-relaxed text-muted-foreground">
            AI-анализ появится здесь после прохождения интервью и завершения обработки.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1120px] pb-28">
      <BackButton onClick={onBack} label="К кандидатам" />
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Avatar initials={candidate.initials} size="lg" />
          <div>
            <h1 className="text-2xl font-semibold tracking-[-0.035em]">{candidate.name}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{candidate.role}</p>
          </div>
        </div>
        <StatusPill status={status} />
      </div>

      <div className="space-y-4">
        <AnalysisOverview analysis={analysis} />
        <EvidenceSection analysis={analysis} notify={notify} />

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]">
          <section className="surface-card p-5 sm:p-6">
            <div className="mb-4 flex items-center gap-2">
              <MessageSquareQuote className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-base font-semibold">Вопросы на следующий этап</h2>
            </div>
            <ol className="space-y-3">
              {analysis.nextQuestions.map((question, index) => (
                <li key={question} className="flex gap-3 text-sm leading-relaxed">
                  <span className="grid size-6 shrink-0 place-items-center rounded-lg bg-accent text-[10px] font-semibold text-accent-foreground">
                    {index + 1}
                  </span>
                  {question}
                </li>
              ))}
            </ol>
          </section>

          <section className="surface-card p-5 sm:p-6">
            <div className="mb-3 flex items-center gap-2">
              <ShieldCheck className="size-4 text-muted-foreground" aria-hidden="true" />
              <h2 className="text-sm font-semibold">Технические события</h2>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl bg-muted p-3">
                <span className="block text-xl font-semibold">{analysis.antifraud.tabSwitches}</span>
                <span className="text-[10px] text-muted-foreground">уходов из вкладки</span>
              </div>
              <div className="rounded-xl bg-muted p-3">
                <span className="block text-xl font-semibold">{analysis.antifraud.pasteEvents}</span>
                <span className="text-[10px] text-muted-foreground">вставок текста</span>
              </div>
            </div>
            <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">
              Эти сигналы не влияют на профессиональный score и не доказывают нарушение.
            </p>
          </section>
        </div>
      </div>

      {candidate.hiringDecision === 'pending' ? (
        <div className="decision-bar">
          <div className="hidden sm:block">
            <p className="text-sm font-medium">Ваше решение</p>
            <p className="text-xs text-muted-foreground">AI-рекомендация не отправляется кандидату автоматически.</p>
          </div>
          <div className="ml-auto flex w-full gap-2 sm:w-auto">
            <Button
              variant="destructive"
              size="lg"
              className="h-11 flex-1 rounded-xl sm:flex-none"
              onClick={() => setRejectOpen(true)}
            >
              Отказать
            </Button>
            <Button
              size="lg"
              className="h-11 flex-1 rounded-xl sm:flex-none"
              onClick={decideNext}
              disabled={savingDecision}
            >
              {savingDecision ? 'Сохраняем…' : 'Позвать дальше'}
              <ArrowUpRight data-icon="inline-end" />
            </Button>
          </div>
        </div>
      ) : (
        <div className="decision-bar">
          <CheckCircle2 className="size-5 text-emerald-600" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium">
              Решение сохранено: {candidate.hiringDecision === 'next_stage' ? 'следующий этап' : 'отказ'}
            </p>
            <p className="text-xs text-muted-foreground">{candidate.decision?.decidedAt}</p>
          </div>
        </div>
      )}

      <RejectionDialog
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        analysis={analysis}
        onSubmit={async (reason, feedback) => {
          const record = await mockApi.saveDecision('rejected', reason, feedback);
          onDecision(record);
          notify(`Решение по ${candidate.name} сохранено, фидбэк доступен кандидату`);
        }}
      />
    </div>
  );
}

export function HrApp({ positions, setPositions, notify }: HrAppProps) {
  const [view, setView] = useState<HrView>({ type: 'dashboard' });

  const activePosition = useMemo(() => {
    if (view.type === 'dashboard' || view.type === 'create-position') return undefined;
    return positions.find((position) => position.id === view.positionId);
  }, [positions, view]);

  const activeCandidate = useMemo(() => {
    if (view.type !== 'candidate' || !activePosition) return undefined;
    return activePosition.candidates.find((candidate) => candidate.id === view.candidateId);
  }, [activePosition, view]);

  const addCandidate = (positionId: string, candidate: Candidate) => {
    setPositions((current) =>
      current.map((position) =>
        position.id === positionId
          ? { ...position, candidates: [...position.candidates, candidate] }
          : position,
      ),
    );
  };

  const saveDecision = (
    positionId: string,
    candidateId: string,
    record: HumanDecisionRecord,
  ) => {
    setPositions((current) =>
      current.map((position) =>
        position.id === positionId
          ? {
              ...position,
              candidates: position.candidates.map((candidate) =>
                candidate.id === candidateId
                  ? {
                      ...candidate,
                      hiringDecision: record.status,
                      decision: record,
                    }
                  : candidate,
              ),
            }
          : position,
      ),
    );
  };

  let content: React.ReactNode = null;

  if (view.type === 'dashboard') {
    content = <HrDashboard positions={positions} onNavigate={setView} />;
  } else if (view.type === 'create-position') {
    content = (
      <CreatePositionView
        example={positions[0]}
        onCancel={() => setView({ type: 'dashboard' })}
        notify={notify}
        onCreated={(position) => {
          setPositions((current) => [...current, position]);
          notify(`Позиция «${position.title}» создана`);
          setView({ type: 'position', positionId: position.id });
        }}
      />
    );
  } else if (view.type === 'position' && activePosition) {
    content = (
      <PositionView
        position={activePosition}
        onBack={() => setView({ type: 'dashboard' })}
        notify={notify}
        onAddCandidate={(candidate) => addCandidate(activePosition.id, candidate)}
        onOpenCandidate={(candidateId) =>
          setView({ type: 'candidate', positionId: activePosition.id, candidateId })
        }
      />
    );
  } else if (view.type === 'candidate' && activePosition && activeCandidate) {
    content = (
      <CandidateResultView
        candidate={activeCandidate}
        notify={notify}
        onBack={() => setView({ type: 'position', positionId: activePosition.id })}
        onDecision={(record) => saveDecision(activePosition.id, activeCandidate.id, record)}
      />
    );
  } else {
    content = <HrDashboard positions={positions} onNavigate={setView} />;
  }

  return (
    <div className="app-grid">
      <HrSidebar view={view} positions={positions} onNavigate={setView} />
      <main className="min-w-0 px-5 pb-14 pt-7 sm:px-8 xl:px-12">
        <MobileHrNav onNavigate={setView} />
        {content}
      </main>
    </div>
  );
}
