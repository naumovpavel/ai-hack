'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { CandidateApp } from '@/components/product/candidate-app';
import { HrApp } from '@/components/product/hr-app';
import { Brand, UserSwitcher } from '@/components/product/shared';
import { initialPositions, testUsers } from '@/lib/mock-data';

export function AppShell() {
  const [currentUser, setCurrentUser] = useState(testUsers[0]);
  const [positions, setPositions] = useState(() => structuredClone(initialPositions));
  const [notice, setNotice] = useState('');
  const noticeTimer = useRef<number | null>(null);

  const notify = useCallback((message: string) => {
    setNotice(message);
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(''), 3200);
  }, []);

  useEffect(() => {
    return () => {
      if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    };
  }, []);

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="topbar">
        <Brand />
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground md:inline-flex">
            Демо · мок-данные
          </span>
          <UserSwitcher user={currentUser} onChange={setCurrentUser} />
        </div>
      </header>

      {currentUser.role === 'hr' ? (
        <HrApp
          key={currentUser.id}
          positions={positions}
          setPositions={setPositions}
          notify={notify}
        />
      ) : (
        <CandidateApp
          key={currentUser.id}
          candidateId={currentUser.candidateId || ''}
          positions={positions}
          setPositions={setPositions}
          notify={notify}
        />
      )}

      <div className={`app-notice ${notice ? 'app-notice-visible' : ''}`} aria-live="polite">
        {notice}
      </div>
    </div>
  );
}
