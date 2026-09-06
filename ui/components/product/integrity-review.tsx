'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  CircleHelp,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { integrityApi } from '@/lib/integrity-api';
import type {
  EvidencePlayback,
  IntegrityDecision,
  IntegrityFinding,
  IntegritySummary,
} from '@/lib/integrity-types';
import { formatEvidenceTime } from '@/lib/evidence-timeline';
import { EvidencePlayer } from './evidence-player';

const sourceLabels = {
  browser: 'Браузер',
  local_heuristic: 'Локальная эвристика · слабый сигнал',
  vlm: 'Мультимодальная модель',
};
const decisions: Array<{ value: IntegrityDecision; label: string }> = [
  { value: 'explained', label: 'Объяснено' },
  { value: 'confirmed', label: 'Нарушение подтверждено' },
  { value: 'needs_clarification', label: 'Нужно уточнить' },
];
const categoryLabels: Record<string, string> = {
  external_assistance: 'Возможное использование внешней подсказки',
  external_help: 'Возможное использование внешней подсказки',
  ai_assistance: 'Возможное использование внешней подсказки',
  tab_switch: 'Переключение вкладки',
  focus_loss: 'Потеря фокуса окна',
  face_absent: 'Лицо вне кадра',
  gaze_deviation: 'Изменение направления взгляда',
  head_deviation: 'Изменение положения головы',
  capture_stopped: 'Перерыв в записи',
};
const findingTitle = (finding: IntegrityFinding) =>
  categoryLabels[finding.category] || 'Эпизод для проверки';
const observabilityLabels: Record<string, string> = {
  clear: 'хорошая',
  partial: 'частичная',
  limited: 'ограниченная',
};
const percent = (part: number, total: number) =>
  total > 0 ? `${Math.min(100, Math.round((part / total) * 100))}%` : '—';

function FindingDecision({
  finding,
  onSave,
}: {
  finding: IntegrityFinding;
  onSave: (decision: IntegrityDecision, comment: string) => Promise<void>;
}) {
  const [decision, setDecision] = useState<IntegrityDecision | null>(
    finding.review?.decision || null,
  );
  const [comment, setComment] = useState(finding.review?.comment || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const busyRef = useRef(false);
  const save = async () => {
    if (!decision || busyRef.current) return;
    if (decision === 'confirmed' && !comment.trim()) {
      setError('Для подтверждения нарушения обязателен комментарий.');
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await onSave(decision, comment.trim());
      setNotice('Решение по эпизоду сохранено.');
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : 'Не удалось сохранить решение.',
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3 rounded-xl border p-3">
      <fieldset disabled={busy} className="flex flex-wrap gap-2">
        <legend className="mb-2 text-sm font-medium">Решение ревьюера</legend>
        {decisions.map((item) => (
          <Button
            key={item.value}
            type="button"
            size="sm"
            variant={decision === item.value ? 'default' : 'outline'}
            aria-pressed={decision === item.value}
            onClick={() => {
              setDecision(item.value);
              setNotice('');
            }}
          >
            {item.value === 'explained' ? (
              <CheckCircle2 />
            ) : item.value === 'needs_clarification' ? (
              <CircleHelp />
            ) : null}
            {item.label}
          </Button>
        ))}
      </fieldset>
      <label className="block text-sm">
        Комментарий
        {decision === 'confirmed' ? ' · обязательно' : ' · необязательно'}
        <Textarea
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          required={decision === 'confirmed'}
          disabled={busy}
          placeholder="Что вы увидели в записи и как объясняете эпизод"
          className="mt-2 min-h-20"
        />
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          size="sm"
          onClick={() => void save()}
          disabled={
            busy || !decision || (decision === 'confirmed' && !comment.trim())
          }
        >
          {busy ? <LoaderCircle className="animate-spin" /> : null}Сохранить
          решение
        </Button>
        {notice ? (
          <output className="text-sm text-muted-foreground">{notice}</output>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function IntegrityReview({ candidateId }: { candidateId: string }) {
  const [summary, setSummary] = useState<IntegritySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadingFinding, setLoadingFinding] = useState<string | null>(null);
  const [selected, setSelected] = useState<{
    findingId: string;
    playback: EvidencePlayback;
  } | null>(null);
  const aliveRef = useRef(true);
  const load = useCallback(async () => {
    try {
      const next = await integrityApi.summary(candidateId);
      if (aliveRef.current) {
        setSummary(next);
        setError('');
      }
    } catch (error) {
      if (aliveRef.current)
        setError(
          error instanceof Error
            ? error.message
            : 'Данные контроля пока недоступны.',
        );
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  }, [candidateId]);
  useEffect(() => {
    aliveRef.current = true;
    const initialLoad = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(initialLoad);
      aliveRef.current = false;
    };
  }, [load]);
  useEffect(() => {
    if (!summary?.pendingJobs && summary?.session?.status !== 'awaiting_upload') return;
    const timer = window.setInterval(() => void load(), 20_000);
    return () => window.clearInterval(timer);
  }, [summary?.pendingJobs, summary?.session?.status, load]);
  const open = async (finding: IntegrityFinding) => {
    if (!finding.videoAvailable || loadingFinding) return;
    setLoadingFinding(finding.id);
    setError('');
    try {
      const playback = await integrityApi.playback(candidateId, finding.id);
      if (!aliveRef.current) return;
      if (!playback.camera.length && !playback.screen.length)
        throw new Error('Видео этого интервала отсутствует');
      setSelected({ findingId: finding.id, playback });
    } catch (error) {
      if (aliveRef.current)
        setError(
          error instanceof Error ? error.message : 'Не удалось открыть запись.',
        );
    } finally {
      if (aliveRef.current) setLoadingFinding(null);
    }
  };
  const saveReview =
    (findingId: string) =>
    async (decision: IntegrityDecision, comment: string) => {
      await integrityApi.review(candidateId, findingId, decision, comment);
      const updated = await integrityApi.summary(candidateId);
      if (aliveRef.current) setSummary(updated);
    };
  const retry = async () => {
    setBusy(true);
    setError('');
    try {
      await integrityApi.retry(candidateId);
      await load();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : 'Не удалось повторить анализ.',
      );
    } finally {
      setBusy(false);
    }
  };
  if (loading)
    return (
      <output className="text-sm text-muted-foreground">
        Загружаем данные контроля записи…
      </output>
    );
  if (!summary?.enabled && !error) return null;
  const activeFinding = summary?.findings.find(
    (finding) => finding.id === selected?.findingId,
  );
  return (
    <section
      aria-label="Проверка спорных эпизодов"
      className="surface-card space-y-4 p-5 sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 font-semibold">
          <ShieldCheck className="size-5 text-accent-foreground" />
          Контроль записи и спорные эпизоды
        </h3>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void load()}
        >
          <RefreshCw />
          Обновить
        </Button>
      </div>
      <p className="text-sm leading-6 text-muted-foreground">
        Наблюдения помогают проверить запись. Обычный взгляд в сторону, смена
        вкладки, эхо или технический сбой сами по себе не подтверждают
        нарушение. Решения по эпизодам сохраняются отдельно от оценки
        компетенций.
      </p>
      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}
      {summary?.enabled ? (
        <>
          <dl className="grid gap-3 rounded-xl bg-muted/30 p-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">
                Покрытие записью · оба потока
              </dt>
              <dd className="mt-1 text-lg font-medium">
                {percent(
                  summary.recordingCoverage.jointMs,
                  summary.recordingCoverage.totalMs,
                )}
              </dd>
              <dd className="text-xs text-muted-foreground">
                Камера{' '}
                {percent(
                  summary.recordingCoverage.cameraMs,
                  summary.recordingCoverage.totalMs,
                )}{' '}
                · экран{' '}
                {percent(
                  summary.recordingCoverage.screenMs,
                  summary.recordingCoverage.totalMs,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                Покрытие анализом
              </dt>
              <dd className="mt-1 text-lg font-medium">
                {percent(
                  summary.analysisCoverage.analyzedMs,
                  summary.analysisCoverage.totalMs,
                )}
              </dd>
              <dd className="text-xs text-muted-foreground">
                {formatEvidenceTime(summary.analysisCoverage.analyzedMs)} из{' '}
                {formatEvidenceTime(summary.analysisCoverage.totalMs)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Стоимость API</dt>
              <dd className="mt-1 text-lg font-medium">
                ${Number(summary.costUsd || 0).toFixed(4)}
              </dd>
              {summary.costKnown === false ? (
                <dd className="text-xs text-muted-foreground">
                  Стоимость частично неизвестна
                </dd>
              ) : null}
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                Незавершённые задания
              </dt>
              <dd className="mt-1 text-lg font-medium">
                {summary.pendingJobs}
              </dd>
              <dd className="text-xs text-muted-foreground">
                С ошибкой: {summary.failedJobs}
              </dd>
            </div>
          </dl>
          {summary.failedJobs > 0 ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm text-muted-foreground">
                Часть записи не проанализирована. Оценка ответов сохранена.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void retry()}
              >
                {busy ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <RefreshCw />
                )}
                Повторить неуспешный анализ
              </Button>
            </div>
          ) : null}
          {!summary.findings.length ? (
            <p className="text-sm text-muted-foreground">
              {summary.session?.status === 'awaiting_upload'
                ? 'Загрузка записи не завершена. Материалы будут проанализированы после восстановления загрузки у кандидата; оценка ответов доступна независимо.'
                : summary.pendingJobs
                ? 'Анализ записи продолжается. Эпизоды появятся после обработки.'
                : 'Эпизодов для проверки пока нет. Это не гарантирует отсутствие внешней помощи.'}
            </p>
          ) : null}
          {summary.findings.map((finding) => (
            <article
              key={finding.id}
              className="space-y-3 rounded-xl border p-4"
            >
              <div>
                <p className="mb-1 text-xs text-muted-foreground">
                  {sourceLabels[finding.source]} ·{' '}
                  {formatEvidenceTime(finding.startMs)}–
                  {formatEvidenceTime(finding.endMs)}
                </p>
                <h4 className="font-medium">{findingTitle(finding)}</h4>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-6">
                {finding.observation}
              </p>
              <p className="text-sm">
                <span className="font-medium">Почему стоит проверить: </span>
                {finding.reason}
              </p>
              {finding.alternativeExplanations.length ? (
                <p className="text-sm text-muted-foreground">
                  <span className="font-medium">
                    Возможное обычное объяснение:{' '}
                  </span>
                  {finding.alternativeExplanations.join(' ')}
                </p>
              ) : null}
              <p className="text-sm text-muted-foreground">
                <span className="font-medium">Ограничения наблюдения: </span>
                {finding.limitations.length
                  ? finding.limitations.join(' ')
                  : 'Наблюдение требует проверки человеком.'}
                {finding.observability
                  ? ` Видимость: ${observabilityLabels[finding.observability] || finding.observability}.`
                  : ''}
              </p>
              {finding.videoAvailable ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={loadingFinding !== null}
                  onClick={() => void open(finding)}
                >
                  {loadingFinding === finding.id ? (
                    <LoaderCircle className="animate-spin" />
                  ) : (
                    <Play />
                  )}
                  Посмотреть фрагмент ·{' '}
                  {Math.max(
                    1,
                    Math.ceil((finding.endMs - finding.startMs) / 1000),
                  )}{' '}
                  секунд
                </Button>
              ) : (
                <output className="rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                  Видео этого интервала отсутствует
                </output>
              )}
              <FindingDecision
                key={`${finding.id}:${finding.review?.reviewedAt || 'new'}`}
                finding={finding}
                onSave={saveReview(finding.id)}
              />
            </article>
          ))}
        </>
      ) : null}
      {selected && activeFinding ? (
        <EvidencePlayer
          key={selected.findingId}
          playback={selected.playback}
          onClose={() => setSelected(null)}
          refreshManifest={() =>
            integrityApi.playback(candidateId, selected.findingId)
          }
          reviewControls={
            <FindingDecision
              key={`${activeFinding.id}:${activeFinding.review?.reviewedAt || 'new'}`}
              finding={activeFinding}
              onSave={saveReview(activeFinding.id)}
            />
          }
        />
      ) : null}
    </section>
  );
}
