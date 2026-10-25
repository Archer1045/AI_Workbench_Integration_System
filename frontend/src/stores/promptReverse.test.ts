import { beforeEach, describe, expect, it, vi } from 'vitest';

import { loadReverseState, promptStore, setReverseOptions } from './prompt';

describe('prompt reverse options', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('switches the reverse mode without throwing', () => {
    setReverseOptions('vlm', 0.35);
    expect(promptStore.reverseMode).toBe('vlm');
    setReverseOptions('wd14', 0.5);
    expect(promptStore.reverseMode).toBe('wd14');
    expect(promptStore.reverseThreshold).toBe(0.5);
  });

  it('persists the selection and reloads it', () => {
    setReverseOptions('wd14', 0.6);
    expect(loadReverseState()).toEqual({ reverseMode: 'wd14', reverseThreshold: 0.6 });
  });

  it('clamps the threshold into the caption range', () => {
    setReverseOptions('hybrid', 5);
    expect(promptStore.reverseThreshold).toBe(0.9);
    setReverseOptions('hybrid', 0);
    expect(promptStore.reverseThreshold).toBe(0.1);
  });

  it('loads the saved selection on first import', async () => {
    localStorage.setItem(
      'rider-studio:prompt-reverse-v1',
      JSON.stringify({ mode: 'wd14', threshold: 0.6 }),
    );
    vi.resetModules();
    const fresh = await import('./prompt');
    expect(fresh.promptStore.reverseMode).toBe('wd14');
    expect(fresh.promptStore.reverseThreshold).toBe(0.6);
  });
});
