import { describe, expect, it } from 'vitest';
import { finishedTasks, taskKey } from './taskNotifications';

describe('task notifications', () => {
  it('uses a stable job key and falls back to the task label', () => {
    expect(taskKey({ type: 'draw', label: 'AI 绘画', job_id: 'abc' })).toBe(
      'draw:abc',
    );
    expect(taskKey({ type: 'video', label: 'AI 视频' })).toBe('video:AI 视频');
  });

  it('returns only tasks that disappeared from the next snapshot', () => {
    const draw = { type: 'draw', label: 'AI 绘画', job_id: 'draw-1' };
    const train = { type: 'training', label: 'LoRA 训练', job_id: 'train-1' };
    expect(finishedTasks([draw, train], [train])).toEqual([draw]);
    expect(finishedTasks([], [draw])).toEqual([]);
  });
});
