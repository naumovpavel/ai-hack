import { jsonRequest, required, uploadForm } from '@/lib/api';
import type {
  Analysis,
  CandidateMedia,
  CompleteInterviewResult,
  Decision,
  DecisionInput,
  InitialDecisionInput,
  PracticeQuestion,
  PracticeSet,
  QuestionRating,
} from '@/lib/types';

export type PracticeSession = PracticeSet & {
  practiceId: string;
  interviewId: string;
  status: 'ready' | 'in_progress' | 'analyzing' | 'completed' | 'error';
  currentQuestion: PracticeQuestion | null;
  answeredQuestionIds: string[];
  remainingSeconds: number;
  startedAt: string | null;
  deadlineAt: string | null;
};

type PracticeAnswer = {
  answerId: string;
  transcript: string;
  nextQuestion: PracticeQuestion | null;
  remainingSeconds: number;
};

const path = (id: string) => `/practice/${encodeURIComponent(id)}`;

function filename(blob: Blob, kind: 'audio' | 'video') {
  const extension = blob.type.includes('mp4')
    ? 'mp4'
    : blob.type.includes('ogg')
      ? 'ogg'
      : 'webm';
  return `practice-${kind}.${extension}`;
}

export const practiceApi = {
  create(interviewId: string, signal?: AbortSignal) {
    return required<PracticeSession>(
      `/interviews/${encodeURIComponent(interviewId)}/practice`,
      { method: 'POST', signal },
    );
  },
  get(id: string, signal?: AbortSignal) {
    return required<PracticeSession>(path(id), { signal });
  },
  start(id: string) {
    return required<PracticeSession>(
      `${path(id)}/start`,
      jsonRequest({ consentToRecording: true }, { method: 'POST' }),
    );
  },
  answer(
    id: string,
    questionId: string,
    audio: Blob,
    video: Blob,
    durationSeconds: number,
    options: { signal?: AbortSignal; onProgress?: (percent: number) => void },
  ) {
    const form = new FormData();
    form.set('questionId', questionId);
    form.set('audio', audio, filename(audio, 'audio'));
    form.set('video', video, filename(video, 'video'));
    form.set('durationSeconds', String(durationSeconds));
    form.set('language', 'ru');
    return uploadForm<PracticeAnswer>(`${path(id)}/answers`, form, options);
  },
  complete(id: string) {
    return required<CompleteInterviewResult>(`${path(id)}/complete`, {
      method: 'POST',
    });
  },
  analysis(id: string, signal?: AbortSignal) {
    return required<Analysis>(`${path(id)}/analysis`, { signal });
  },
  media(id: string, signal?: AbortSignal) {
    return required<CandidateMedia>(`${path(id)}/media`, { signal });
  },
  rate(id: string, questionId: string, rating: QuestionRating) {
    return required<Analysis>(
      `${path(id)}/questions/${encodeURIComponent(questionId)}/rating`,
      jsonRequest({ rating }, { method: 'PUT' }),
    );
  },
  reveal(id: string, decision: InitialDecisionInput) {
    return required<Analysis>(
      `${path(id)}/review`,
      jsonRequest(decision, { method: 'POST' }),
    );
  },
  save(id: string, decision: DecisionInput) {
    return required<Decision>(
      `${path(id)}/decision`,
      jsonRequest(decision, { method: 'POST' }),
    );
  },
};
