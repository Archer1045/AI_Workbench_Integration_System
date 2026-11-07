import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_DRAW_LORA_SELECTOR_STATE,
  filterDrawLoraItems,
  loadDrawLoraSelectorState,
  saveDrawLoraSelectorState,
} from './drawLoraSelectorState';

const items = [
  { name: 'style-a.safetensors', size_mb: 120, purpose: 'drawing' as const, compatible: true },
  { name: 'character-b.safetensors', size_mb: 240, purpose: 'unknown' as const, compatible: false, incompatible_reason: 'base mismatch' },
  { name: 'video-c.safetensors', size_mb: 300, purpose: 'video' as const, compatible: true },
];

describe('draw LoRA selector state', () => {
  it('falls back to defaults for missing or malformed storage', () => {
    expect(
      loadDrawLoraSelectorState({ getItem: () => '{broken' }),
    ).toEqual(DEFAULT_DRAW_LORA_SELECTOR_STATE);
  });

  it('loads and saves compact selector state', () => {
    const setItem = vi.fn();
    const state = {
      expanded: true,
      search: 'style',
      purpose: 'drawing' as const,
      compatibleOnly: false,
    };
    saveDrawLoraSelectorState(state, { setItem });
    expect(setItem).toHaveBeenCalledWith(
      'rider-studio:lora-selector-v1',
      JSON.stringify(state),
    );
    expect(
      loadDrawLoraSelectorState({
        getItem: () => JSON.stringify(state),
      }),
    ).toEqual(state);
  });

  it('filters video, purpose, compatibility and search without hiding results implicitly', () => {
    expect(
      filterDrawLoraItems(items, {
        search: '',
        purpose: 'all',
        compatibleOnly: true,
      }).map((item) => item.name),
    ).toEqual(['style-a.safetensors']);
    expect(
      filterDrawLoraItems(items, {
        search: 'base',
        purpose: 'unknown',
        compatibleOnly: false,
      }).map((item) => item.name),
    ).toEqual(['character-b.safetensors']);
  });
});
