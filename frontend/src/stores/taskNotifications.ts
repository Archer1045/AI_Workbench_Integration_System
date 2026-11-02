import useStore from 'resso';
import type { BusyTask } from './busy';

const SOUND_KEY = 'rider-studio:task-notify-sound-v1';
const DESKTOP_KEY = 'rider-studio:task-notify-desktop-v1';

function readBoolean(key: string, fallback: boolean): boolean {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : value === '1';
  } catch {
    return fallback;
  }
}

function writeBoolean(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // Private browsing can reject local storage writes.
  }
}

export const taskNotificationStore = useStore({
  soundEnabled: readBoolean(SOUND_KEY, true),
  desktopEnabled: readBoolean(DESKTOP_KEY, false),
});

const notifiedTaskKeys = new Set<string>();

export function taskKey(task: BusyTask): string {
  return `${task.type}:${task.job_id || task.label}`;
}

export function finishedTasks(
  previous: BusyTask[],
  next: BusyTask[],
): BusyTask[] {
  const nextKeys = new Set(next.map(taskKey));
  return previous.filter((task) => !nextKeys.has(taskKey(task)));
}

export async function setDesktopNotificationsEnabled(
  enabled: boolean,
): Promise<boolean> {
  if (!enabled) {
    taskNotificationStore.desktopEnabled = false;
    writeBoolean(DESKTOP_KEY, false);
    return true;
  }
  if (typeof Notification === 'undefined') return false;
  const permission =
    Notification.permission === 'default'
      ? await Notification.requestPermission()
      : Notification.permission;
  const allowed = permission === 'granted';
  taskNotificationStore.desktopEnabled = allowed;
  writeBoolean(DESKTOP_KEY, allowed);
  return allowed;
}

export function setSoundNotificationsEnabled(enabled: boolean): void {
  taskNotificationStore.soundEnabled = enabled;
  writeBoolean(SOUND_KEY, enabled);
}

function playCompletionTone(): void {
  if (typeof window === 'undefined') return;
  const AudioContextClass =
    window.AudioContext ||
    (window as Window & { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!AudioContextClass) return;
  try {
    const context = new AudioContextClass();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = 'sine';
    oscillator.frequency.setValueAtTime(660, context.currentTime);
    oscillator.frequency.exponentialRampToValueAtTime(
      990,
      context.currentTime + 0.16,
    );
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.16, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.24);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.25);
    oscillator.addEventListener('ended', () => void context.close());
  } catch {
    // Browsers may block audio until the page receives a user gesture.
  }
}

export function notifyFinishedTasks(
  previous: BusyTask[],
  next: BusyTask[],
): BusyTask[] {
  const finished = finishedTasks(previous, next).filter((task) => {
    const key = taskKey(task);
    if (notifiedTaskKeys.has(key)) return false;
    notifiedTaskKeys.add(key);
    return true;
  });
  if (finished.length === 0) return [];

  if (taskNotificationStore.soundEnabled) playCompletionTone();
  if (
    taskNotificationStore.desktopEnabled &&
    typeof Notification !== 'undefined' &&
    Notification.permission === 'granted'
  ) {
    const labels = finished.map((task) => task.label).join('、');
    new Notification('AI 工作台任务已完成', {
      body:
        finished.length === 1
          ? `${labels}已结束`
          : `${finished.length} 个任务已结束：${labels}`,
      tag: `rider-studio-task-${finished.map(taskKey).join('-')}`,
    });
  }
  return finished;
}
