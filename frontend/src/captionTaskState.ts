const CAPTION_TASK_KEY = 'rider-studio:caption-task-v1';
const CAPTION_IDEMPOTENCY_KEY = 'rider-studio:caption-idempotency-v1';

export function saveCaptionTask(jobId: string): void {
  try {
    localStorage.setItem(CAPTION_TASK_KEY, JSON.stringify({ jobId }));
  } catch {
    // 隐私模式下不持久化任务。
  }
}

export function loadCaptionTask(): string {
  try {
    const parsed = JSON.parse(localStorage.getItem(CAPTION_TASK_KEY) || '{}') as {
      jobId?: string;
    };
    return parsed.jobId || '';
  } catch {
    return '';
  }
}

export function clearCaptionTask(): void {
  try {
    localStorage.removeItem(CAPTION_TASK_KEY);
  } catch {
    // 忽略存储失败
  }
}

export function captionIdempotencyKey(): string {
  try {
    const existing = localStorage.getItem(CAPTION_IDEMPOTENCY_KEY);
    if (existing) return existing;
    const created =
      globalThis.crypto?.randomUUID?.() ||
      `caption-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(CAPTION_IDEMPOTENCY_KEY, created);
    return created;
  } catch {
    return `caption-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}

export function clearCaptionIdempotencyKey(): void {
  try {
    localStorage.removeItem(CAPTION_IDEMPOTENCY_KEY);
  } catch {
    // 忽略存储失败
  }
}
