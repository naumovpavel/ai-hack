'use client';

import Link from 'next/link';

import { useEffect, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Copy,
  Download,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react';
import { Brand } from './shared';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { API_BASE_URL, ApiError } from '@/lib/api';
import { copyText } from '@/lib/clipboard';
import {
  researchApi,
  type ResearchMetric,
  type ReasonBreakdown,
  type ResearchSummary,
} from '@/lib/research-api';

const number = (value: number | null) =>
  value === null
    ? '—'
    : value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });

function Metric({ title, metric }: { title: string; metric: ResearchMetric }) {
  return (
    <section className="surface-card p-6 sm:p-8">
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Доля ответивших «Да» среди завершивших оба опроса
      </p>
      <div className="mt-7 flex flex-wrap items-end gap-6">
        <div>
          <p className="text-sm text-muted-foreground">До знакомства</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums">
            {number(metric.beforePercent)}
            {metric.beforePercent !== null && '%'}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {metric.beforeYes} из {metric.pairs}
          </p>
        </div>
        <ArrowRight className="mb-6 size-5 text-muted-foreground" />
        <div>
          <p className="text-sm text-muted-foreground">После знакомства</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums">
            {number(metric.afterPercent)}
            {metric.afterPercent !== null && '%'}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {metric.afterYes} из {metric.pairs}
          </p>
        </div>
        <div className="rounded-xl bg-primary/5 px-5 py-3">
          <p className="text-sm text-muted-foreground">Изменение доли</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">
            {metric.deltaPp !== null && metric.deltaPp > 0 ? '+' : ''}
            {number(metric.deltaPp)}
            <span className="ml-2 text-sm font-normal">п. п.</span>
          </p>
        </div>
      </div>
      <div className="mt-6 grid grid-cols-2 gap-4 border-t pt-5 sm:grid-cols-4">
        {[
          ['Нет → Да', metric.noToYes],
          ['Да → Нет', metric.yesToNo],
          ['Да → Да', metric.yesToYes],
          ['Нет → Нет', metric.noToNo],
        ].map(([label, count]) => (
          <div key={label}>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className="mt-1 text-lg font-medium">{count}</p>
          </div>
        ))}
      </div>
      <p className="mt-5 text-sm text-muted-foreground">
        Сравниваются ответы одних и тех же людей. Незавершённые опросы не входят
        в расчёт.
      </p>
    </section>
  );
}
const hypothesisNames: Record<string, string> = {
  GENERAL: 'Общее недоверие к ИИ — без привязки к отдельной функции',
  PH1: 'Понятные основания оценки',
  PH3: 'Релевантные вопросы и уточнения',
  PH4: 'Понятный и удобный процесс',
  PH5: 'Проверка человеком',
  PH11: 'Полезная обратная связь',
};
function Reasons({ groups }: { groups: ReasonBreakdown[] }) {
  return (
    <section className="mt-10 space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">
          Причины и продуктовые гипотезы
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Частоты выбора причин внутри каждой ветки «Да / Нет». Знаменатель —
          число людей с этим ответом на соответствующем этапе. Можно выбрать
          несколько причин, поэтому сумма долей может превышать 100%.
        </p>
      </div>
      {groups.map((group) => (
        <div
          key={`${group.question}-${group.answer}`}
          className="surface-card p-5 sm:p-6"
        >
          <h3 className="mb-4 text-lg font-semibold">
            {group.question === 'trust' ? 'Доверие' : 'Готовность'}: ответ «
            {group.answer === 'yes' ? 'Да' : 'Нет'}»
          </h3>
          <Table aria-label="Причины до и после знакомства">
            <TableHeader>
              <TableRow>
                <TableHead>Причина / гипотеза</TableHead>
                <TableHead className="text-right">До</TableHead>
                <TableHead className="text-right">После</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {group.options.map((option) => (
                <TableRow key={option.id}>
                  <TableCell className="max-w-xl whitespace-normal py-4">
                    <span className="block leading-relaxed">
                      {option.label}
                    </span>
                    <span className="mt-1 block text-sm text-muted-foreground">
                      {option.hypothesis} · {hypothesisNames[option.hypothesis]}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {option.before} / {group.beforeRespondents}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {option.after} / {group.afterRespondents}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ))}
    </section>
  );
}

export function ResearchResults() {
  const [summary, setSummary] = useState<ResearchSummary | null>(null);
  const [error, setError] = useState('');
  const [authRequired, setAuthRequired] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState('');
  const [exporting, setExporting] = useState(false);
  const refresh = () => {
    setLoading(true);
    setError('');
    setAuthRequired(false);
    setRevision((value) => value + 1);
  };
  useEffect(() => {
    let cancelled = false;
    researchApi
      .summary()
      .then((result) => {
        if (!cancelled) setSummary(result);
      })
      .catch((caught) => {
        if (cancelled) return;
        setError(
          caught instanceof Error
            ? caught.message
            : 'Не удалось загрузить результаты.',
        );
        setAuthRequired(
          caught instanceof ApiError && [401, 403].includes(caught.status),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [revision]);

  const exportCsv = async () => {
    setExporting(true);
    setNotice('');
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/research/results.csv`,
        { credentials: 'include' },
      );
      if (!response.ok)
        throw new Error(
          'Не удалось выгрузить ответы. Войдите через Telegram как организатор исследования и повторите.',
        );
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = 'slopy-research.csv';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : 'Ошибка выгрузки.');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="min-h-dvh bg-background">
      <header className="topbar">
        <Link href="/" aria-label="Slopy — на главную">
          <Brand />
        </Link>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
        <Link
          href="/"
          className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm text-muted-foreground"
        >
          <ArrowLeft className="size-4" />В кабинет
        </Link>
        <h1 className="text-3xl font-semibold tracking-tight">
          Доверие к интервью с ИИ
        </h1>
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">
          Результаты двух опросов: до и после актуальной демонстрации Slopy.
        </p>
        {loading ? (
          <output className="mt-10 flex items-center gap-3">
            <LoaderCircle className="size-5 animate-spin" />
            Загружаем результаты…
          </output>
        ) : error ? (
          <div className="surface-card mt-8 space-y-4 p-6">
            <p role="alert">
              {authRequired
                ? 'Результаты доступны только организатору исследования. Войдите на главной странице через свой Telegram-аккаунт.'
                : error}
            </p>
            <div className="flex gap-4">
              {authRequired && (
                <Link
                  href="/"
                  className="inline-flex min-h-11 items-center text-accent-foreground"
                >
                  Войти в Slopy
                </Link>
              )}
              <Button variant="outline" onClick={refresh}>
                Повторить
              </Button>
            </div>
          </div>
        ) : (
          summary && (
            <>
              <div className="mt-7 flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={async () => {
                    const copied = await copyText(
                      `${window.location.origin}/research`,
                    );
                    setNotice(
                      copied
                        ? 'Ссылка на опрос скопирована.'
                        : `Ссылка на опрос: ${window.location.origin}/research`,
                    );
                  }}
                >
                  <Copy className="size-4" />
                  Ссылка для участников
                </Button>
                <Button
                  variant="outline"
                  disabled={exporting}
                  onClick={() => void exportCsv()}
                >
                  {exporting ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    <Download className="size-4" />
                  )}
                  Выгрузить ответы CSV
                </Button>
                <Button variant="ghost" onClick={refresh}>
                  <RefreshCw className="size-4" />
                  Обновить
                </Button>
              </div>
              {notice && <output className="mt-4 text-sm">{notice}</output>}
              <div className="my-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
                {[
                  ['Первый опрос сохранён', summary.started],
                  ['Прошли примеры', summary.demoViewed],
                  ['Завершили оба опроса', summary.completed],
                ].map(([label, count]) => (
                  <div key={label} className="rounded-xl border px-5 py-4">
                    <p className="text-sm text-muted-foreground">{label}</p>
                    <p className="mt-2 text-3xl font-semibold tabular-nums">
                      {count}
                    </p>
                  </div>
                ))}
              </div>
              {summary.started === 0 && (
                <p className="mb-8 rounded-xl bg-primary/5 p-5">
                  Ответов пока нет. Отправьте участникам ссылку на опрос — здесь
                  появятся реальные результаты.
                </p>
              )}
              <div className="grid gap-5">
                <Metric title="Доверие" metric={summary.trust} />
                <Metric
                  title="Готовность пройти интервью"
                  metric={summary.readiness}
                />
              </div>
              <Reasons groups={summary.reasons} />
              <p className="mt-6 text-sm leading-relaxed text-muted-foreground">
                Изменение — разница долей «Да» в процентных пунктах на одной и
                той же парной выборке. Это заявленные доверие и готовность, а не
                доказательство точности ИИ, реального прохождения интервью или
                причинного эффекта отдельных функций. PH1 здесь проверяется с
                позиции кандидата; в продуктовых документах исходная гипотеза
                относится к работе нанимающего менеджера. CSV содержит причины,
                свободные ответы, впечатление от прошлого опыта и демонстрации.
                Ответы по старой шкале и предыдущим демонстрациям сохранены в
                CSV с отдельными версиями и не входят в эти метрики. Участие с
                другого устройства может создать отдельный ответ.
              </p>
            </>
          )
        )}
      </main>
    </div>
  );
}
