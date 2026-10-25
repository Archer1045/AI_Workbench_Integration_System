import { describe, expect, it } from 'vitest';
import type { ClothingPreset } from './api';
import { formatClothingInsert } from './clothingPresets';

const preset: ClothingPreset = {
  id: 'test',
  category: '测试',
  label: '测试服装',
  translation: '测试',
  tags: ['school uniform', 'pleated skirt'],
  gender: '女',
  part: '全身',
  nsfw: false,
  rating: '普通',
};

describe('formatClothingInsert', () => {
  it('keeps plain tags for all characters', () => {
    expect(formatClothingInsert(preset, 'all')).toBe('school uniform, pleated skirt');
  });

  it('adds an English scope for a specific character', () => {
    expect(formatClothingInsert(preset, 'girlA')).toBe('the first girl wearing school uniform, pleated skirt');
    expect(formatClothingInsert(preset, 'boyB')).toBe('the second boy wearing school uniform, pleated skirt');
  });

  it('uses draw_prompt when scoped', () => {
    expect(formatClothingInsert({ ...preset, draw_prompt: 'wearing a white dress' }, 'girlB')).toBe(
      'the second girl wearing a white dress',
    );
  });
});
