'use client';
import { useEffect } from 'react';
import type {
  IntegrityEvent,
  IntegrityEventType,
} from '@/lib/integrity-capture-api';

export type RecordIntegrityEvent = (
  type: IntegrityEventType,
  payload?: Record<string, unknown>,
  durationMs?: number,
  offsetMs?: number,
  questionId?: string,
) => void;

/** Signals describe observability; none is a verdict or a competency score. */
export function useIntegrityEvents(
  active: boolean,
  camera: MediaStream | null,
  screen: MediaStream | null,
  record: RecordIntegrityEvent,
  checkHealth: () => void,
) {
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    const visibility = () =>
      record('visibility_change', {
        visibilityState: document.visibilityState,
      });
    const blur = () =>
      record('focus_lost', {
        alternativeExplanation:
          'Системное окно, переключение приложения или обычная работа браузера.',
      });
    const focus = () => record('focus_gained');
    const devices = async () => {
      try {
        const list = await navigator.mediaDevices.enumerateDevices();
        if (!disposed)
          record('device_change', {
            audioInputs: list.filter((item) => item.kind === 'audioinput')
              .length,
            videoInputs: list.filter((item) => item.kind === 'videoinput')
              .length,
          });
      } catch {
        if (!disposed) record('technical_error');
      }
      checkHealth();
    };
    const display = () => {
      const browserScreen = window.screen as Screen & { isExtended?: boolean };
      record('display_info', {
        isExtended:
          typeof browserScreen.isExtended === 'boolean'
            ? browserScreen.isExtended
            : null,
        displayCount: null,
        limitation:
          'Браузер может не сообщать количество экранов. Демонстрируется только выбранный полный экран.',
      });
    };
    const listeners: Array<() => void> = [];
    for (const [kind, media] of [
      ['camera', camera],
      ['screen', screen],
    ] as const) {
      for (const track of media?.getTracks() || []) {
        for (const eventName of ['ended', 'mute', 'unmute']) {
          const listener = () => {
            record('capture_state', {
              kind,
              trackKind: track.kind,
              event: eventName,
              technical: true,
            });
            checkHealth();
          };
          track.addEventListener(eventName, listener);
          listeners.push(() => track.removeEventListener(eventName, listener));
        }
      }
    }
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('blur', blur);
    window.addEventListener('focus', focus);
    navigator.mediaDevices.addEventListener('devicechange', devices);
    const screenEvents = window.screen as Screen & EventTarget;
    screenEvents.addEventListener?.('change', display);
    visibility();
    display();
    // Query detailed screen count only if permission was previously granted.
    void navigator.permissions
      ?.query({ name: 'window-management' as PermissionName })
      .then(async (permission) => {
        const supported = window as unknown as {
          getScreenDetails?: () => Promise<
            EventTarget & { screens: unknown[] }
          >;
        };
        if (
          disposed ||
          permission.state !== 'granted' ||
          !supported.getScreenDetails
        )
          return;
        const details = await supported.getScreenDetails();
        if (disposed) return;
        const update = () =>
          record('display_info', {
            displayCount: details.screens.length,
            source: 'window-management',
          });
        update();
        details.addEventListener('screenschange', update);
        listeners.push(() =>
          details.removeEventListener('screenschange', update),
        );
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('blur', blur);
      window.removeEventListener('focus', focus);
      navigator.mediaDevices.removeEventListener('devicechange', devices);
      screenEvents.removeEventListener?.('change', display);
      for (const remove of listeners) remove();
    };
  }, [active, camera, screen, record, checkHealth]);
}

export type { IntegrityEvent, IntegrityEventType };
