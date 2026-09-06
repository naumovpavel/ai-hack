import { request } from './api';
import type { YesNo } from './research-catalog';

export const RESEARCH_DEMO_VERSION = 'signal-demo-v2';

export type Opinion = {
  trust: YesNo;
  trustFactors: string[];
  trustReason: string;
  readiness: YesNo;
  readinessFactors: string[];
  readinessReason: string;
};
export type Baseline = Opinion & {
  hadInterview: YesNo;
  hadAiInterview: YesNo;
  experienceLiked: YesNo | null;
  experienceFactors: string[];
  experienceReason: string;
};
export type Followup = Opinion & {
  solutionLiked: YesNo;
  solutionFactors: string[];
  solutionReason: string;
};
export type ResearchSession = {
  status: 'baseline' | 'demo' | 'complete';
  baseline: Baseline;
  followup: Followup | null;
};
export type ResearchMetric = {
  pairs: number;
  beforeYes: number;
  afterYes: number;
  beforePercent: number | null;
  afterPercent: number | null;
  deltaPp: number | null;
  noToYes: number;
  yesToNo: number;
  yesToYes: number;
  noToNo: number;
};
export type ReasonResult = {
  id: string;
  label: string;
  hypothesis: string;
  before: number;
  after: number;
};
export type ReasonBreakdown = {
  question: 'trust' | 'readiness';
  answer: YesNo;
  beforeRespondents: number;
  afterRespondents: number;
  options: ReasonResult[];
};
export type ResearchSummary = {
  started: number;
  demoViewed: number;
  completed: number;
  trust: ResearchMetric;
  readiness: ResearchMetric;
  reasons: ReasonBreakdown[];
};

async function surveyRequest<T>(path: string, token: string, body?: unknown) {
  const result = await request<T>(`/research/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      'X-Survey-Token': token,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!result) throw new Error('Сервер не вернул ответ. Повторите попытку.');
  return result;
}

export const researchApi = {
  session: (token: string) => surveyRequest<ResearchSession>('session', token),
  baseline: (token: string, body: Baseline) =>
    surveyRequest<ResearchSession>('baseline', token, body),
  demo: (token: string) =>
    surveyRequest<ResearchSession>('demo', token, {
      demoVersion: RESEARCH_DEMO_VERSION,
    }),
  complete: (token: string, body: Followup) =>
    surveyRequest<ResearchSession>('complete', token, body),
  summary: () => request<ResearchSummary>('/research/results'),
};
