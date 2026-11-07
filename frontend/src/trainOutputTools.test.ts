import { describe, expect, it } from 'vitest';
import {
  addRecentCompareCombo,
  buildTrainingOutputGroups,
  toggleFavoriteName,
  trainingOutputFamily,
} from './trainOutputTools';

describe('train output tools', () => {
  it('groups raw, converted and checkpoint names into one family', () => {
    expect(trainingOutputFamily('my_lora.safetensors')).toBe('my_lora');
    expect(trainingOutputFamily('my_lora_comfy.safetensors')).toBe('my_lora');
    expect(trainingOutputFamily('my_lora-000002.safetensors')).toBe('my_lora');
    expect(trainingOutputFamily('my_lora-000002-state.safetensors')).toBe('my_lora');
  });

  it('filters, pins favorites and keeps the newest families first', () => {
    const groups = buildTrainingOutputGroups(
      [
        { name: 'older.safetensors', modified_at: '2026-10-20T10:00:00+08:00' },
        { name: 'newer_comfy.safetensors', modified_at: '2026-10-22T10:00:00+08:00' },
        { name: 'favorite.safetensors', modified_at: '2026-10-19T10:00:00+08:00' },
      ],
      { search: '', kind: 'all', favorites: ['favorite.safetensors'] },
    );
    expect(groups.map((group) => group.key)).toEqual(['favorite', 'newer', 'older']);
    expect(groups[0].favorite).toBe(true);
  });

  it('keeps favorite files first and then orders files by modification time', () => {
    const groups = buildTrainingOutputGroups(
      [
        { name: 'family-000001.safetensors', modified_at: '2026-10-20T10:00:00+08:00' },
        { name: 'family-000002.safetensors', modified_at: '2026-10-21T10:00:00+08:00' },
        { name: 'family.safetensors', modified_at: '2026-10-19T10:00:00+08:00' },
      ],
      { search: '', kind: 'all', favorites: ['family.safetensors'] },
    );
    expect(groups[0].items.map((item) => item.name)).toEqual([
      'family.safetensors',
      'family-000002.safetensors',
      'family-000001.safetensors',
    ]);
  });

  it('toggles favorites and keeps every selected name in recent compare combos', () => {
    expect(toggleFavoriteName(['a'], 'a')).toEqual([]);
    expect(toggleFavoriteName(['a'], 'b')).toEqual(['a', 'b']);
    const first = addRecentCompareCombo([], ['a', 'a', 'b', 'c', 'd', 'e']);
    expect(first).toEqual([['a', 'b', 'c', 'd', 'e']]);
    const repeated = addRecentCompareCombo(first, ['e', 'd', 'c', 'b', 'a']);
    expect(repeated).toHaveLength(1);
  });
});
