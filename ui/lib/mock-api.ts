import {
  developingAnalysis,
  type Candidate,
  type HumanDecisionRecord,
  type Position,
} from '@/lib/mock-data';

type CreatePositionInput = Pick<
  Position,
  'title' | 'level' | 'location' | 'description' | 'requirements' | 'questions'
>;

type AddCandidateInput = Pick<Candidate, 'name' | 'email' | 'role' | 'resume'>;

const pause = (milliseconds: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

const makeId = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

export const mockApi = {
  async listPositions(seed: Position[]) {
    await pause(240);
    return structuredClone(seed);
  },

  async createPosition(input: CreatePositionInput): Promise<Position> {
    await pause(650);
    return {
      ...input,
      id: makeId('position'),
      status: 'active',
      createdAt: 'сегодня',
      candidates: [],
    };
  },

  async addCandidate(input: AddCandidateInput): Promise<Candidate> {
    await pause(520);
    const initials = input.name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('');

    return {
      ...input,
      id: makeId('candidate'),
      initials: initials || 'К',
      processingStatus: 'not_started',
      hiringDecision: 'pending',
    };
  },

  async saveDecision(
    status: HumanDecisionRecord['status'],
    reason: string,
    feedback: string,
  ): Promise<HumanDecisionRecord> {
    await pause(560);
    return {
      status,
      reason,
      feedback,
      decidedAt: new Intl.DateTimeFormat('ru-RU', {
        day: 'numeric',
        month: 'long',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date()),
    };
  },

  async saveInterviewAnswer(questionId: string) {
    await pause(420);
    return { questionId, saved: true, savedAt: Date.now() };
  },

  async submitInterview() {
    await pause(1450);
    return {
      processingStatus: 'ready' as const,
      analysis: structuredClone(developingAnalysis),
    };
  },
};
