/** All offsets refer to milliseconds since the integrity session started. */
export type EvidenceRange = { startMs: number; endMs: number };
export type EvidenceStream = EvidenceRange & {
  mediaId: string;
  streamId: string;
  url: string;
  /** Offset inside the media file corresponding to startMs. */
  mediaOffsetMs: number;
};
export type EvidenceTranscript = {
  questionId?: string | null;
  text: string;
  startMs?: number | null;
  endMs?: number | null;
  words: Array<{ text: string; startMs: number; endMs: number }>;
};
export type EvidencePlayback = {
  findingId: string;
  title: string;
  episode: EvidenceRange;
  context: EvidenceRange;
  answerRange: EvidenceRange | null;
  camera: EvidenceStream[];
  screen: EvidenceStream[];
  transcript: EvidenceTranscript[];
  observations: Array<EvidenceRange & { source: string; text: string }>;
  expiresAt?: string;
};
export type IntegrityDecision =
  | 'explained'
  | 'confirmed'
  | 'needs_clarification';
export type IntegrityReviewDecision = {
  decision: IntegrityDecision;
  comment: string;
  reviewedAt: string;
};
export type IntegrityFinding = EvidenceRange & {
  id: string;
  interviewId: string;
  questionId: string | null;
  category: string;
  source: 'browser' | 'local_heuristic' | 'vlm';
  observation: string;
  reason: string;
  alternativeExplanations: string[];
  limitations: string[];
  evidenceRefs: Array<EvidenceRange & { mediaId: string }>;
  observability: string;
  videoAvailable: boolean;
  review: IntegrityReviewDecision | null;
};
export type IntegritySummary = {
  enabled: boolean;
  session: {
    id: string;
    interviewId: string;
    status: string;
    nextQuestionBlocked: boolean;
    elapsedMs: number;
  } | null;
  findings: IntegrityFinding[];
  recordingCoverage: {
    cameraMs: number;
    screenMs: number;
    jointMs: number;
    totalMs: number;
  };
  analysisCoverage: { analyzedMs: number; totalMs: number };
  costUsd: number;
  costKnown: boolean;
  pendingJobs: number;
  failedJobs: number;
};
