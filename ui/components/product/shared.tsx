'use client';

import { ArrowLeft, Check, ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  candidateStatusCopy,
  testUsers,
  type CandidateStatus,
  type TestUser,
} from '@/lib/mock-data';

export function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="brand-mark" aria-hidden="true">
        <span />
        <span />
      </div>
      <span className="text-[17px] font-semibold tracking-[-0.02em]">Signal</span>
    </div>
  );
}

export function UserSwitcher({
  user,
  onChange,
}: {
  user: TestUser;
  onChange: (user: TestUser) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex min-h-11 items-center gap-2 rounded-full py-1 pl-1 pr-2 text-left outline-none transition hover:bg-black/[0.04] focus-visible:ring-2 focus-visible:ring-primary/30 dark:hover:bg-white/[0.06]">
        <span className="grid size-9 place-items-center rounded-full bg-[#e8e7ff] text-xs font-semibold text-[#4540a3]">
          {user.initials}
        </span>
        <span className="hidden min-w-0 sm:block">
          <span className="block max-w-36 truncate text-sm font-medium leading-tight">
            {user.name}
          </span>
          <span className="block text-[11px] leading-tight text-muted-foreground">
            {user.meta}
          </span>
        </span>
        <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="w-64 p-2">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-2">Тестовые пользователи</DropdownMenuLabel>
          {testUsers.map((item) => (
            <DropdownMenuItem
              key={item.id}
              onClick={() => onChange(item)}
              className="min-h-12 cursor-pointer gap-3 px-2"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold">
                {item.initials}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.name}</span>
                <span className="block text-xs text-muted-foreground">{item.meta}</span>
              </span>
              {item.id === user.id ? (
                <Check className="size-4 text-primary" aria-label="Выбран" />
              ) : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function StatusPill({
  status,
  candidateView = false,
}: {
  status: CandidateStatus;
  candidateView?: boolean;
}) {
  const copy = candidateStatusCopy[status];
  return (
    <span className={`status-pill ${copy.tone}`}>
      <span className="status-dot" aria-hidden="true" />
      {candidateView ? copy.candidateLabel : copy.label}
    </span>
  );
}

export function BackButton({ onClick, label = 'Назад' }: { onClick: () => void; label?: string }) {
  return (
    <Button variant="ghost" size="lg" onClick={onClick} className="-ml-2 mb-6 h-10 rounded-xl px-2.5">
      <ArrowLeft data-icon="inline-start" />
      {label}
    </Button>
  );
}

export function Avatar({
  initials,
  size = 'md',
}: {
  initials: string;
  size?: 'sm' | 'md' | 'lg';
}) {
  const sizing = {
    sm: 'size-9 text-[11px]',
    md: 'size-11 text-xs',
    lg: 'size-16 text-base',
  }[size];

  return (
    <span
      className={`grid shrink-0 place-items-center rounded-full bg-[#f0efff] font-semibold text-[#514bb5] ${sizing}`}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}
