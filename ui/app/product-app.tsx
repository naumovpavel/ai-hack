'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, LoaderCircle, LogOut, Send } from 'lucide-react';
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
import { api } from '@/lib/api';
import type {
  InterviewBriefing,
  TelegramLogin,
  User,
  UserRole,
} from '@/lib/types';

function inviteTokenFromLocation() {
  const url = new URL(window.location.href);
  const query = url.searchParams.get('invite') || url.searchParams.get('token');
  if (query) return query;
  const match = url.pathname.match(/^\/(?:invite|interview)\/([^/]+)\/?$/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
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

const roleLabel = (role: UserRole) =>
  role === 'hr' ? 'Кабинет HR' : 'Кабинет кандидата';
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : 'Не удалось выполнить запрос. Попробуйте ещё раз.';

function clearPendingLogin() {
  try {
    sessionStorage.removeItem('signal.telegram.login');
  } catch {
    /* Optional storage. */
  }
}

export function AppShell() {
  const [loading, setLoading] = useState(true);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [briefing, setBriefing] = useState<InterviewBriefing | null>(null);
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [login, setLogin] = useState<TelegramLogin | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    try {
      if (login)
        sessionStorage.setItem('signal.telegram.login', JSON.stringify(login));
    } catch {
      /* The HttpOnly challenge cookie still protects login. */
    }
  }, [login]);
  const notify = useCallback((message: string) => {
    setNotice(message);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(''), 4000);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const bootstrap = async () => {
      setLoading(true);
      setError('');
      const token = inviteTokenFromLocation();
      setInviteToken(token);
      try {
        let user = await api.getSession(controller.signal);
        if (!user && !controller.signal.aborted) {
          try {
            const saved = sessionStorage.getItem('signal.telegram.login');
            if (saved) {
              const challenge = JSON.parse(saved) as TelegramLogin;
              if (
                Date.parse(challenge.expiresAt) > Date.now() &&
                /^https:\/\/t\.me\/[A-Za-z0-9_]+\?start=[A-Za-z0-9_-]+$/.test(
                  challenge.botUrl,
                )
              )
                setLogin(challenge);
              else clearPendingLogin();
            }
          } catch {
            /* Storage may be unavailable in a private browser. */
          }
        }
        if (!controller.signal.aborted)
          setCurrentUser(user?.telegramConnected ? user : null);
        let resolved: InterviewBriefing | null = null;
        if (user?.telegramConnected && token) {
          resolved = await api.resolveInvite(token, controller.signal);
          user = await api.getSession(controller.signal);
          if (!controller.signal.aborted) {
            clearInviteFromLocation();
            setInviteToken(null);
          }
        }
        if (controller.signal.aborted) return;
        // Only a Telegram-confirmed identity opens the product.
        setCurrentUser(user?.telegramConnected ? user : null);
        setBriefing(resolved);
      } catch (caught) {
        if (!controller.signal.aborted) setError(errorText(caught));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void bootstrap();
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (!login) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (Date.now() >= Date.parse(login.expiresAt)) {
        clearPendingLogin();
        setLogin(null);
        setError(
          'Время ожидания истекло. Нажмите «Войти через Telegram» ещё раз.',
        );
        return;
      }
      try {
        const result = await api.telegramLoginStatus(controller.signal);
        if (controller.signal.aborted) return;
        if (result.status === 'authenticated') {
          clearPendingLogin();
          setLogin(null);
          setReload((value) => value + 1);
          return;
        }
        if (result.status === 'expired') {
          clearPendingLogin();
          setLogin(null);
          setError('Ссылка для входа истекла. Начните вход ещё раз.');
          return;
        }
        setError('');
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(errorText(caught));
      }
      timer = setTimeout(() => void poll(), 1800);
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [login]);

  useEffect(
    () => () => {
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    },
    [],
  );

  const signIn = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    // Open during the click so mobile/desktop popup blockers allow the bot tab.
    const botWindow = window.open('about:blank', '_blank');
    if (botWindow) botWindow.opener = null;
    try {
      const challenge = await api.startTelegramLogin(
        inviteToken ? 'candidate' : 'hr',
        inviteToken,
      );
      setLogin(challenge);
      if (botWindow) botWindow.location.href = challenge.botUrl;
    } catch (caught) {
      botWindow?.close();
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const switchRole = async (role: UserRole) => {
    if (busy || currentUser?.role === role) return;
    setBusy(true);
    try {
      const session = await api.switchRole(role);
      setCurrentUser(session.user);
      setBriefing(null);
      setError('');
      clearInviteFromLocation();
      setInviteToken(null);
      notify(roleLabel(role));
    } catch (caught) {
      notify(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    setBusy(true);
    try {
      await api.logout();
      clearPendingLogin();
      setCurrentUser(null);
      setBriefing(null);
      setLogin(null);
      setError('');
    } catch (caught) {
      notify(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="topbar">
        <Brand />
        {currentUser ? (
          <DropdownMenu>
            <DropdownMenuTrigger
              disabled={busy}
              className="ml-auto flex min-h-11 items-center gap-3 rounded-full px-3 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-primary"
            >
              <span>
                <span className="block max-w-48 truncate text-sm font-medium">
                  {currentUser.name}
                </span>
                <span className="block text-sm text-muted-foreground">
                  {roleLabel(currentUser.role)}
                </span>
              </span>
              {busy ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <ChevronDown className="size-4" />
              )}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64 p-2">
              <DropdownMenuGroup>
                <DropdownMenuLabel>
                  {currentUser.telegramUsername
                    ? `@${currentUser.telegramUsername}`
                    : 'Мой аккаунт'}
                </DropdownMenuLabel>
                {(['hr', 'candidate'] as const).map((role) => (
                  <DropdownMenuItem
                    key={role}
                    onClick={() => void switchRole(role)}
                    className="min-h-11 cursor-pointer"
                  >
                    {roleLabel(role)}
                    {role === currentUser.role && (
                      <Check className="ml-auto size-4" />
                    )}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem
                  className="min-h-11 cursor-pointer"
                  onClick={() => void logout()}
                >
                  <LogOut className="size-4" /> Выйти
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </header>
      {loading ? (
        <main
          className="grid min-h-[70dvh] place-items-center"
          aria-busy="true"
        >
          <p className="flex items-center gap-3">
            <LoaderCircle className="size-5 animate-spin" /> Восстанавливаем
            сессию…
          </p>
        </main>
      ) : !currentUser ? (
        <main className="grid min-h-[calc(100dvh-68px)] place-items-center px-5 py-12">
          <section className="surface-card w-full max-w-md p-7 sm:p-10">
            <span className="grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary">
              <Send className="size-6" />
            </span>
            <h1 className="mt-6 text-2xl font-semibold">
              {inviteToken ? 'Войдите, чтобы пройти интервью' : 'Вход в Signal'}
            </h1>
            <p className="mt-3 text-base leading-relaxed text-muted-foreground">
              {login
                ? 'Нажмите «Старт» у бота и вернитесь сюда. Вход завершится автоматически.'
                : 'Откройте нашего бота и нажмите «Старт». Один аккаунт для кабинетов HR и кандидата.'}
            </p>
            {login ? (
              <>
                <a
                  href={login.botUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-6 flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 py-3 font-medium text-primary-foreground"
                >
                  <Send className="size-4" /> Открыть бота
                </a>
                <p
                  className="mt-4 flex items-center gap-2 text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  <LoaderCircle className="size-4 animate-spin" /> Ожидаем
                  подтверждение в Telegram
                </p>
                <Button
                  variant="ghost"
                  className="mt-3"
                  disabled={busy}
                  onClick={() => void signIn()}
                >
                  Получить новую ссылку
                </Button>
              </>
            ) : (
              <Button
                className="mt-6 w-full"
                size="lg"
                disabled={busy}
                onClick={() => void signIn()}
              >
                {busy ? (
                  <LoaderCircle className="size-4 animate-spin" />
                ) : (
                  <Send className="size-4" />
                )}{' '}
                Войти через Telegram
              </Button>
            )}
            {error && (
              <div className="mt-4 text-sm text-destructive" role="alert">
                {error}
                <Button
                  variant="ghost"
                  className="mt-2"
                  onClick={() => setReload((value) => value + 1)}
                >
                  Повторить
                </Button>
              </div>
            )}
          </section>
        </main>
      ) : error ? (
        <main className="mx-auto max-w-lg px-5 py-20">
          <h1 className="text-2xl font-semibold">
            Не удалось открыть интервью
          </h1>
          <p className="mt-4 text-base text-destructive" role="alert">
            {error}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={() => {
                clearInviteFromLocation();
                setInviteToken(null);
                setError('');
              }}
            >
              В кабинет
            </Button>
            <Button onClick={() => setReload((value) => value + 1)}>
              Повторить
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void logout()}
            >
              Войти в другой аккаунт
            </Button>
          </div>
        </main>
      ) : currentUser.role === 'hr' ? (
        <HrApp key={currentUser.id} notify={notify} />
      ) : currentUser.candidateId ? (
        <CandidateApp
          key={`${currentUser.id}:${currentUser.candidateId}`}
          candidateId={currentUser.candidateId}
          candidateName={currentUser.name}
          initialBriefing={briefing}
          notify={notify}
        />
      ) : (
        <main className="mx-auto max-w-xl px-5 py-20">
          <h1 className="text-2xl font-semibold">Кабинет кандидата</h1>
          <p className="mt-4 text-base text-muted-foreground">
            Пока нет приглашений на интервью. Перейдите по ссылке от рекрутера —
            интервью появится здесь.
          </p>
          <p className="mt-3 text-base text-muted-foreground">
            Уведомления будут приходить в Telegram.
          </p>
        </main>
      )}
      <div
        className={`app-notice ${notice ? 'app-notice-visible' : ''}`}
        aria-live="polite"
      >
        {notice}
      </div>
    </div>
  );
}
