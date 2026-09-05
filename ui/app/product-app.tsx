'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  LoaderCircle,
  RotateCcw,
  ServerCrash,
} from 'lucide-react';

import { CandidateApp } from '@/components/product/candidate-app';
import { HrApp } from '@/components/product/hr-app';
import { Brand } from '@/components/product/shared';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { API_BASE_URL, api } from '@/lib/api';
import type { InterviewBriefing, User } from '@/lib/types';

type LoadState = 'loading' | 'ready' | 'error';

function inviteTokenFromLocation() {
  const url = new URL(window.location.href);
  const queryToken =
    url.searchParams.get('invite') || url.searchParams.get('token');
  if (queryToken) return queryToken;
  const pathMatch = url.pathname.match(/^\/(?:invite|interview)\/([^/]+)\/?$/);
  return pathMatch?.[1] ? decodeURIComponent(pathMatch[1]) : null;
}

function clearInviteFromLocation() {
  const url = new URL(window.location.href);
  url.searchParams.delete('invite');
  url.searchParams.delete('token');
  if (/^\/(?:invite|interview)\//.test(url.pathname)) url.pathname = '/';
  window.history.replaceState(
    window.history.state,
    '',
    `${url.pathname}${url.search}${url.hash}`,
  );
}

function userInitials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('');
}

function userMeta(user: User) {
  return user.role === 'hr' ? 'Рекрутер · demo' : 'Кандидат';
}

function UserSwitcher({
  user,
  users,
  switching,
  onChange,
}: {
  user: User;
  users: User[];
  switching: boolean;
  onChange: (user: User) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex min-h-11 items-center gap-2 rounded-full py-1 pl-1 pr-2 text-left outline-none transition hover:bg-black/[0.04] focus-visible:ring-2 focus-visible:ring-primary/30"
        disabled={switching}
      >
        <span className="grid size-9 place-items-center rounded-full bg-[#e8e7ff] text-xs font-semibold text-[#4540a3]">
          {userInitials(user.name)}
        </span>
        <span className="hidden min-w-0 sm:block">
          <span className="block max-w-36 truncate text-sm font-medium leading-tight">
            {user.name}
          </span>
          <span className="block text-[11px] leading-tight text-muted-foreground">
            {switching ? 'Переключаем…' : userMeta(user)}
          </span>
        </span>
        {switching ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <ChevronDown className="size-4" />
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="w-64 p-2">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-2">
            Тестовые пользователи
          </DropdownMenuLabel>
          {users.map((item) => (
            <DropdownMenuItem
              key={item.id}
              className="min-h-12 cursor-pointer gap-3 px-2"
              onClick={() => onChange(item)}
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold">
                {userInitials(item.name)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {userMeta(item)}
                </span>
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

function LoadingView({ label }: { label: string }) {
  return (
    <main className="grid min-h-[calc(100dvh-68px)] place-items-center px-5 text-center">
      <div aria-live="polite" aria-busy="true">
        <LoaderCircle className="mx-auto size-8 animate-spin text-primary" />
        <p className="mt-4 text-sm font-medium">{label}</p>
      </div>
    </main>
  );
}

function ErrorView({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <main className="grid min-h-[calc(100dvh-68px)] place-items-center px-5 py-12">
      <div
        className="surface-card w-full max-w-lg p-7 text-center sm:p-10"
        role="alert"
      >
        <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-rose-50 text-rose-700">
          <ServerCrash className="size-5" />
        </span>
        <h1 className="mt-5 text-xl font-semibold">Backend недоступен</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {message}
        </p>
        <p className="mt-3 text-xs text-muted-foreground">
          Ожидаемый адрес API: <code>{API_BASE_URL}</code>
        </p>
        <Button className="mt-6" onClick={onRetry}>
          <RotateCcw data-icon="inline-start" />
          Повторить
        </Button>
      </div>
    </main>
  );
}

export function AppShell() {
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [loadMessage, setLoadMessage] = useState('Восстанавливаем сессию…');
  const [errorMessage, setErrorMessage] = useState('');
  const [users, setUsers] = useState<User[]>([]);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [briefing, setBriefing] = useState<InterviewBriefing | null>(null);
  const [switching, setSwitching] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState('');
  const noticeTimer = useRef<number | null>(null);

  const notify = useCallback((message: string) => {
    setNotice(message);
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(''), 4000);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const bootstrap = async () => {
      setLoadState('loading');
      setLoadMessage('Восстанавливаем сессию…');
      setErrorMessage('');
      try {
        const availableUsers = await api.listUsers(controller.signal);
        if (!availableUsers.length)
          throw new Error('Backend не вернул тестовых пользователей.');

        const inviteToken = inviteTokenFromLocation();
        let resolvedBriefing: InterviewBriefing | null = null;
        if (inviteToken) {
          setLoadMessage('Открываем персональное приглашение…');
          resolvedBriefing = await api.resolveInvite(
            inviteToken,
            controller.signal,
          );
        }

        let sessionUser = await api.getSession(controller.signal);
        if (!sessionUser) {
          sessionUser = (
            await api.setSession(availableUsers[0].id, controller.signal)
          ).user;
        }
        if (controller.signal.aborted) return;

        setUsers(
          availableUsers.some((item) => item.id === sessionUser.id)
            ? availableUsers
            : [...availableUsers, sessionUser],
        );
        setCurrentUser(sessionUser);
        setBriefing(resolvedBriefing);
        if (inviteToken) clearInviteFromLocation();
        setLoadState('ready');
      } catch (error) {
        if (controller.signal.aborted) return;
        setErrorMessage(
          error instanceof Error
            ? error.message
            : 'Не удалось загрузить приложение.',
        );
        setLoadState('error');
      }
    };
    void bootstrap();
    return () => controller.abort();
  }, [reloadKey]);

  useEffect(
    () => () => {
      if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    },
    [],
  );

  const switchUser = async (user: User) => {
    if (switching || user.id === currentUser?.id) return;
    setSwitching(true);
    try {
      const session = await api.setSession(user.id);
      clearInviteFromLocation();
      setBriefing(null);
      setCurrentUser(session.user);
      notify(`Вы вошли как ${session.user.name}`);
    } catch (error) {
      notify(
        error instanceof Error
          ? error.message
          : 'Не удалось переключить пользователя.',
      );
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="topbar">
        <Brand />
        {loadState === 'ready' && currentUser ? (
          <div className="ml-auto flex items-center gap-3">
            <UserSwitcher
              user={currentUser}
              users={users}
              switching={switching}
              onChange={(user) => void switchUser(user)}
            />
          </div>
        ) : null}
      </header>

      {loadState === 'loading' ? <LoadingView label={loadMessage} /> : null}
      {loadState === 'error' ? (
        <ErrorView
          message={errorMessage}
          onRetry={() => setReloadKey((key) => key + 1)}
        />
      ) : null}
      {loadState === 'ready' && currentUser ? (
        currentUser.role === 'hr' ? (
          <HrApp key={currentUser.id} notify={notify} />
        ) : (
          <CandidateApp
            key={currentUser.id}
            candidateId={currentUser.candidateId}
            candidateName={currentUser.name}
            initialBriefing={briefing}
            notify={notify}
          />
        )
      ) : null}

      <div
        className={`app-notice ${notice ? 'app-notice-visible' : ''}`}
        aria-live="polite"
      >
        {notice}
      </div>
    </div>
  );
}
