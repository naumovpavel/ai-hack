import React from 'react';
import { createRoot } from 'react-dom/client';
import { AnswerEvidence } from '@/components/product/answer-evidence';
import { IntegrityReview } from '@/components/product/integrity-review';
import { EvidencePlayer } from '@/components/product/evidence-player';
import '@/app/globals.css';
const reactRoot = createRoot(document.getElementById('root'));
const root = {
  render: (children) =>
    reactRoot.render(<React.StrictMode>{children}</React.StrictMode>),
};
window.mountPlayer = (manifest, options = {}) =>
  root.render(
    <EvidencePlayer
      playback={manifest}
      onClose={() => root.render(<p>Closed</p>)}
      refreshManifest={
        options.refresh
          ? async () => {
              window.refreshCalls = (window.refreshCalls || 0) + 1;
              return {
                ...manifest,
                expiresAt: new Date(Date.now() + 600000).toISOString(),
              };
            }
          : undefined
      }
    />,
  );
window.mountLegacy = (url) =>
  root.render(
    <AnswerEvidence
      notify={() => {}}
      answer={{ questionId: 'q1', answerText: 'слово проверка' }}
      items={[
        {
          id: 'item',
          title: 'Обоснование',
          body: 'Проверить слово',
          questionId: 'q1',
          evidence: [
            {
              quote: 'слово',
              start: 0,
              end: 5,
              label: 'check',
              clipStartSeconds: 1,
              clipEndSeconds: 2,
            },
          ],
        },
      ]}
      media={{
        candidateId: 'c1',
        assets: [
          { id: 'legacy', kind: 'video', questionId: 'q1', playbackUrl: url },
        ],
      }}
    />,
  );
window.mountReview = () =>
  root.render(<IntegrityReview candidateId="candidate-one" />);
window.fixtureReady = true;
