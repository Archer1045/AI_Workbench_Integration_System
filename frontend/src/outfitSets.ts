import type {
  ClothingPreset,
  OutfitItemDraft,
  OutfitSetDefinition,
  OutfitSlot,
  PresetScope,
  PromptDocumentV1,
  StoredOutfitItem,
} from './api';
import {
  createPromptBlock,
  mergeTags,
  resolveCharacterTargets,
  updateCharacterBlock,
} from './promptDocument';

export const OUTFIT_SLOTS: ReadonlyArray<{ value: OutfitSlot; label: string }> = [
  { value: 'headwear', label: '头饰' },
  { value: 'underwear', label: '内衣' },
  { value: 'top', label: '上装' },
  { value: 'bottom', label: '下装' },
  { value: 'outerwear', label: '外套' },
  { value: 'full_body', label: '全身装' },
  { value: 'legwear', label: '袜' },
  { value: 'footwear', label: '鞋' },
  { value: 'accessory', label: '配饰' },
];

function containsTag(preset: ClothingPreset, values: string[]): boolean {
  const text = (preset.tags || []).join(' ').toLowerCase();
  return values.some((value) => text.includes(value));
}

export function inferOutfitSlot(preset: ClothingPreset): OutfitSlot {
  if (preset.part === '鞋' || preset.category === '鞋') return 'footwear';
  if (preset.part === '袜') return 'legwear';
  if (preset.part === '上装') {
    return containsTag(preset, ['jacket', 'coat', 'cardigan', 'blazer'])
      ? 'outerwear'
      : 'top';
  }
  if (preset.part === '下装') return 'bottom';
  if (preset.part === '内衣') {
    return containsTag(preset, ['bodysuit', 'leotard', 'catsuit', 'romper'])
      ? 'full_body'
      : 'underwear';
  }
  if (preset.part === '配饰') {
    return containsTag(preset, ['hat', 'headwear', 'veil', 'headpiece'])
      ? 'headwear'
      : 'accessory';
  }
  return 'full_body';
}

export function defaultOutfitCovers(
  slot: OutfitSlot,
  preset?: ClothingPreset,
): OutfitSlot[] {
  if (slot !== 'full_body') return [];
  if (preset && containsTag(preset, ['bodysuit', 'leotard', 'catsuit', 'romper'])) {
    return ['top', 'bottom', 'underwear'];
  }
  return ['top', 'bottom'];
}

export function outfitDraftItem(preset: ClothingPreset): OutfitItemDraft {
  const slot = inferOutfitSlot(preset);
  return {
    clothing_id: preset.id,
    slot,
    colors: {},
    layer_state: preset.layer_state || '完整',
    enabled: true,
    covers: defaultOutfitCovers(slot, preset),
  };
}

function textTags(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function storedOutfitItems(
  definition: OutfitSetDefinition,
): StoredOutfitItem[] {
  return definition.items
    .filter(
      (item): item is StoredOutfitItem =>
        'snapshot' in item && Boolean(item.snapshot),
    )
    .map((item, index) => ({
      ...item,
      order: item.order ?? index,
      enabled: item.enabled !== false,
      covers: item.covers || [],
      colors: item.colors || {},
    }));
}

export function applyOutfitSetToDocument(
  document: PromptDocumentV1,
  outfit: OutfitSetDefinition & { preset_id?: string; version?: number; content_hash?: string },
  activeCharacterId: string,
  scope: 'current' | 'all' | PresetScope,
): PromptDocumentV1 {
  const items = storedOutfitItems(outfit).filter((item) => item.enabled);
  const clothingItems = items.filter((item) => item.slot !== 'footwear');
  const footwearItems = items.filter((item) => item.slot === 'footwear');
  const clothingTags = mergeTags(
    ...clothingItems.map((item) => [
      ...item.snapshot.tags,
      ...textTags(item.snapshot.draw_prompt),
      ...Object.entries(item.colors || {}).map(
        ([slot, color]) => `${slot} color ${color}`,
      ),
    ]),
  );
  const footwearTags = mergeTags(
    ...footwearItems.map((item) => [
      ...item.snapshot.tags,
      ...textTags(item.snapshot.draw_prompt),
      ...Object.entries(item.colors || {}).map(
        ([slot, color]) => `${slot} color ${color}`,
      ),
    ]),
  );
  const itemRefs = items.map((item) => ({
    preset_id: `outfit_item:${item.clothing_id}`,
    version: item.clothing_version || 1,
  }));
  const outfitRef = {
    preset_id: `outfit_set:${outfit.preset_id || outfit.name}`,
    version: outfit.version || 1,
  };
  const targetIds = resolveCharacterTargets(document, activeCharacterId, scope);

  return targetIds.reduce(
    (next, characterId) =>
      updateCharacterBlock(next, characterId, 'clothing', (block) => ({
        ...block,
        tags: clothingTags,
        preset_refs: [outfitRef, ...itemRefs],
        footwear: createPromptBlock(
          'footwear',
          footwearTags,
          itemRefs.filter((ref) =>
            footwearItems.some(
              (item) => ref.preset_id === `outfit_item:${item.clothing_id}`,
            ),
          ),
        ),
        preset_snapshot: {
          ...block.preset_snapshot,
          outfit_set: {
            preset_id: outfit.preset_id || '',
            version: outfit.version || 1,
            name: outfit.name,
            content_hash: outfit.content_hash || '',
          },
          outfit_items: items.map((item) => ({
            clothing_id: item.clothing_id,
            slot: item.slot,
            colors: item.colors,
            layer_state: item.layer_state,
            order: item.order,
            covers: item.covers,
            clothing_version: item.clothing_version,
            snapshot: item.snapshot,
          })),
        },
        source: 'outfit_set',
      })),
    document,
  );
}
