import { beforeEach, describe, expect, it } from 'vitest';
import {
  captionIdempotencyKey,
  clearCaptionIdempotencyKey,
  clearCaptionTask,
  loadCaptionTask,
  saveCaptionTask,
} from './captionTaskState';

describe('caption task persistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('reconnects the last caption job across a page refresh', () => {
    saveCaptionTask('caption-123');
    expect(loadCaptionTask()).toBe('caption-123');
    clearCaptionTask();
    expect(loadCaptionTask()).toBe('');
  });

  it('keeps one submission key while a task is active', () => {
    const first = captionIdempotencyKey();
    expect(captionIdempotencyKey()).toBe(first);
    clearCaptionIdempotencyKey();
    expect(captionIdempotencyKey()).not.toBe(first);
  });
});
