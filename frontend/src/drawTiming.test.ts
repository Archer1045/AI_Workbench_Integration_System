import { describe, expect, it } from 'vitest';
import type { BatchJob } from './api';
import { batchElapsedSeconds, projectedDrawElapsed } from './drawTiming';

function job(overrides: Partial<BatchJob> = {}): BatchJob {
  return {
    batch_id: 'batch-1',
    status: 'running',
    total: 4,
    done: 1,
    current_group: 0,
    results: [],
    created_at: '2026-10-28T10:00:00+08:00',
    finished_at: null,
    ...overrides,
  };
}

describe('draw timing', () => {
  it('uses the server elapsed value while running', () => {
    expect(batchElapsedSeconds(job({ elapsed_seconds: 125 }))).toBe(125);
  });

  it('computes a stable finished duration from server timestamps', () => {
    expect(
      batchElapsedSeconds(
        job({
          status: 'done',
          finished_at: '2026-10-28T10:04:05+08:00',
        }),
      ),
    ).toBe(245);
  });

  it('projects smoothly from the latest server anchor', () => {
    const anchored = projectedDrawElapsed(120, 1_000, true, 4_500);
    expect(anchored).toBe(123);
    expect(projectedDrawElapsed(120, 1_000, false, 99_000)).toBe(120);
  });
});
