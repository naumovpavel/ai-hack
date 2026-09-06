import type {
  UserRole,
  TelegramLogin,
  TelegramLoginStatus,
  AddCandidateInput,
  Analysis,
  AnswerResult,
  Approval,
  CandidateDetail,
  CandidateMedia,
  CandidateOutcome,
  CompleteInterviewResult,
  CreatePositionInput,
  Decision,
  DecisionInput,
  InterviewBriefing,
  InterviewQuestion,
  InterviewState,
  PositionDetail,
  PositionSummary,
  QuestionRating,
  InitialDecisionInput,
  PracticeSet,
  Session,
  User,
  ContextDocument,
  VacancyTemplate,
  InterviewTemplate,
  Vacancy,
  VacancyDetail,
  VacancyDraft,
  VacancyFields,
  InterviewPlanDraft,
  InterviewPlan,
  InterviewPlanDetail,
  CandidateDraft,
  CandidateSummary,
  EditableQuestion,
} from '@/lib/types';

const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
export const API_BASE_URL = (
  configuredBaseUrl || 'http://localhost:8000'
).replace(/\/+$/, '');

type RequestOptions = RequestInit & { allowNotFound?: boolean };
type ErrorPayload = {
  error?: { code?: string; message?: string; details?: unknown };
  detail?: string | Array<{ msg?: string }>;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(
    message: string,
    status: number,
    code?: string,
    details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function endpoint(path: string) {
  return `${API_BASE_URL}/api/v1${path.startsWith('/') ? path : `/${path}`}`;
}

function detailMessage(detail: ErrorPayload['detail']) {
  if (typeof detail === 'string') return detail;
  if (!Array.isArray(detail)) return '';
  return detail
    .map((item) => item.msg)
    .filter((item): item is string => Boolean(item))
    .join('; ');
}

function validationMessage(error: ErrorPayload['error']) {
  if (
    error?.code !== 'validation_error' ||
    !error.details ||
    typeof error.details !== 'object'
  )
    return '';
  const errors = (
    error.details as {
      errors?: Array<{
        loc?: Array<string | number>;
        type?: string;
        ctx?: Record<string, unknown>;
      }>;
    }
  ).errors;
  if (!Array.isArray(errors)) return '';
  const labels: Record<string, string> = {
    title: 'Название вакансии',
    name: 'Имя / название',
    role: 'Роль',
    level: 'Грейд',
    description: 'Описание',
    requirements: 'Требования',
    questions: 'Вопросы',
    text: 'Текст вопроса',
    topic: 'Тема вопроса',
    competency: 'Критерий вопроса',
    evaluates: 'Что проверяется',
    maxPersonalizedQuestions: 'Максимум персонализированных вопросов',
    maxFollowUpQuestions: 'Максимум уточняющих вопросов',
    durationMinutes: 'Лимит времени',
  };
  return errors
    .slice(0, 3)
    .map((entry) => {
      const field =
        entry.loc
          ?.filter(
            (item): item is string =>
              typeof item === 'string' && item !== 'body',
          )
          .at(-1) || '';
      const label = labels[field] || 'Поле формы';
      const context = entry.ctx || {};
      if (entry.type === 'string_too_short')
        return `${label}: минимум ${String(context.min_length)} символа.`;
      if (entry.type === 'string_too_long')
        return `${label}: максимум ${String(context.max_length)} символов.`;
      if (entry.type === 'less_than_equal')
        return `${label}: не больше ${String(context.le)}.`;
      if (entry.type === 'greater_than_equal')
        return `${label}: не меньше ${String(context.ge)}.`;
      if (entry.type === 'too_long')
        return `${label}: максимум ${String(context.max_length)} пунктов.`;
      if (entry.type === 'too_short')
        return `${label}: добавьте хотя бы ${String(context.min_length)} пункт.`;
      return `Проверьте поле «${label}».`;
    })
    .join(' ');
}

async function readPayload(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return response.json();
  const text = await response.text();
  return text || undefined;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T | null> {
  const { allowNotFound = false, headers, ...init } = options;
  const requestHeaders = new Headers(headers);
  if (!requestHeaders.has('Accept'))
    requestHeaders.set('Accept', 'application/json');
  const response = await fetch(endpoint(path), {
    ...init,
    credentials: 'include',
    headers: requestHeaders,
  });
  if (allowNotFound && (response.status === 401 || response.status === 404))
    return null;

  const payload = await readPayload(response);
  if (!response.ok) {
    const errorPayload =
      payload && typeof payload === 'object'
        ? (payload as ErrorPayload)
        : undefined;
    throw new ApiError(
      validationMessage(errorPayload?.error) ||
        errorPayload?.error?.message ||
        detailMessage(errorPayload?.detail) ||
        (typeof payload === 'string' ? payload : '') ||
        `API request failed with status ${response.status}`,
      response.status,
      errorPayload?.error?.code,
      errorPayload?.error?.details,
    );
  }
  return payload as T;
}

async function required<T>(path: string, options?: RequestOptions): Promise<T> {
  const payload = await request<T>(path, options);
  if (payload === null || payload === undefined) {
    throw new ApiError('API returned an empty response', 502, 'empty_response');
  }
  return payload;
}

function unwrapItems<T>(payload: T[] | { items: T[] }): T[] {
  return Array.isArray(payload) ? payload : payload.items;
}

function jsonRequest(body: unknown, init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  return {
    ...init,
    headers,
    body: JSON.stringify(body),
  };
}

function vacancyPayload(value: VacancyFields): VacancyFields {
  const { title, role, level, description, requirements } = value;
  return { title, role, level, description, requirements };
}

function questionPayload(question: EditableQuestion) {
  return {
    text: question.text.trim(),
    ...(question.topic?.trim() ? { topic: question.topic.trim() } : {}),
    ...(question.competency?.trim()
      ? { competency: question.competency.trim() }
      : {}),
  };
}

function appendText(form: FormData, key: string, value: string) {
  if (value.trim()) form.set(key, value.trim());
}

function blobFilename(blob: Blob, fallback: string) {
  return blob instanceof File && blob.name ? blob.name : fallback;
}

function recordedFilename(blob: Blob, stem: string) {
  if (blob.type.includes('mp4')) return `${stem}.mp4`;
  if (blob.type.includes('ogg')) return `${stem}.ogg`;
  if (blob.type.includes('wav')) return `${stem}.wav`;
  return `${stem}.webm`;
}

async function requestBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(endpoint(path), {
    credentials: 'include',
    headers: { Accept: 'audio/wav, audio/mpeg' },
    signal,
  });
  if (!response.ok) {
    const payload = await readPayload(response);
    const errorPayload =
      payload && typeof payload === 'object'
        ? (payload as ErrorPayload)
        : undefined;
    throw new ApiError(
      errorPayload?.error?.message ||
        `Audio request failed with status ${response.status}`,
      response.status,
      errorPayload?.error?.code,
      errorPayload?.error?.details,
    );
  }
  return response.blob();
}

export const api = {
  startTelegramLogin(
    role: UserRole,
    inviteToken: string | null,
  ): Promise<TelegramLogin> {
    return required(
      '/auth/telegram/start',
      jsonRequest({ role, inviteToken }, { method: 'POST' }),
    );
  },
  telegramLoginStatus(signal?: AbortSignal): Promise<TelegramLoginStatus> {
    return required('/auth/telegram/status', { signal });
  },
  switchRole(role: UserRole): Promise<Session> {
    return required('/auth/role', jsonRequest({ role }, { method: 'POST' }));
  },
  async logout(): Promise<void> {
    await request('/auth/session', { method: 'DELETE' });
  },
  async listCompanyContext(signal?: AbortSignal): Promise<ContextDocument[]> {
    return unwrapItems(
      await required<ContextDocument[] | { items: ContextDocument[] }>(
        '/company-context',
        { signal },
      ),
    );
  },

  uploadCompanyContext(
    document: File,
    signal?: AbortSignal,
  ): Promise<ContextDocument> {
    const form = new FormData();
    form.set('document', document, document.name);
    return required<ContextDocument>('/company-context', {
      method: 'POST',
      body: form,
      signal,
    });
  },

  async listVacancyTemplates(signal?: AbortSignal): Promise<VacancyTemplate[]> {
    return unwrapItems(
      await required<VacancyTemplate[] | { items: VacancyTemplate[] }>(
        '/vacancy-templates',
        { signal },
      ),
    );
  },

  updateVacancyTemplate(
    id: string,
    fields: VacancyFields,
  ): Promise<VacancyTemplate> {
    return required<VacancyTemplate>(
      `/vacancy-templates/${encodeURIComponent(id)}`,
      jsonRequest(vacancyPayload(fields), { method: 'PATCH' }),
    );
  },

  async listInterviewTemplates(
    signal?: AbortSignal,
  ): Promise<InterviewTemplate[]> {
    return unwrapItems(
      await required<InterviewTemplate[] | { items: InterviewTemplate[] }>(
        '/interview-templates',
        { signal },
      ),
    );
  },

  updateInterviewTemplate(
    id: string,
    fields: Pick<InterviewTemplate, 'name' | 'description' | 'evaluates'>,
  ): Promise<InterviewTemplate> {
    return required<InterviewTemplate>(
      `/interview-templates/${encodeURIComponent(id)}`,
      jsonRequest(
        {
          name: fields.name,
          description: fields.description,
          evaluates: fields.evaluates,
        },
        { method: 'PATCH' },
      ),
    );
  },

  async listVacancies(signal?: AbortSignal): Promise<Vacancy[]> {
    return unwrapItems(
      await required<Vacancy[] | { items: Vacancy[] }>('/vacancies', {
        signal,
      }),
    );
  },

  getVacancy(id: string, signal?: AbortSignal): Promise<VacancyDetail> {
    return required<VacancyDetail>(`/vacancies/${encodeURIComponent(id)}`, {
      signal,
    });
  },

  parseVacancy(file: File, signal?: AbortSignal): Promise<VacancyDraft> {
    const form = new FormData();
    form.set('vacancy', file, file.name);
    return required<VacancyDraft>('/vacancies/parse', {
      method: 'POST',
      body: form,
      signal,
    });
  },

  createVacancy(draft: VacancyDraft): Promise<VacancyDetail> {
    return required<VacancyDetail>(
      '/vacancies',
      jsonRequest(
        {
          ...vacancyPayload(draft),
          draftId: draft.draftId,
          templateId: draft.templateId,
        },
        { method: 'POST' },
      ),
    );
  },

  updateVacancy(id: string, fields: VacancyFields): Promise<VacancyDetail> {
    return required<VacancyDetail>(
      `/vacancies/${encodeURIComponent(id)}`,
      jsonRequest(vacancyPayload(fields), { method: 'PATCH' }),
    );
  },

  prepareInterview(
    vacancyId: string,
    templateId: string,
    signal?: AbortSignal,
  ): Promise<InterviewPlanDraft> {
    return required<InterviewPlanDraft>(
      `/vacancies/${encodeURIComponent(vacancyId)}/interviews/prepare`,
      jsonRequest({ templateId }, { method: 'POST', signal }),
    );
  },

  createInterviewPlan(
    vacancyId: string,
    draft: InterviewPlanDraft,
  ): Promise<InterviewPlan> {
    const {
      templateId,
      questions,
      maxFollowUpQuestions,
      maxPersonalizedQuestions,
      durationMinutes,
    } = draft;
    return required<InterviewPlan>(
      `/vacancies/${encodeURIComponent(vacancyId)}/interviews`,
      jsonRequest(
        {
          templateId,
          questions: questions.map(questionPayload),
          maxFollowUpQuestions,
          maxPersonalizedQuestions,
          durationMinutes,
        },
        { method: 'POST' },
      ),
    );
  },

  getInterviewPlan(
    id: string,
    signal?: AbortSignal,
  ): Promise<InterviewPlanDetail> {
    return required<InterviewPlanDetail>(
      `/interview-plans/${encodeURIComponent(id)}`,
      { signal },
    );
  },

  prepareCandidate(
    interviewPlanId: string,
    resume: File,
    signal?: AbortSignal,
  ): Promise<CandidateDraft> {
    const form = new FormData();
    form.set('resume', resume, resume.name);
    return required<CandidateDraft>(
      `/interview-plans/${encodeURIComponent(interviewPlanId)}/candidates/prepare`,
      { method: 'POST', body: form, signal },
    );
  },

  savePreparedCandidate(
    interviewPlanId: string,
    draft: CandidateDraft,
  ): Promise<Approval> {
    return required<Approval>(
      `/interview-plans/${encodeURIComponent(interviewPlanId)}/candidates`,
      jsonRequest(
        {
          draftId: draft.draftId,
          name: draft.name,
          email: draft.email,
          telegramUsername: draft.telegramUsername || null,
          role: draft.role,
          questions: draft.questions.map(questionPayload),
        },
        { method: 'POST' },
      ),
    );
  },

  async listCandidates(
    search = '',
    signal?: AbortSignal,
  ): Promise<CandidateSummary[]> {
    return unwrapItems(
      await required<CandidateSummary[] | { items: CandidateSummary[] }>(
        `/candidates${search ? `?search=${encodeURIComponent(search)}` : ''}`,
        { signal },
      ),
    );
  },

  async listUsers(signal?: AbortSignal): Promise<User[]> {
    const payload = await required<User[] | { items: User[] }>('/dev/users', {
      signal,
    });
    return unwrapItems(payload);
  },

  async getSession(signal?: AbortSignal): Promise<User | null> {
    const payload = await request<User | Session>('/session', {
      signal,
      allowNotFound: true,
    });
    if (!payload) return null;
    return 'user' in payload ? payload.user : payload;
  },

  setSession(userId: string, signal?: AbortSignal): Promise<Session> {
    return required<Session>(
      '/dev/session',
      jsonRequest({ userId }, { method: 'POST', signal }),
    );
  },

  async listPositions(signal?: AbortSignal): Promise<PositionSummary[]> {
    const payload = await required<
      PositionSummary[] | { items: PositionSummary[] }
    >('/positions', {
      signal,
    });
    return unwrapItems(payload);
  },

  getPosition(
    positionId: string,
    signal?: AbortSignal,
  ): Promise<PositionDetail> {
    return required<PositionDetail>(
      `/positions/${encodeURIComponent(positionId)}`,
      { signal },
    );
  },

  createPosition(
    input: CreatePositionInput,
    signal?: AbortSignal,
  ): Promise<PositionDetail> {
    const form = new FormData();
    form.set('title', input.title.trim());
    appendText(form, 'level', input.level);
    appendText(form, 'location', input.location);
    form.set('requirements', JSON.stringify(input.requirements));
    form.set('questionCount', String(input.questionCount));
    form.set('durationMinutes', String(input.durationMinutes));
    form.set('maxFollowUpQuestions', String(input.maxFollowUpQuestions));
    if (input.seedQuestions.length) {
      form.set('seedQuestions', JSON.stringify(input.seedQuestions));
    }
    form.set('vacancy', input.vacancy, input.vacancy.name);
    return required<PositionDetail>('/positions', {
      method: 'POST',
      body: form,
      signal,
    });
  },

  addCandidate(
    positionId: string,
    input: AddCandidateInput,
    signal?: AbortSignal,
  ): Promise<CandidateDetail> {
    const form = new FormData();
    form.set('name', input.name.trim());
    appendText(form, 'email', input.email);
    appendText(form, 'role', input.role);
    form.set('resume', input.resume, input.resume.name);
    return required<CandidateDetail>(
      `/positions/${encodeURIComponent(positionId)}/candidates`,
      { method: 'POST', body: form, signal },
    );
  },

  getCandidate(
    candidateId: string,
    signal?: AbortSignal,
  ): Promise<CandidateDetail> {
    return required<CandidateDetail>(
      `/candidates/${encodeURIComponent(candidateId)}`,
      { signal },
    );
  },

  async getCandidateQuestions(
    candidateId: string,
    signal?: AbortSignal,
  ): Promise<InterviewQuestion[]> {
    const payload = await required<
      InterviewQuestion[] | { items: InterviewQuestion[] }
    >(`/candidates/${encodeURIComponent(candidateId)}/questions`, { signal });
    return unwrapItems(payload);
  },

  updateCandidateQuestion(
    candidateId: string,
    questionId: string,
    update: Partial<
      Pick<InterviewQuestion, 'text' | 'topic' | 'competency' | 'orderIndex'>
    >,
    signal?: AbortSignal,
  ): Promise<InterviewQuestion> {
    return required<InterviewQuestion>(
      `/candidates/${encodeURIComponent(candidateId)}/questions/${encodeURIComponent(questionId)}`,
      jsonRequest(update, { method: 'PATCH', signal }),
    );
  },

  approveCandidateQuestions(
    candidateId: string,
    signal?: AbortSignal,
  ): Promise<Approval> {
    return required<Approval>(
      `/candidates/${encodeURIComponent(candidateId)}/questions/approve`,
      { method: 'POST', signal },
    );
  },

  resolveInvite(
    token: string,
    signal?: AbortSignal,
  ): Promise<InterviewBriefing> {
    return required<InterviewBriefing>(
      '/invites/resolve',
      jsonRequest({ token }, { method: 'POST', signal }),
    );
  },

  getCandidateInterview(
    signal?: AbortSignal,
  ): Promise<InterviewBriefing | null> {
    return request<InterviewBriefing>('/candidate/interview', {
      signal,
      allowNotFound: true,
    });
  },

  createPracticeSet(
    interviewId: string,
    signal?: AbortSignal,
  ): Promise<PracticeSet> {
    return required<PracticeSet>(
      `/interviews/${encodeURIComponent(interviewId)}/practice`,
      { method: 'POST', signal },
    );
  },

  startInterview(
    interviewId: string,
    consentToRecording: boolean,
    signal?: AbortSignal,
  ): Promise<InterviewState> {
    return required<InterviewState>(
      `/interviews/${encodeURIComponent(interviewId)}/start`,
      jsonRequest({ consentToRecording }, { method: 'POST', signal }),
    );
  },

  getInterviewState(
    interviewId: string,
    signal?: AbortSignal,
  ): Promise<InterviewState> {
    return required<InterviewState>(
      `/interviews/${encodeURIComponent(interviewId)}/state`,
      {
        signal,
      },
    );
  },

  getQuestionSpeech(
    interviewId: string,
    questionId: string,
    signal?: AbortSignal,
  ): Promise<Blob> {
    return requestBlob(
      `/interviews/${encodeURIComponent(interviewId)}/questions/${encodeURIComponent(questionId)}/speech`,
      signal,
    );
  },

  submitAnswer(
    interviewId: string,
    questionId: string,
    audio: Blob,
    video: Blob | null,
    durationSeconds?: number,
    signal?: AbortSignal,
  ): Promise<AnswerResult> {
    const form = new FormData();
    form.set('questionId', questionId);
    form.set(
      'audio',
      audio,
      blobFilename(audio, recordedFilename(audio, 'answer-audio')),
    );
    if (video) {
      form.set(
        'video',
        video,
        blobFilename(video, recordedFilename(video, 'answer-video')),
      );
    }
    if (durationSeconds !== undefined)
      form.set('durationSeconds', String(durationSeconds));
    form.set('language', 'ru');
    return required<AnswerResult>(
      `/interviews/${encodeURIComponent(interviewId)}/answers`,
      {
        method: 'POST',
        body: form,
        signal,
      },
    );
  },

  completeInterview(
    interviewId: string,
    signal?: AbortSignal,
  ): Promise<CompleteInterviewResult> {
    return required<CompleteInterviewResult>(
      `/interviews/${encodeURIComponent(interviewId)}/complete`,
      { method: 'POST', signal },
    );
  },

  getCandidateAnalysis(
    candidateId: string,
    signal?: AbortSignal,
  ): Promise<Analysis> {
    return required<Analysis>(
      `/candidates/${encodeURIComponent(candidateId)}/analysis`,
      { signal },
    );
  },

  getCandidateMedia(
    candidateId: string,
    signal?: AbortSignal,
  ): Promise<CandidateMedia> {
    return required<CandidateMedia>(
      `/candidates/${encodeURIComponent(candidateId)}/media`,
      { signal },
    );
  },

  rateInterviewQuestion(
    candidateId: string,
    questionId: string,
    rating: QuestionRating,
    signal?: AbortSignal,
  ): Promise<Analysis> {
    return required<Analysis>(
      `/candidates/${encodeURIComponent(candidateId)}/analysis/questions/${encodeURIComponent(questionId)}/review`,
      jsonRequest({ rating }, { method: 'PUT', signal }),
    );
  },

  revealAiRecommendation(
    candidateId: string,
    decision: InitialDecisionInput,
    signal?: AbortSignal,
  ): Promise<Analysis> {
    return required<Analysis>(
      `/candidates/${encodeURIComponent(candidateId)}/analysis/review`,
      jsonRequest(decision, { method: 'POST', signal }),
    );
  },

  saveCandidateDecision(
    candidateId: string,
    decision: DecisionInput,
    signal?: AbortSignal,
  ): Promise<Decision> {
    return required<Decision>(
      `/candidates/${encodeURIComponent(candidateId)}/decision`,
      jsonRequest(decision, { method: 'POST', signal }),
    );
  },

  getCandidateOutcome(signal?: AbortSignal): Promise<CandidateOutcome> {
    return required<CandidateOutcome>('/candidate/outcome', { signal });
  },
};
