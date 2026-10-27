import type { BatchJob } from './api';

export function batchElapsedSeconds(job: BatchJob, nowMs = Date.now()): number {
  if (typeof job.elapsed_seconds === 'number' && Number.isFinite(job.elapsed_seconds)) {
    return Math.max(0, Math.floor(job.elapsed_seconds));
  }
  const startedAt = Date.parse(job.created_at || '');
  if (!Number.isFinite(startedAt)) return 0;
  const finishedAt = Date.parse(job.finished_at || '');
  const end = Number.isFinite(finishedAt) ? finishedAt : nowMs;
  return Math.max(0, Math.floor((end - startedAt) / 1000));
}

export function projectedDrawElapsed(
  baseSeconds: number,
  syncedAtMs: number,
  running: boolean,
  nowMs = Date.now(),
): number {
  const base = Math.max(0, Math.floor(baseSeconds || 0));
  if (!running || !syncedAtMs) return base;
  return base + Math.max(0, Math.floor((nowMs - syncedAtMs) / 1000));
}
