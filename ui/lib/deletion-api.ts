import { request } from '@/lib/api';

export type DeletionKind = 'candidate' | 'interview' | 'vacancy';

const resourcePaths: Record<DeletionKind, string> = {
  candidate: 'candidates',
  interview: 'interview-plans',
  vacancy: 'vacancies',
};

export async function deleteHiringResource(kind: DeletionKind, id: string) {
  await request<void>(`/${resourcePaths[kind]}/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}
