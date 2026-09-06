import { request } from '@/lib/api';
import type {
  EvidencePlayback,
  IntegrityDecision,
  IntegritySummary,
  IntegrityReviewDecision,
} from '@/lib/integrity-types';

const candidatePath = (id: string) =>
  `/candidates/${encodeURIComponent(id)}/integrity`;
export const integrityApi = {
  summary: (id: string) => request<IntegritySummary>(candidatePath(id)),
  playback: async (
    id: string,
    findingId: string,
  ): Promise<EvidencePlayback> => {
    const manifest = await request<EvidencePlayback>(
      `${candidatePath(id)}/findings/${encodeURIComponent(findingId)}/playback`,
    );
    if (!manifest) throw new Error('Видео этого интервала отсутствует');
    return manifest;
  },
  review: (
    id: string,
    findingId: string,
    decision: IntegrityDecision,
    comment: string,
  ) =>
    request<IntegrityReviewDecision>(
      `${candidatePath(id)}/findings/${encodeURIComponent(findingId)}/review`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, comment }),
      },
    ),
  retry: (id: string) =>
    request(`${candidatePath(id)}/retry`, { method: 'POST' }),
};
