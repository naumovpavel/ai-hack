export type UserRole = 'hr' | 'candidate';

export type TestUser = {
  id: string;
  role: UserRole;
  name: string;
  initials: string;
  meta: string;
  candidateId?: string;
};

export type ProcessingStatus =
  | 'not_started'
  | 'recorded'
  | 'transcribing'
  | 'analyzing'
  | 'ready'
  | 'error';

export type HiringDecision = 'pending' | 'next_stage' | 'rejected';
export type CandidateStatus =
  | 'needs_interview'
  | 'processing'
  | 'awaiting_decision'
  | 'next_stage'
  | 'rejected';

export type EvidenceLabel = 'confirmed' | 'incorrect' | 'check';

export type EvidenceSpan = {
  id: string;
  quote: string;
  start: number;
  end: number;
  timestamp: string;
  label: EvidenceLabel;
  confidence: number;
  rationale: string;
  criterionIds: string[];
};

export type AnswerReview = {
  id: string;
  questionId: string;
  question: string;
  topic: string;
  duration: string;
  transcript: string;
  evidence: EvidenceSpan[];
  missingAspects: string[];
};

export type CriterionResult = {
  id: string;
  name: string;
  required: boolean;
  score: number | null;
  status: 'confirmed' | 'partial' | 'unknown';
  summary: string;
  evidenceCount: number;
};

export type AnalysisResult = {
  id: string;
  version: string;
  score: number;
  confidence: number;
  recommendation: 'fit' | 'manual_review' | 'not_fit';
  summary: string;
  strengths: string[];
  growthAreas: string[];
  unknowns: string[];
  skills: string[];
  criteria: CriterionResult[];
  answers: AnswerReview[];
  nextQuestions: string[];
  antifraud: {
    tabSwitches: number;
    pasteEvents: number;
  };
};

export type HumanDecisionRecord = {
  status: Exclude<HiringDecision, 'pending'>;
  reason: string;
  feedback: string;
  decidedAt: string;
};

export type Candidate = {
  id: string;
  name: string;
  initials: string;
  email: string;
  role: string;
  resume: string;
  processingStatus: ProcessingStatus;
  hiringDecision: HiringDecision;
  analysis?: AnalysisResult;
  decision?: HumanDecisionRecord;
};

export type Position = {
  id: string;
  title: string;
  level: string;
  location: string;
  status: 'active' | 'draft';
  createdAt: string;
  description: string;
  requirements: string[];
  questions: string[];
  candidates: Candidate[];
};

export type InterviewHistory = {
  id: string;
  company: string;
  positionTitle: string;
  date: string;
  status: 'rejected' | 'next_stage';
  feedback?: string;
  nextStep?: string;
};

export const testUsers: TestUser[] = [
  {
    id: 'hr-yulia',
    role: 'hr',
    name: 'Юлия Белова',
    initials: 'ЮБ',
    meta: 'Рекрутер · Neon',
  },
  {
    id: 'candidate-andrey',
    role: 'candidate',
    name: 'Андрей Лебедев',
    initials: 'АЛ',
    meta: 'Кандидат',
    candidateId: 'candidate-strong',
  },
  {
    id: 'candidate-maxim',
    role: 'candidate',
    name: 'Максим Романов',
    initials: 'МР',
    meta: 'Кандидат',
    candidateId: 'candidate-upcoming',
  },
];

const strongAnalysis: AnalysisResult = {
  id: 'analysis-strong',
  version: 'mock-adapter-v6',
  score: 8,
  confidence: 0.84,
  recommendation: 'fit',
  summary:
    'Кандидат демонстрирует хороший уровень профессиональных знаний и практического опыта. Наиболее убедительны ответы про RabbitMQ, PostgreSQL и асинхронный Python. Для следующего этапа стоит уточнить личный вклад в CI/CD и измеримые результаты.',
  strengths: [
    'Глубоко понимает подтверждения, retry и dead-letter очереди в RabbitMQ.',
    'Уверенно объясняет EXPLAIN ANALYZE, статистику планировщика и причины медленных запросов.',
    'Корректно описывает event loop и последствия блокирующих вызовов.',
    'Осознанно использует AI и перепроверяет сгенерированный код.',
  ],
  growthAreas: [
    'Не хватает конкретных метрик результата и масштаба изменений.',
    'CI/CD описан менее глубоко: часть деплоя выполнял DevOps.',
    'Личный вклад в инфраструктурные решения раскрыт частично.',
  ],
  unknowns: [
    'Продакшн-опыт с Kafka не подтверждён ответами.',
    'Не проверены Event Sourcing и CQRS.',
  ],
  skills: [
    'Python',
    'FastAPI',
    'RabbitMQ',
    'PostgreSQL',
    'Docker',
    'Kubernetes',
    'CI/CD',
  ],
  criteria: [
    {
      id: 'q02_delivery',
      name: 'Надёжность сообщений',
      required: true,
      score: 8.8,
      status: 'confirmed',
      summary: 'Подтверждения, идемпотентность, ограниченный retry и DLQ раскрыты на практике.',
      evidenceCount: 3,
    },
    {
      id: 'q03_diagnosis',
      name: 'PostgreSQL и данные',
      required: true,
      score: 8.4,
      status: 'confirmed',
      summary: 'Есть опыт загрузки файлов в несколько ГБ и диагностики EXPLAIN ANALYZE.',
      evidenceCount: 2,
    },
    {
      id: 'q05_blocking',
      name: 'Асинхронный Python',
      required: true,
      score: 8.9,
      status: 'confirmed',
      summary: 'Корректно различает I/O-задачи и объясняет блокировку event loop.',
      evidenceCount: 2,
    },
    {
      id: 'q04_deploy',
      name: 'CI/CD и контейнеры',
      required: true,
      score: 6.1,
      status: 'partial',
      summary: 'CI раскрыт, но сборка образа, rollout и проверяемый rollback описаны частично.',
      evidenceCount: 1,
    },
    {
      id: 'q08_store',
      name: 'Event Sourcing и CQRS',
      required: false,
      score: null,
      status: 'unknown',
      summary: 'Тема не проверялась в этой версии интервью.',
      evidenceCount: 0,
    },
  ],
  answers: [
    {
      id: 'answer-messaging',
      questionId: 'q02_messaging',
      topic: 'Очереди сообщений',
      duration: '04:18',
      question:
        'Расскажите про продакшн-сервис на Python с Kafka или RabbitMQ. Как защищались от потери, дублей и необработанных сообщений?',
      transcript:
        'Если говорить про RabbitMQ, то использовал FastStream. При отправке сообщений продюсером ждали подтверждения. Для сложной обработки фиксировали успешно пройденные этапы в PostgreSQL и при повторной доставке пропускали их. Для ошибок использовали retry-очереди с экспоненциальной задержкой, а после трёх попыток — dead-letter очередь.',
      evidence: [
        {
          id: 'evidence-rabbit-ack',
          quote: 'при отправке сообщений продюсером ждали подтверждения',
          start: 62,
          end: 119,
          timestamp: '01:24',
          label: 'confirmed',
          confidence: 0.93,
          rationale:
            'Ответ называет подтверждение публикации как механизм защиты от потери сообщения.',
          criterionIds: ['q02_delivery'],
        },
        {
          id: 'evidence-rabbit-retry',
          quote: 'retry-очереди с экспоненциальной задержкой, а после трёх попыток — dead-letter очередь',
          start: 258,
          end: 348,
          timestamp: '03:06',
          label: 'confirmed',
          confidence: 0.95,
          rationale:
            'Кандидат описывает ограниченные повторы, задержку и отдельный маршрут для необработанных сообщений.',
          criterionIds: ['q02_failures'],
        },
      ],
      missingAspects: ['Опыт с Kafka в этом ответе не подтверждён.'],
    },
    {
      id: 'answer-postgres',
      questionId: 'q03_postgresql',
      topic: 'PostgreSQL',
      duration: '03:42',
      question:
        'Как вы загружали большие объёмы данных в PostgreSQL и находили причину медленных запросов?',
      transcript:
        'Файлы были на несколько гигабайт. Из кода разбивали данные на батчи примерно по тысяче строк. Для медленных запросов сначала выполняли EXPLAIN ANALYZE и сравнивали ожидаемое число строк с фактическим, затем смотрели статистику, узлы плана и выход операций на диск.',
      evidence: [
        {
          id: 'evidence-postgres-scale',
          quote: 'Файлы были на несколько гигабайт',
          start: 0,
          end: 34,
          timestamp: '00:38',
          label: 'check',
          confidence: 0.72,
          rationale:
            'Масштаб назван, но это факт личного опыта — его следует подтвердить уточняющим вопросом.',
          criterionIds: ['q03_scale'],
        },
        {
          id: 'evidence-postgres-explain',
          quote: 'выполняли EXPLAIN ANALYZE и сравнивали ожидаемое число строк с фактическим',
          start: 126,
          end: 200,
          timestamp: '02:07',
          label: 'confirmed',
          confidence: 0.94,
          rationale:
            'Назван корректный способ диагностики плана и качества статистики PostgreSQL.',
          criterionIds: ['q03_diagnosis'],
        },
      ],
      missingAspects: ['Не назван способ загрузки через COPY или staging-таблицу.'],
    },
    {
      id: 'answer-cicd',
      questionId: 'q04_cicd',
      topic: 'CI/CD',
      duration: '02:51',
      question:
        'Что делал CI/CD-пайплайн, как собирали Docker-образ, деплоили и откатывались?',
      transcript:
        'В GitLab запускали линтеры и тесты. Затем контейнер отправлялся в registry. Дальнейшие этапы Kubernetes в основном настраивал DevOps, я вносил отдельные изменения в конфигурацию и контролировал перезапуск подов по дашбордам.',
      evidence: [
        {
          id: 'evidence-cicd-partial',
          quote: 'Дальнейшие этапы Kubernetes в основном настраивал DevOps',
          start: 83,
          end: 140,
          timestamp: '01:35',
          label: 'check',
          confidence: 0.88,
          rationale:
            'Личный вклад кандидата в деплой и rollback ограничен; необходима дополнительная проверка.',
          criterionIds: ['q04_deploy', 'q04_rollback'],
        },
      ],
      missingAspects: ['как собирали Docker-образ', 'проверяемый rollback на immutable image'],
    },
    {
      id: 'answer-async',
      questionId: 'q05_async',
      topic: 'Async Python',
      duration: '03:29',
      question:
        'Когда выбираете асинхронный код и что произойдёт при блокирующем вызове внутри event loop?',
      transcript:
        'Асинхронный код подходит, когда много I/O-операций. В финтех-проекте получали внешние данные от брокера и работали с базой. Если вызвать блокирующую функцию без await, управление не возвращается событийном циклу и остальные корутины не выполняются.',
      evidence: [
        {
          id: 'evidence-async-block',
          quote: 'управление не возвращается событийном циклу и остальные корутины не выполняются',
          start: 146,
          end: 225,
          timestamp: '02:18',
          label: 'confirmed',
          confidence: 0.96,
          rationale:
            'Ответ корректно описывает влияние синхронного блокирующего вызова на event loop.',
          criterionIds: ['q05_blocking'],
        },
      ],
      missingAspects: [],
    },
  ],
  nextQuestions: [
    'Как именно собирался и тегировался Docker-образ, и какой механизм использовали для rollback?',
    'Назовите одну измеримую метрику, которая изменилась после вашей оптимизации PostgreSQL.',
    'Расскажите про решение, за которое вы лично отвечали в Kubernetes.',
  ],
  antifraud: {
    tabSwitches: 10,
    pasteEvents: 0,
  },
};

export const developingAnalysis: AnalysisResult = {
  id: 'analysis-developing',
  version: 'mock-adapter-v6',
  score: 6.67,
  confidence: 0.77,
  recommendation: 'manual_review',
  summary:
    'Кандидат показывает общую техническую базу по Kafka, PostgreSQL, CI/CD и async Python, но ответы часто остаются на уровне общих формулировок. До решения стоит проверить практическую глубину, масштаб задач и личный вклад.',
  strengths: [
    'Понимает назначение Outbox и offset в очередях сообщений.',
    'Знаком с индексами и EXPLAIN для PostgreSQL.',
    'Ориентируется в GitLab CI, Docker и базовых принципах async Python.',
  ],
  growthAreas: [
    'Не хватает конкретных примеров и измеримых результатов.',
    'Не раскрыты retry, DLQ и защита от повторной обработки.',
    'Часть технических утверждений требует ручной проверки.',
  ],
  unknowns: ['Масштаб продакшн-нагрузки', 'Личный вклад в CI/CD', 'Глубина работы с Kubernetes'],
  skills: ['Python', 'Kafka', 'PostgreSQL', 'GitLab CI', 'Docker', 'FastAPI'],
  criteria: [
    {
      id: 'q02_delivery',
      name: 'Надёжность сообщений',
      required: true,
      score: 5.9,
      status: 'partial',
      summary: 'Outbox и offset упомянуты, но идемпотентность и обработка ошибок не раскрыты.',
      evidenceCount: 2,
    },
    {
      id: 'q03_diagnosis',
      name: 'PostgreSQL и данные',
      required: true,
      score: 6.8,
      status: 'partial',
      summary: 'Есть знание индексов и EXPLAIN, нет убедительного примера большой загрузки.',
      evidenceCount: 2,
    },
    {
      id: 'q05_blocking',
      name: 'Асинхронный Python',
      required: true,
      score: 7.1,
      status: 'confirmed',
      summary: 'Базово понимает event loop и блокирующие вызовы.',
      evidenceCount: 1,
    },
    {
      id: 'q04_image',
      name: 'CI/CD и контейнеры',
      required: true,
      score: 5.8,
      status: 'partial',
      summary: 'Перечислены job-этапы, но сборка образа и rollback раскрыты слабо.',
      evidenceCount: 1,
    },
  ],
  answers: [
    {
      id: 'answer-developing-messaging',
      questionId: 'q02_messaging',
      topic: 'Очереди сообщений',
      duration: '03:37',
      question:
        'Как добивались, чтобы сообщение не потерялось и не обработалось дважды?',
      transcript:
        'Сообщения хранились в Kafka. У каждого был GUID, а Outbox гарантировал отправку. Если consumer останавливался, после запуска он продолжал с последнего закоммиченного offset.',
      evidence: [
        {
          id: 'evidence-developing-id',
          quote: 'У каждого был GUID, а Outbox гарантировал отправку',
          start: 30,
          end: 83,
          timestamp: '01:11',
          label: 'check',
          confidence: 0.78,
          rationale:
            'GUID и Outbox сами по себе не гарантируют отсутствие повторной обработки; нужна фиксация идемпотентного результата.',
          criterionIds: ['q02_idempotency'],
        },
      ],
      missingAspects: ['retry и dead-letter очередь'],
    },
    {
      id: 'answer-developing-postgres',
      questionId: 'q03_postgresql',
      topic: 'PostgreSQL',
      duration: '03:08',
      question: 'Как загружали большие объёмы и диагностировали медленные запросы?',
      transcript:
        'Больших объёмов, которые сильно тормозили, не было. Медленные запросы смотрели по моделям и индексам, добавляли prefetch, а для сложных случаев использовали EXPLAIN.',
      evidence: [
        {
          id: 'evidence-developing-explain',
          quote: 'для сложных случаев использовали EXPLAIN',
          start: 127,
          end: 168,
          timestamp: '02:26',
          label: 'confirmed',
          confidence: 0.9,
          rationale: 'EXPLAIN — релевантный инструмент, но не раскрыты ANALYZE, BUFFERS и разбор плана.',
          criterionIds: ['q03_diagnosis'],
        },
      ],
      missingAspects: ['измеримый объём загрузки', 'как была устроена загрузка'],
    },
    {
      id: 'answer-developing-cicd',
      questionId: 'q04_cicd',
      topic: 'CI/CD',
      duration: '02:44',
      question: 'Как собирали Docker-образ, деплоили и откатывались?',
      transcript:
        'В GitLab были job для build, тестов и деплоя на стенды. Старые images удаляли, чтобы не заканчивалось место. Для отката брали образ прошлой версии.',
      evidence: [
        {
          id: 'evidence-developing-rollback',
          quote: 'Для отката брали образ прошлой версии',
          start: 113,
          end: 150,
          timestamp: '02:02',
          label: 'check',
          confidence: 0.74,
          rationale:
            'Подход возможен, но не названы immutable tag/digest, механизм rollout и проверка успешности отката.',
          criterionIds: ['q04_rollback'],
        },
      ],
      missingAspects: ['как собирали Docker-образ'],
    },
  ],
  nextQuestions: [
    'Как вы фиксировали результат обработки сообщения, чтобы повторная доставка не создала дубль?',
    'Расскажите о самой большой загрузке PostgreSQL: объём, время и способ импорта.',
  ],
  antifraud: {
    tabSwitches: 1,
    pasteEvents: 0,
  },
};

export const initialPositions: Position[] = [
  {
    id: 'middle-python',
    title: 'Middle+ Python Developer',
    level: 'Middle+',
    location: 'Санкт-Петербург · Челябинск · удалённо',
    status: 'active',
    createdAt: '2 сентября',
    description:
      'Разработка и поддержка высоконагруженных микросервисов; интеграции с Kafka; проектирование Event Sourcing и CQRS; разработка API; мониторинг и code review.',
    requirements: [
      'Python — от 5 лет коммерческой разработки',
      'Django или FastAPI, разработка REST API',
      'Apache Kafka: producers, consumers, доставка сообщений',
      'PostgreSQL: схемы, загрузка данных, оптимизация запросов',
      'Docker, Kubernetes и CI/CD',
      'Event-driven архитектура, CQRS и Event Sourcing',
    ],
    questions: [
      'Почему вы сейчас ищете работу и какими задачами хотите заниматься?',
      'Расскажите про продакшн-сервис на Python с Kafka или RabbitMQ: доставка, идемпотентность и необработанные сообщения.',
      'Как вы загружали большие объёмы данных в PostgreSQL и находили причины медленных запросов?',
      'Расскажите про CI/CD-пайплайн Python-сервиса: сборка образа, деплой и откат.',
      'Когда выбираете асинхронный код, а когда синхронный? Что произойдёт при блокирующем вызове?',
      'Как вы используете AI в работе и как проверяете результат?',
    ],
    candidates: [
      {
        id: 'candidate-strong',
        name: 'Андрей Лебедев',
        initials: 'АЛ',
        email: 'andrey@example.test',
        role: 'Senior Python-разработчик',
        resume:
          '6 лет Python. FastAPI, RabbitMQ, PostgreSQL, Docker и Kubernetes. Последний проект — финтех-платформа для алгоритмической торговли.',
        processingStatus: 'ready',
        hiringDecision: 'pending',
        analysis: strongAnalysis,
      },
      {
        id: 'candidate-upcoming',
        name: 'Максим Романов',
        initials: 'МР',
        email: 'maxim@example.test',
        role: 'Python-разработчик',
        resume:
          '4 года backend-разработки. Django, FastAPI, Kafka, PostgreSQL и GitLab CI. Работал с интеграционными сервисами и API-шинами.',
        processingStatus: 'not_started',
        hiringDecision: 'pending',
      },
    ],
  },
];

export const candidateHistories: Record<string, InterviewHistory[]> = {
  'candidate-strong': [
    {
      id: 'history-data-platform',
      company: 'Northstar',
      positionTitle: 'Data Platform Engineer',
      date: '18 августа',
      status: 'rejected',
      feedback:
        'Вы уверенно разобрали SQL и структуру пайплайна. Для этой роли нам не хватило подтверждённого опыта с инкрементальными ETL-загрузками и безопасным replay. Рекомендуем подготовить пример с watermark, дедупликацией и восстановлением после сбоя.',
    },
    {
      id: 'history-backend-labs',
      company: 'Labs',
      positionTitle: 'Backend Engineer',
      date: '7 августа',
      status: 'next_stage',
      nextStep: 'Разговор с техническим лидом назначен на 10 сентября, 16:00.',
    },
  ],
  'candidate-upcoming': [
    {
      id: 'history-python-core',
      company: 'Core',
      positionTitle: 'Python Developer',
      date: '12 августа',
      status: 'rejected',
      feedback:
        'В ответах была хорошая база Python и REST. Для роли требовался более глубокий продакшн-опыт с Kubernetes и наблюдаемостью. Полезно подготовить пример безопасного rollout с readiness/liveness probes и метриками деградации.',
    },
    {
      id: 'history-api-studio',
      company: 'Studio',
      positionTitle: 'API Engineer',
      date: '30 июля',
      status: 'next_stage',
      nextStep: 'Команда пришлёт варианты времени для финальной встречи.',
    },
  ],
};

export const candidateStatusCopy: Record<
  CandidateStatus,
  { label: string; candidateLabel: string; tone: string }
> = {
  needs_interview: {
    label: 'Ожидает интервью',
    candidateLabel: 'Нужно пройти',
    tone: 'bg-blue-50 text-blue-700 ring-blue-200',
  },
  processing: {
    label: 'AI анализирует',
    candidateLabel: 'Ждём ответа команды',
    tone: 'bg-violet-50 text-violet-700 ring-violet-200',
  },
  awaiting_decision: {
    label: 'Ждёт решения',
    candidateLabel: 'Ждём ответа команды',
    tone: 'bg-amber-50 text-amber-800 ring-amber-200',
  },
  next_stage: {
    label: 'Следующий этап',
    candidateLabel: 'Позвали дальше',
    tone: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  rejected: {
    label: 'Отказ',
    candidateLabel: 'Отказ',
    tone: 'bg-rose-50 text-rose-700 ring-rose-200',
  },
};

export function getCandidateStatus(candidate: Candidate): CandidateStatus {
  if (candidate.hiringDecision === 'next_stage') return 'next_stage';
  if (candidate.hiringDecision === 'rejected') return 'rejected';
  if (candidate.processingStatus === 'not_started') return 'needs_interview';
  if (
    candidate.processingStatus === 'recorded' ||
    candidate.processingStatus === 'transcribing' ||
    candidate.processingStatus === 'analyzing'
  ) {
    return 'processing';
  }
  return 'awaiting_decision';
}

export const questionTopics = [
  'Мотивация и задачи',
  'Kafka или RabbitMQ',
  'PostgreSQL',
  'CI/CD и Docker',
  'Async Python',
  'AI в разработке',
];
