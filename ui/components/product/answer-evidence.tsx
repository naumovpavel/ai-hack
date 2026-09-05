'use client';

import { useRef, useState } from 'react';
import { Play, RotateCcw, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type {
  AnalysisItem,
  AnalysisEvidence,
  CandidateMedia,
  MediaAsset,
} from '@/lib/types';

type EvidenceClip = {
  quote: string;
  startSeconds: number;
  endSeconds: number;
  asset: MediaAsset;
};

function vttTime(seconds: number) {
  const milliseconds = Math.max(0, Math.round(seconds * 1000));
  const hours = Math.floor(milliseconds / 3_600_000);
  const minutes = Math.floor((milliseconds % 3_600_000) / 60_000);
  const remainderSeconds = Math.floor((milliseconds % 60_000) / 1000);
  const remainderMilliseconds = milliseconds % 1000;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainderSeconds).padStart(2, '0')}.${String(remainderMilliseconds).padStart(3, '0')}`;
}

function clipCaptions(clip: EvidenceClip) {
  return `data:text/vtt;charset=utf-8,${encodeURIComponent(
    `WEBVTT\n\n${vttTime(clip.startSeconds)} --> ${vttTime(clip.endSeconds)}\n${clip.quote}\n`,
  )}`;
}

function EvidenceAnswer({
  answerText,
  evidence,
  video,
  onPlay,
}: {
  answerText: string;
  evidence: AnalysisEvidence[];
  video: MediaAsset | undefined;
  onPlay: (clip: EvidenceClip) => void;
}) {
  const candidates = [...evidence]
    .filter(
      (entry) =>
        Number.isInteger(entry.start) &&
        Number.isInteger(entry.end) &&
        entry.start >= 0 &&
        entry.end > entry.start &&
        entry.end <= answerText.length,
    )
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const ranges: AnalysisEvidence[] = [];
  let acceptedEnd = 0;
  candidates.forEach((entry) => {
    if (entry.start < acceptedEnd) return;
    ranges.push(entry);
    acceptedEnd = entry.end;
  });

  if (!ranges.length) {
    return <p className="whitespace-pre-wrap">{answerText}</p>;
  }

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  ranges.forEach((entry, index) => {
    if (entry.start > cursor) parts.push(answerText.slice(cursor, entry.start));
    const marked = entry.label === 'incorrect' || entry.label === 'check';
    const canPlay =
      marked &&
      Boolean(video?.playbackUrl) &&
      entry.clipStartSeconds !== null &&
      entry.clipEndSeconds !== null &&
      entry.clipEndSeconds > entry.clipStartSeconds;
    const className =
      entry.label === 'incorrect'
        ? 'rounded bg-rose-200 px-0.5 text-rose-900 ring-1 ring-rose-300'
        : entry.label === 'check'
          ? 'rounded bg-rose-100/55 px-0.5 text-rose-800 ring-1 ring-rose-200/70'
          : '';
    const text = answerText.slice(entry.start, entry.end);
    if (
      canPlay &&
      video &&
      entry.clipStartSeconds !== null &&
      entry.clipEndSeconds !== null
    ) {
      parts.push(
        <button
          key={`evidence-${index}`}
          type="button"
          className="inline cursor-pointer text-left align-baseline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          title="Воспроизвести этот фрагмент ответа"
          onClick={() =>
            onPlay({
              quote: entry.quote,
              startSeconds: entry.clipStartSeconds as number,
              endSeconds: entry.clipEndSeconds as number,
              asset: video,
            })
          }
        >
          <span className={className}>{text}</span>
          <Play
            className="ml-1 inline size-3 text-rose-700"
            aria-hidden="true"
          />
        </button>,
      );
    } else {
      parts.push(
        <span
          key={`evidence-${index}`}
          className={className}
          title={
            marked ? 'Временные метки для этого ответа недоступны' : undefined
          }
        >
          {text}
        </span>,
      );
    }
    cursor = entry.end;
  });
  if (cursor < answerText.length) parts.push(answerText.slice(cursor));

  return <p className="whitespace-pre-wrap">{parts}</p>;
}

export function AnswerEvidence({
  items,
  media,
  notify,
  answer,
}: {
  items: AnalysisItem[];
  media: CandidateMedia | null;
  notify: (message: string) => void;
  answer?: { questionId: string; answerText: string | null };
}) {
  const [evidenceClip, setEvidenceClip] = useState<EvidenceClip | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const playEvidenceClip = () => {
    if (!evidenceClip || !videoRef.current) return;
    videoRef.current.currentTime = evidenceClip.startSeconds;
    void videoRef.current.play().catch(() => undefined);
  };
  return (
    <div className={answer ? 'space-y-4' : 'mt-4 divide-y'}>
      {answer ? (
        <>
          <div className="rounded-xl border bg-muted/20 p-4 sm:p-5">
            <p className="mb-3 text-sm font-medium">Ответ кандидата</p>
            <div className="break-words text-base leading-7">
              {answer.answerText ? (
                <EvidenceAnswer
                  answerText={answer.answerText}
                  evidence={items.flatMap((item) => item.evidence)}
                  video={media?.assets.find(
                    (asset) =>
                      asset.kind === 'video' &&
                      asset.questionId === answer.questionId,
                  )}
                  onPlay={setEvidenceClip}
                />
              ) : (
                <p>
                  Записанного ответа нет. Вы можете выбрать «Не могу оценить».
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Sparkles className="size-4 text-primary" aria-hidden="true" />
            Аргументация ИИ по ответу
          </div>
          {!items.length ? (
            <p className="text-sm text-muted-foreground">
              Для этого ответа нет отдельного комментария ИИ.
            </p>
          ) : null}
        </>
      ) : null}
      {items.map((item) => (
        <div
          key={item.id}
          className={
            answer
              ? 'rounded-xl border border-primary/15 bg-primary/5 p-4'
              : 'py-4'
          }
        >
          <h4 className={answer ? 'text-sm font-medium' : 'font-medium'}>
            {item.title}
          </h4>
          <p className="mt-2 whitespace-pre-wrap break-words text-base leading-7">
            {item.body}
          </p>
          {answer ? null : item.answerText ? (
            <div className="mt-3 rounded-xl bg-muted/30 p-4 text-base leading-7">
              <p className="mb-2 text-sm text-muted-foreground">
                Ответ кандидата · выделения ИИ
              </p>
              <EvidenceAnswer
                answerText={item.answerText}
                evidence={item.evidence}
                video={media?.assets.find(
                  (asset) =>
                    asset.kind === 'video' &&
                    asset.questionId === item.questionId,
                )}
                onPlay={setEvidenceClip}
              />
            </div>
          ) : (
            item.evidence.map((entry, index) => (
              <blockquote
                key={index}
                className="mt-3 border-l-2 border-primary/30 pl-4 text-sm leading-6 text-muted-foreground"
              >
                {entry.quote}
              </blockquote>
            ))
          )}
        </div>
      ))}
      <Dialog
        open={evidenceClip !== null}
        onOpenChange={(open) => {
          if (!open) {
            videoRef.current?.pause();
            setEvidenceClip(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Фрагмент ответа кандидата</DialogTitle>
            <DialogDescription>
              {evidenceClip?.quote || 'Выделенный фрагмент ответа'}
            </DialogDescription>
          </DialogHeader>
          {evidenceClip?.asset.playbackUrl ? (
            <video
              ref={videoRef}
              className="max-h-[65vh] w-full rounded-xl bg-black"
              controls
              preload="metadata"
              src={evidenceClip.asset.playbackUrl}
              onLoadedMetadata={playEvidenceClip}
              onTimeUpdate={(event) => {
                if (
                  evidenceClip &&
                  event.currentTarget.currentTime >= evidenceClip.endSeconds
                ) {
                  event.currentTarget.pause();
                  event.currentTarget.currentTime = evidenceClip.endSeconds;
                }
              }}
              onPlay={(event) => {
                if (
                  evidenceClip &&
                  (event.currentTarget.currentTime <
                    evidenceClip.startSeconds ||
                    event.currentTarget.currentTime >= evidenceClip.endSeconds)
                ) {
                  event.currentTarget.currentTime = evidenceClip.startSeconds;
                }
              }}
              onError={() => notify('Не удалось загрузить видеофрагмент')}
            >
              <track
                default
                kind="captions"
                src={clipCaptions(evidenceClip)}
                srcLang="ru"
                label="Расшифровка ответа"
              />
            </video>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={playEvidenceClip}>
              <RotateCcw data-icon="inline-start" />
              Повторить фрагмент
            </Button>
            <Button type="button" onClick={() => setEvidenceClip(null)}>
              Закрыть
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
