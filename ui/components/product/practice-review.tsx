'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, LoaderCircle, RotateCcw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { practiceApi } from '@/lib/practice-api';
import type { Analysis, CandidateMedia } from '@/lib/types';
import { HumanFirstReview } from './human-first-review';

export function PracticeReview({
  practiceId,
  onBack,
  notify,
}: {
  practiceId: string;
  onBack: () => void;
  notify: (message: string) => void;
}) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [media, setMedia] = useState<CandidateMedia | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let completionRequested = false;
    const load = async () => {
      try {
        const session = await practiceApi.get(practiceId, controller.signal);
        if (controller.signal.aborted) return;
        if (session.status === 'completed') {
          const result = await practiceApi.analysis(
            practiceId,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          setAnalysis(result);
          // The transcript remains usable if the media service is temporarily unavailable.
          const recordings = await practiceApi
            .media(practiceId, controller.signal)
            .catch(() => null);
          if (!controller.signal.aborted) setMedia(recordings);
          return;
        }
        if (session.status !== 'analyzing') {
          if (completionRequested) {
            throw new Error(
              'Не удалось завершить анализ тренировки. Повторите попытку.',
            );
          }
          completionRequested = true;
          await practiceApi.complete(practiceId);
          if (controller.signal.aborted) return;
        }
        timer = window.setTimeout(() => void load(), 2500);
      } catch (caught) {
        if (!controller.signal.aborted) {
          setError(
            caught instanceof Error
              ? caught.message
              : 'Не удалось загрузить разбор тренировки.',
          );
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [practiceId, attempt]);

  return (
    <main className="candidate-shell max-w-6xl">
      <Button variant="ghost" className="-ml-2 mb-6" onClick={onBack}>
        <ArrowLeft data-icon="inline-start" /> К подготовке
      </Button>
      <p className="eyebrow">Мок-интервью</p>
      <h1 className="page-title">Разбор вашей тренировки</h1>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted-foreground">
        Сначала оцените свои ответы и запишите выводы. Затем откроется анализ
        ИИ: сравните оценки и сохраните план подготовки.
      </p>
      <div className="my-5 flex items-start gap-3 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
        <ShieldCheck className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <span>
          Тренировка доступна только вам. Её ответы и оценки не передаются
          рекрутеру. Настоящее интервью ещё нужно пройти отдельно.
        </span>
      </div>
      {analysis ? (
        <HumanFirstReview
          key={practiceId}
          candidate={{ id: analysis.candidateId }}
          analysis={analysis}
          media={media}
          mode="practice"
          actions={{
            rate: (questionId, rating) =>
              practiceApi.rate(practiceId, questionId, rating),
            reveal: (decision) => practiceApi.reveal(practiceId, decision),
            save: (decision) => practiceApi.save(practiceId, decision),
          }}
          notify={notify}
          onDecision={() => undefined}
        />
      ) : (
        <section className="surface-card p-7 text-center" aria-live="polite">
          {error ? (
            <>
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
              <Button
                className="mt-4"
                onClick={() => {
                  setError('');
                  setAttempt((value) => value + 1);
                }}
              >
                <RotateCcw data-icon="inline-start" /> Повторить загрузку
                разбора
              </Button>
            </>
          ) : (
            <>
              <LoaderCircle className="mx-auto size-8 animate-spin text-accent-foreground" />
              <h2 className="mt-4 font-semibold">Готовим разбор тренировки</h2>
              <p className="mx-auto mt-2 max-w-lg text-sm text-muted-foreground">
                Ответы сохранены. Камера и микрофон выключены. Можно вернуться к
                подготовке и открыть разбор позже.
              </p>
            </>
          )}
        </section>
      )}
    </main>
  );
}
