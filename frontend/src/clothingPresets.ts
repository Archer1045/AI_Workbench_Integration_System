import type { ClothingPreset } from './api';

export type ClothingScope = 'all' | 'girlA' | 'girlB' | 'boyA' | 'boyB';

export const CLOTHING_SCOPE_OPTIONS: { label: string; value: ClothingScope }[] = [
  { label: '全部角色', value: 'all' },
  { label: '女A', value: 'girlA' },
  { label: '女B', value: 'girlB' },
  { label: '男A', value: 'boyA' },
  { label: '男B', value: 'boyB' },
];

const SCOPE_LABELS: Record<Exclude<ClothingScope, 'all'>, string> = {
  girlA: 'the first girl',
  girlB: 'the second girl',
  boyA: 'the first boy',
  boyB: 'the second boy',
};

export function formatClothingInsert(preset: ClothingPreset, scope: ClothingScope): string {
  const tags = preset.tags.join(', ');
  if (scope === 'all') {
    return preset.draw_prompt ? `${tags}, ${preset.draw_prompt}` : tags;
  }
  const label = SCOPE_LABELS[scope];
  if (preset.draw_prompt) {
    return `${label} ${preset.draw_prompt}`;
  }
  return `${label} wearing ${tags}`;
}
