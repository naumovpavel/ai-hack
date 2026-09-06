'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  Expand,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type {
  EvidencePlayback,
  EvidenceRange,
  EvidenceStream,
  EvidenceTranscript,
} from '@/lib/integrity-types';
import {
  clampTime,
  expandEvidenceRange,
  formatEvidenceTime,
  globalTimeMs,
  initialEvidenceRange,
  mediaTimeSeconds,
  needsCorrection,
  streamAt,
} from '@/lib/evidence-timeline';

type PlayerProps = {
  playback: EvidencePlayback;
  onClose: () => void;
  refreshManifest?: () => Promise<EvidencePlayback>;
  reviewControls?: ReactNode;
  /** Older answer recordings have no duration in the asset response. Read real metadata. */
  inferSingleStreamDuration?: boolean;
};

type PlaybackStatus = 'paused' | 'playing' | 'buffering' | 'refreshing';
type Controller = { seek: (timeMs: number) => void; pause: () => void };

function MediaPane({
  label,
  stream,
  videoRef,
  muted,
  isScreen = false,
  onError,
  onDuration,
  onEnded,
  transcript = [],
}: {
  label: string;
  stream: EvidenceStream | undefined;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  muted: boolean;
  isScreen?: boolean;
  onError: () => void;
  onDuration?: (duration: number) => void;
  onEnded: () => void;
  transcript?: EvidenceTranscript[];
}) {
  const captionUrl = useMemo(() => {
    const stamp = (ms: number) =>
      new Date(Math.max(0, ms)).toISOString().slice(11, 23);
    const cues = stream
      ? transcript
          .flatMap((entry) => entry.words)
          .filter(
            (word) =>
              word.startMs < stream.endMs && word.endMs > stream.startMs,
          )
          .map(
            (word) =>
              `${stamp(mediaTimeSeconds(stream, Math.max(word.startMs, stream.startMs)) * 1000)} --> ${stamp(mediaTimeSeconds(stream, Math.min(word.endMs, stream.endMs)) * 1000)}\n${word.text.replaceAll('<', '&lt;')}\n`,
          )
          .join('\n')
      : '';
    return `data:text/vtt;charset=utf-8,${encodeURIComponent(`WEBVTT\n\n${cues}`)}`;
  }, [stream, transcript]);
  useEffect(() => {
    const video = videoRef.current;
    // Restore src after React StrictMode's setup/cleanup replay.
    if (video && stream?.url && video.getAttribute('src') !== stream.url) {
      video.src = stream.url;
      video.load();
    }
    return () => {
      video?.pause();
      video?.removeAttribute('src');
      video?.load();
    };
  }, [stream?.url, stream?.mediaId, videoRef]);
  return (
    <div className="min-w-0 overflow-hidden rounded-xl border bg-black">
      <p className="flex items-center justify-between gap-2 bg-muted px-3 py-2 text-sm text-foreground">
        <span>{label}</span>
        <span className="text-xs text-muted-foreground">
          {isScreen
            ? 'Без второго звука'
            : muted
              ? 'Звук выключен'
              : 'Со звуком'}
        </span>
      </p>
      {stream ? (
        <video
          key={`${stream.mediaId}:${stream.url}`}
          ref={videoRef}
          src={stream.url}
          muted={muted}
          className="aspect-video max-h-[43vh] w-full object-contain"
          preload="auto"
          playsInline
          aria-label={label}
          onError={onError}
          onLoadedMetadata={(event) =>
            onDuration?.(event.currentTarget.duration)
          }
          onEnded={onEnded}
        >
          <track
            kind="captions"
            src={captionUrl}
            srcLang="ru"
            label="Расшифровка с временными метками"
          />
        </video>
      ) : (
        <output className="flex aspect-video items-center justify-center p-6 text-center text-sm text-white/80">
          {isScreen
            ? 'Нет записи экрана на этом участке'
            : 'Нет записи камеры на этом участке'}
        </output>
      )}
    </div>
  );
}

/** Mounted only while the dialog is open, so every close releases media and timers. */
function PlaybackSession({
  playback,
  onClose,
  refreshManifest,
  reviewControls,
  inferSingleStreamDuration,
}: PlayerProps) {
  const [manifest, setManifest] = useState(playback);
  const [range, setRange] = useState(() =>
    initialEvidenceRange(playback.episode, playback.context),
  );
  const [position, setPosition] = useState(
    () => initialEvidenceRange(playback.episode, playback.context).startMs,
  );
  const [status, setStatus] = useState<PlaybackStatus>('buffering');
  const [message, setMessage] = useState('');
  const [speed, setSpeed] = useState(1);
  const [muted, setMuted] = useState(false);
  const [refreshCount, setRefreshCount] = useState(0);
  const cameraRef = useRef<HTMLVideoElement>(null);
  const screenRef = useRef<HTMLVideoElement>(null);
  const screenContainerRef = useRef<HTMLDivElement>(null);
  const positionRef = useRef(position);
  const rangeRef = useRef(range);
  const wantedRef = useRef(true);
  const forceSeekRef = useRef(true);
  const aliveRef = useRef(true);
  const refreshingRef = useRef(false);
  const errorRetriedRef = useRef(false);
  const controller = useRef<Controller | null>(null);
  const speedRef = useRef(speed);
  const camera = streamAt(manifest.camera, position);
  const screen = streamAt(manifest.screen, position);
  const hasScreen = manifest.screen.length > 0;

  const seek = (timeMs: number) => {
    positionRef.current = clampTime(timeMs, rangeRef.current);
    forceSeekRef.current = true;
    cameraRef.current?.pause();
    screenRef.current?.pause();
    setPosition(positionRef.current);
    controller.current?.seek(positionRef.current);
  };
  const pause = useCallback(() => {
    wantedRef.current = false;
    controller.current?.pause();
    setStatus('paused');
  }, []);
  const play = () => {
    setMessage('');
    if (positionRef.current >= rangeRef.current.endMs)
      seek(rangeRef.current.startMs);
    wantedRef.current = true;
    forceSeekRef.current = true;
    setStatus('buffering');
  };
  const refresh = useCallback(
    async (automatic = false) => {
      if (!aliveRef.current || !refreshManifest || refreshingRef.current)
        return;
      if (automatic && errorRetriedRef.current) {
        pause();
        setMessage(
          'Видео не загрузилось. Обновите ссылки или попробуйте позже. Позиция сохранена.',
        );
        return;
      }
      if (automatic) errorRetriedRef.current = true;
      refreshingRef.current = true;
      cameraRef.current?.pause();
      screenRef.current?.pause();
      setStatus('refreshing');
      setMessage('Обновляем ссылки на запись. Позиция сохранена.');
      try {
        const updated = await refreshManifest();
        if (!aliveRef.current) return;
        positionRef.current = clampTime(positionRef.current, updated.context);
        setPosition(positionRef.current);
        setManifest(updated);
        const restoredRange = {
          startMs: clampTime(rangeRef.current.startMs, updated.context),
          endMs: clampTime(rangeRef.current.endMs, updated.context),
        };
        rangeRef.current = restoredRange;
        setRange(restoredRange);
        forceSeekRef.current = true;
        setRefreshCount((count) => count + 1);
        setMessage('Ссылки обновлены.');
      } catch (error) {
        if (aliveRef.current) {
          wantedRef.current = false;
          setStatus('paused');
          setMessage(
            error instanceof Error
              ? error.message
              : 'Не удалось обновить ссылки. Позиция сохранена.',
          );
        }
      } finally {
        refreshingRef.current = false;
      }
    },
    [pause, refreshManifest],
  );
  const mediaError = () => {
    if (refreshManifest) void refresh(true);
    else {
      pause();
      setMessage(
        'Не удалось загрузить видеофрагмент. Откройте материалы ещё раз.',
      );
    }
  };

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    const cameraVideo = cameraRef.current;
    const screenVideo = screenRef.current;
    const videos = [cameraVideo, screenVideo].filter(
      (video): video is HTMLVideoElement => !!video,
    );
    let running = false;
    let pendingPlay = false;
    let disposed = false;
    let previousTick = performance.now();
    const stop = () => {
      videos.forEach((video) => video.pause());
      running = false;
    };
    controller.current = {
      seek: () => {
        stop();
        forceSeekRef.current = true;
      },
      pause: stop,
    };
    forceSeekRef.current = true;
    const tick = () => {
      if (disposed || refreshingRef.current) {
        stop();
        previousTick = performance.now();
        return;
      }
      const now = performance.now();
      const delta = Math.min(150, now - previousTick);
      previousTick = now;
      videos.forEach((video) => {
        video.playbackRate = speedRef.current;
      });
      if (forceSeekRef.current) {
        if (videos.some((video) => video.readyState < 1)) {
          stop();
          if (wantedRef.current) setStatus('buffering');
          return;
        }
        stop();
        if (cameraVideo && camera)
          cameraVideo.currentTime = mediaTimeSeconds(
            camera,
            positionRef.current,
          );
        if (screenVideo && screen)
          screenVideo.currentTime = mediaTimeSeconds(
            screen,
            positionRef.current,
          );
        forceSeekRef.current = false;
      }
      if (!wantedRef.current) {
        stop();
        return;
      }
      if (videos.some((video) => video.readyState < 3 || video.seeking)) {
        stop();
        setStatus('buffering');
        return;
      }
      // A cancelled play() from a replaced stream can settle after the new stream
      // starts. Recover from that pause as well as browser-initiated suspension.
      if (running && videos.some((video) => video.paused)) running = false;
      if (!running) {
        if (pendingPlay) return;
        pendingPlay = true;
        void Promise.all(videos.map((video) => video.play()))
          .then(() => {
            pendingPlay = false;
            if (disposed || !wantedRef.current || refreshingRef.current) {
              stop();
              return;
            }
            running = true;
            previousTick = performance.now();
            setStatus('playing');
          })
          .catch(() => {
            pendingPlay = false;
            stop();
            if (!disposed && wantedRef.current) {
              wantedRef.current = false;
              setStatus('paused');
              setMessage('Нажмите Play, чтобы запустить запись со звуком.');
            }
          });
        return;
      }
      const next =
        cameraVideo && camera
          ? globalTimeMs(camera, cameraVideo.currentTime)
          : positionRef.current + delta * speedRef.current;
      const bounded = clampTime(next, rangeRef.current);
      if (
        screenVideo &&
        screen &&
        needsCorrection(
          screenVideo.currentTime,
          mediaTimeSeconds(screen, bounded),
        )
      ) {
        screenVideo.currentTime = mediaTimeSeconds(screen, bounded);
      }
      positionRef.current = bounded;
      setPosition(bounded);
      if (bounded >= rangeRef.current.endMs) {
        wantedRef.current = false;
        stop();
        setStatus('paused');
        // The camera is master; clamp it as well instead of leaving overrun audio.
        if (cameraVideo && camera)
          cameraVideo.currentTime = mediaTimeSeconds(
            camera,
            rangeRef.current.endMs,
          );
        if (screenVideo && screen)
          screenVideo.currentTime = mediaTimeSeconds(
            screen,
            rangeRef.current.endMs,
          );
      }
    };
    const interval = window.setInterval(tick, 40);
    tick();
    return () => {
      disposed = true;
      window.clearInterval(interval);
      stop();
      controller.current = null;
    };
  }, [camera, screen, refreshCount]);

  // Renew short-lived URLs while a reviewer is watching; media errors also trigger one retry.
  useEffect(() => {
    if (!manifest.expiresAt || !refreshManifest) return;
    const expires = new Date(manifest.expiresAt).getTime();
    if (!Number.isFinite(expires)) return;
    const timer = window.setTimeout(
      () => void refresh(),
      Math.max(1_000, expires - Date.now() - 20_000),
    );
    return () => window.clearTimeout(timer);
  }, [manifest.expiresAt, refreshCount, refresh, refreshManifest]);

  const changeRange = (next: EvidenceRange, restart = false) => {
    rangeRef.current = next;
    setRange(next);
    if (
      restart ||
      positionRef.current < next.startMs ||
      positionRef.current >= next.endMs
    )
      seek(next.startMs);
  };
  const useRealDuration = (seconds: number) => {
    if (!inferSingleStreamDuration || !Number.isFinite(seconds) || seconds <= 0)
      return;
    const endMs = seconds * 1_000;
    if (Math.abs(manifest.context.endMs - endMs) < 1) return;
    setManifest((current) => ({
      ...current,
      context: { startMs: 0, endMs },
      answerRange: { startMs: 0, endMs },
      camera: current.camera.map((stream) => ({ ...stream, endMs })),
    }));
    changeRange(initialEvidenceRange(manifest.episode, { startMs: 0, endMs }));
  };
  const endStream = (stream: EvidenceStream | undefined) => {
    if (!stream || !wantedRef.current) return;
    // Move to the next manifest segment (or an explicit gap); never retain a stale frame.
    positionRef.current = clampTime(stream.endMs, rangeRef.current);
    setPosition(positionRef.current);
    if (positionRef.current >= rangeRef.current.endMs) pause();
  };
  const duration = Math.max(1, range.endMs - range.startMs);
  const highlightStart = Math.max(
    0,
    ((manifest.episode.startMs - range.startMs) / duration) * 100,
  );
  const highlightEnd = Math.min(
    100,
    ((manifest.episode.endMs - range.startMs) / duration) * 100,
  );
  const visibleTranscript = manifest.transcript.filter(
    (entry) =>
      entry.startMs == null ||
      entry.endMs == null ||
      (entry.startMs <= range.endMs && entry.endMs >= range.startMs),
  );
  const observations = manifest.observations.filter(
    (entry) => position >= entry.startMs && position <= entry.endMs,
  );
  return (
    <>
      <DialogHeader>
        <DialogTitle className="pr-8">{manifest.title}</DialogTitle>
        <DialogDescription>
          Спорный участок: {formatEvidenceTime(manifest.episode.startMs)}–
          {formatEvidenceTime(manifest.episode.endMs)}. Таймкод — подпись к
          записи; решение принимает ревьюер.
        </DialogDescription>
      </DialogHeader>
      <div className={`grid gap-3 ${hasScreen ? 'lg:grid-cols-2' : ''}`}>
        <MediaPane
          label="Камера кандидата"
          stream={camera}
          videoRef={cameraRef}
          muted={muted}
          onError={mediaError}
          onDuration={useRealDuration}
          transcript={manifest.transcript}
          onEnded={() => endStream(camera)}
        />
        {hasScreen ? (
          <div ref={screenContainerRef} className="min-w-0 bg-background">
            <MediaPane
              label="Демонстрация экрана"
              stream={screen}
              videoRef={screenRef}
              muted
              isScreen
              onError={mediaError}
              onEnded={() => endStream(screen)}
            />
          </div>
        ) : null}
      </div>
      {!hasScreen && !inferSingleStreamDuration ? (
        <output className="text-sm text-muted-foreground">
          Нет записи экрана на этом участке
        </output>
      ) : null}
      <div className="space-y-3 rounded-xl border p-3">
        <div className="flex items-center gap-3">
          <Button
            type="button"
            size="icon"
            aria-label={status === 'paused' ? 'Play' : 'Пауза'}
            onClick={() => (wantedRef.current ? pause() : play())}
            disabled={status === 'refreshing'}
          >
            {status === 'buffering' || status === 'refreshing' ? (
              <LoaderCircle className="animate-spin" />
            ) : status !== 'paused' ? (
              <Pause />
            ) : (
              <Play />
            )}
          </Button>
          <div className="min-w-0 flex-1">
            <div className="relative flex h-6 items-center">
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 h-2 rounded bg-muted"
              >
                <div
                  className="absolute h-full rounded bg-amber-400/70"
                  style={{
                    left: `${highlightStart}%`,
                    width: `${Math.max(0, highlightEnd - highlightStart)}%`,
                  }}
                />
              </div>
              <input
                type="range"
                aria-label="Позиция в записи"
                min={range.startMs}
                max={range.endMs}
                step={50}
                value={position}
                onChange={(event) => seek(Number(event.target.value))}
                className="relative h-6 w-full cursor-pointer appearance-none bg-transparent accent-primary [&::-webkit-slider-runnable-track]:h-2 [&::-webkit-slider-runnable-track]:bg-transparent [&::-webkit-slider-thumb]:-mt-1 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary [&::-moz-range-track]:bg-transparent [&::-moz-range-thumb]:size-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-primary"
              />
            </div>
            <div className="flex justify-between gap-2 text-xs tabular-nums text-muted-foreground">
              <span>{formatEvidenceTime(position)}</span>
              <span>Выделен спорный участок</span>
              <span>{formatEvidenceTime(range.endMs)}</span>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={
              muted ? 'Включить звук камеры' : 'Выключить звук камеры'
            }
            onClick={() => setMuted(!muted)}
          >
            {muted ? <VolumeX /> : <Volume2 />}
          </Button>
          <label className="text-xs">
            Скорость
            <select
              aria-label="Скорость воспроизведения"
              value={speed}
              onChange={(event) => {
                speedRef.current = Number(event.target.value);
                setSpeed(speedRef.current);
              }}
              className="ml-1 rounded border bg-background p-2 text-sm"
            >
              {[0.5, 1, 1.5, 2].map((value) => (
                <option key={value} value={value}>
                  {String(value).replace('.', ',')}×
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              seek(range.startMs);
              play();
            }}
          >
            <RotateCcw />
            Повторить
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={range.startMs <= manifest.context.startMs}
            onClick={() =>
              changeRange(
                expandEvidenceRange(range, manifest.context, 'start'),
                true,
              )
            }
          >
            −10 с контекста
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={range.endMs >= manifest.context.endMs}
            onClick={() =>
              changeRange(expandEvidenceRange(range, manifest.context, 'end'))
            }
          >
            +10 с контекста
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              changeRange(manifest.answerRange || manifest.context, true)
            }
          >
            {manifest.answerRange
              ? 'Показать весь ответ'
              : 'Показать доступный контекст'}
          </Button>
          {hasScreen ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void screenContainerRef.current
                  ?.requestFullscreen?.()
                  .catch(() =>
                    setMessage('Браузер не разрешил полноэкранный режим.'),
                  );
              }}
            >
              <Expand />
              Развернуть экран
            </Button>
          ) : null}
        </div>
        {status === 'buffering' ? (
          <output className="text-sm text-muted-foreground">
            Ожидаем загрузку потоков. Оба видео приостановлены.
          </output>
        ) : null}
        {message ? (
          <output className="text-sm text-muted-foreground">{message}</output>
        ) : null}
        {refreshManifest && message ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={status === 'refreshing'}
            onClick={() => {
              errorRetriedRef.current = false;
              void refresh();
            }}
          >
            Обновить ссылки на запись
          </Button>
        ) : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="max-h-44 space-y-2 overflow-y-auto rounded-xl border p-3">
          <p className="text-sm font-medium">Расшифровка</p>
          {visibleTranscript.length ? (
            visibleTranscript.map((entry, index) => (
              <p
                key={`${entry.questionId || 'text'}:${index}`}
                className="whitespace-pre-wrap text-sm leading-6"
              >
                {entry.words.length
                  ? entry.words.map((word, wordIndex) => (
                      <span
                        key={wordIndex}
                        className={
                          position >= word.startMs && position < word.endMs
                            ? 'rounded bg-primary/20 font-medium'
                            : undefined
                        }
                      >
                        {word.text}{' '}
                      </span>
                    ))
                  : entry.text}
              </p>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">
              Расшифровка для этого участка отсутствует.
            </p>
          )}
          {visibleTranscript.some((entry) => !entry.words.length) ? (
            <p className="text-xs text-muted-foreground">
              Текст без временного выравнивания показан без синхронной
              подсветки.
            </p>
          ) : null}
        </div>
        <div className="max-h-44 space-y-2 overflow-y-auto rounded-xl border p-3">
          <p className="text-sm font-medium">Наблюдения для текущего момента</p>
          {observations.length ? (
            observations.map((entry, index) => (
              <p key={index} className="text-sm">
                {entry.text}
              </p>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">
              На этом участке отдельных наблюдений нет.
            </p>
          )}
        </div>
      </div>
      {reviewControls}
      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            pause();
            onClose();
          }}
        >
          Закрыть
        </Button>
      </div>
    </>
  );
}

export function EvidencePlayer(props: PlayerProps) {
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) props.onClose();
      }}
    >
      <DialogContent className="max-h-[94dvh] overflow-y-auto sm:max-w-[min(1200px,calc(100vw-2rem))]">
        <PlaybackSession {...props} />
      </DialogContent>
    </Dialog>
  );
}
