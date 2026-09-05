export type UserRole = 'hr' | 'candidate';

export type User = {
  id: string;
  role: UserRole;
  name: string;
  email: string | null;
  candidateId: string | null;
  telegramUsername?: string | null;
  telegramConnected: boolean;
  roles?: UserRole[];
};

export type TelegramLogin = { botUrl: string; expiresAt: string };
export type TelegramLoginStatus = {
  status: 'pending' | 'expired' | 'authenticated';
  user?: User | null;
};

export type Session = {
  user: User;
  expiresAt: string;
};

export type ProcessingStatus =
  | 'not_started'
  | 'questions_draft'
  | 'invited'
  | 'in_progress'
  | 'recorded'
  | 'transcribing'
  | 'analyzing'
  | 'ready'
  | 'completed'
  | 'error';

export type HiringDecision = 'pending' | 'next_stage' | 'rejected';

export type CandidateSummary = {
  telegramUsername?: string | null;
  id: string;
  positionId: string;
  name: string;
  email: string | null;
  role: string;
  processingStatus: ProcessingStatus;
  hiringDecision: HiringDecision;
  createdAt: string;
  vacancyId?: string;
  vacancyTitle?: string;
  interviewPlanId?: string;
  interviewName?: string;
};

export type ContextDocument = {
  id: string;
  filename: string;
  text: string;
  status: 'ready';
  createdAt: string;
};

export type VacancyFields = {
  title: string;
  role: string;
  level: string;
  description: string;
  requirements: string[];
};

export type VacancyTemplate = VacancyFields & { id: string; adapted: boolean };
export type InterviewTemplate = {
  id: string;
  name: string;
  description: string;
  evaluates: string[];
  adapted: boolean;
};
export type EditableQuestion = {
  text: string;
  topic: string;
  competency: string;
};
export type InterviewSettings = {
  maxFollowUpQuestions: number;
  maxPersonalizedQuestions: number;
  durationMinutes: number;
};
export type InterviewPlanDraft = InterviewSettings & {
  templateId: string;
  name: string;
  description: string;
  evaluates: string[];
  questions: EditableQuestion[];
};
export type InterviewPlan = InterviewPlanDraft & {
  id: string;
  vacancyId: string;
  candidateCount: number;
  createdAt: string;
};
export type Vacancy = VacancyFields & {
  id: string;
  status: string;
  createdAt: string;
  candidateCount: number;
  interviewCount: number;
};
export type VacancyDetail = Vacancy & { interviews: InterviewPlan[] };
export type VacancyDraft = VacancyFields & {
  draftId?: string;
  templateId?: string;
};
export type InterviewPlanDetail = InterviewPlan & {
  vacancy: Vacancy;
  candidates: CandidateSummary[];
};
export type CandidateDraft = {
  telegramUsername?: string | null;
  draftId: string;
  name: string;
  email: string;
  role: string;
  questions: EditableQuestion[];
};

export type PositionSummary = {
  id: string;
  title: string;
  level: string;
  location: string;
  description: string;
  requirements: string[];
  questionCount: number;
  durationMinutes: number;
  maxFollowUpQuestions: number;
  status: string;
  createdAt: string;
  candidateCount: number;
};

export type QuestionKind = 'provided' | 'generated' | 'follow_up';

export type InterviewQuestion = {
  id: string;
  candidateId: string;
  parentQuestionId: string | null;
  orderIndex: number;
  kind: QuestionKind;
  text: string;
  topic: string;
  competency: string;
  sourceRefs: string[];
  followUpReason: string | null;
  status: string;
};

export type PublicQuestion = Pick<
  InterviewQuestion,
  'id' | 'text' | 'topic' | 'kind' | 'orderIndex' | 'followUpReason'
>;

export type CandidateDetail = CandidateSummary & {
  resumeFilename: string;
  questions: InterviewQuestion[];
};

export type PositionDetail = PositionSummary & {
  vacancyFilename: string;
  seedQuestions: string[];
  candidates: CandidateSummary[];
};

export type CreatePositionInput = {
  title: string;
  level: string;
  location: string;
  requirements: string[];
  questionCount: number;
  durationMinutes: number;
  maxFollowUpQuestions: number;
  seedQuestions: string[];
  vacancy: File;
};

export type AddCandidateInput = {
  name: string;
  email: string;
  role: string;
  resume: File;
};

export type Approval = {
  candidateId: string;
  interviewId: string;
  inviteToken: string;
  inviteUrl: string;
  expiresAt: string;
};

export type InterviewBriefing = {
  interviewId: string;
  candidateId: string;
  candidateName: string;
  positionId: string;
  positionTitle: string;
  topics: string[];
  questionCount: number;
  durationMinutes: number;
  status: string;
  currentQuestion: PublicQuestion | null;
  recordsAudio: boolean;
  recordsVideo: boolean;
  allowsFollowUps: boolean;
  evaluationNotice: string;
  humanReviewNotice: string;
};

export type InterviewState = {
  interviewId: string;
  status: string;
  startedAt: string | null;
  deadlineAt: string | null;
  remainingSeconds: number;
  currentQuestion: PublicQuestion | null;
  answeredQuestionIds: string[];
};

export type AnswerResult = {
  answerId: string;
  transcript: string;
  nextQuestion: PublicQuestion | null;
  followUpAdded: boolean;
  remainingSeconds: number;
};

export type AnalysisEvidence = {
  quote: string;
  label: 'confirmed' | 'incorrect' | 'check';
  rationale: string;
  start: number;
  end: number;
  clipStartSeconds: number | null;
  clipEndSeconds: number | null;
};

export type AnalysisItem = {
  id: string;
  orderIndex: number;
  kind: string;
  title: string;
  body: string;
  questionId: string | null;
  answerText: string | null;
  evidence: AnalysisEvidence[];
  requiredReview: boolean;
  reviewedSeconds: number;
  reviewComplete: boolean;
};

export type Analysis = {
  id: string;
  candidateId: string;
  version: string;
  score: number | null;
  confidence: number | null;
  recommendation: 'fit' | 'manual_review' | 'not_fit' | null;
  summary: string | null;
  strengths: string[];
  growthAreas: string[];
  unknowns: string[];
  skills: string[];
  nextQuestions: string[];
  items: AnalysisItem[];
  reviewComplete: boolean;
  recommendationLocked: boolean;
  createdAt: string;
};

export type CompleteInterviewResult = {
  interviewId: string;
  status: string;
};

export type MediaAsset = {
  id: string;
  kind: string;
  filename: string;
  contentType: string;
  sizeBytes: number;
  downloadUrl: string;
  playbackUrl: string | null;
  questionId: string | null;
};

export type CandidateMedia = {
  candidateId: string;
  assets: MediaAsset[];
};

export type ReviewEvent = {
  itemId: string;
  event: 'open' | 'heartbeat' | 'close';
  visible: boolean;
  focused: boolean;
};

export type ReviewProgress = {
  itemId: string;
  reviewedSeconds: number;
  reviewComplete: boolean;
  allItemsComplete: boolean;
};

export type DecisionInput = {
  status: Exclude<HiringDecision, 'pending'>;
  internalReason: string;
  candidateFeedback: string;
  internalReasonPasteEvents: number;
  internalReasonTypedCharacters: number;
};

export type Decision = {
  id: string;
  candidateId: string;
  status: Exclude<HiringDecision, 'pending'>;
  internalReason: string;
  candidateFeedback: string;
  decidedAt: string;
};

export type CandidateOutcome = {
  candidateId: string;
  status: HiringDecision;
  candidateFeedback: string | null;
  decidedAt: string | null;
};
