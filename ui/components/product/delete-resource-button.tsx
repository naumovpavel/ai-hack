'use client';

import { useState } from 'react';
import { LoaderCircle, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { deleteHiringResource, type DeletionKind } from '@/lib/deletion-api';

const labels: Record<DeletionKind, string> = {
  candidate: 'кандидата',
  interview: 'интервью',
  vacancy: 'вакансию',
};

export function DeleteResourceButton({
  kind,
  id,
  name,
  candidateCount = 0,
  interviewCount = 0,
  compact = false,
  onDeleted,
}: {
  kind: DeletionKind;
  id: string;
  name: string;
  candidateCount?: number;
  interviewCount?: number;
  compact?: boolean;
  onDeleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');
  const label = labels[kind];
  const remove = async () => {
    setDeleting(true);
    setError('');
    try {
      await deleteHiringResource(kind, id);
      setOpen(false);
      onDeleted();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Не удалось удалить. Попробуйте ещё раз.',
      );
    } finally {
      setDeleting(false);
    }
  };
  return (
    <>
      <Button
        variant={compact ? 'ghost' : 'outline'}
        size={compact ? 'icon' : 'default'}
        className="shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
        aria-label={`Удалить ${label} «${name}»`}
        title={`Удалить ${label}`}
        onClick={() => {
          setError('');
          setOpen(true);
        }}
      >
        <Trash2 aria-hidden="true" />
        {!compact ? `Удалить ${label}` : null}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!deleting) setOpen(value);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить {label}?</DialogTitle>
            <DialogDescription>
              Удаление «{name}» нельзя будет отменить.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm leading-relaxed text-muted-foreground">
            {kind !== 'candidate' ? (
              <p>
                Вместе с {kind === 'vacancy' ? 'вакансией' : 'интервью'} будут
                удалены
                {kind === 'vacancy' ? ` интервью: ${interviewCount},` : ''}{' '}
                кандидаты: {candidateCount}.
              </p>
            ) : null}
            <p>
              Будут удалены вопросы, ответы, записи, результаты анализа и
              решения HR, включая результаты мок-интервью. Действующие ссылки
              приглашений перестанут работать, текущее прохождение интервью
              будет прервано.
            </p>
            <p>Аккаунты пользователей сохранятся.</p>
          </div>
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={deleting}
              onClick={() => setOpen(false)}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              disabled={deleting}
              onClick={() => void remove()}
            >
              {deleting ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <Trash2 />
              )}
              {deleting ? 'Удаляем…' : `Удалить ${label}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
