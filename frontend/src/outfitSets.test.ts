import { describe, expect, it } from 'vitest';
import type {
  ClothingPreset,
  OutfitSetDefinition,
  StoredOutfitItem,
} from './api';
import {
  applyOutfitSetToDocument,
  defaultOutfitCovers,
  inferOutfitSlot,
  outfitDraftItem,
} from './outfitSets';
import {
  addCharacter,
  createEmptyStructuredDocument,
  updateCharacterBlock,
  updateGlobalBlock,
} from './promptDocument';

function clothing(
  overrides: Partial<ClothingPreset> = {},
): ClothingPreset {
  return {
    id: 'test_top',
    category: '日常服装',
    label: '测试上衣',
    translation: '测试',
    tags: ['test top'],
    gender: '女',
    part: '上装',
    nsfw: false,
    rating: '普通',
    ...overrides,
  };
}

function item(
  id: string,
  slot: StoredOutfitItem['slot'],
  tags: string[],
  order: number,
): StoredOutfitItem {
  return {
    clothing_id: id,
    slot,
    colors: {},
    layer_state: '完整',
    order,
    enabled: true,
    covers: slot === 'full_body' ? ['top', 'bottom'] : [],
    clothing_version: 2,
    snapshot: {
      id,
      label: id,
      translation: '',
      category: '',
      part: '',
      tags,
      draw_prompt: '',
      rating: '普通',
      source: 'builtin',
      schema_version: 2,
      layer_state: '完整',
      materials: [],
      accessories: [],
    },
  };
}

describe('outfit set helpers', () => {
  it('infers primary slots and cross-slot coverage', () => {
    expect(inferOutfitSlot(clothing())).toBe('top');
    expect(inferOutfitSlot(clothing({ part: '鞋', category: '鞋' }))).toBe('footwear');
    expect(inferOutfitSlot(clothing({ part: '配饰', tags: ['wide hat'] }))).toBe('headwear');
    expect(inferOutfitSlot(clothing({ part: '内衣', tags: ['lace bodysuit'] }))).toBe('full_body');
    expect(defaultOutfitCovers('full_body')).toEqual(['top', 'bottom']);
    expect(
      defaultOutfitCovers(
        'full_body',
        clothing({ part: '内衣', tags: ['lace bodysuit'] }),
      ),
    ).toEqual(['top', 'bottom', 'underwear']);
  });

  it('creates an editable draft from an atomic clothing preset', () => {
    expect(
      outfitDraftItem(
        clothing({
          id: 'shoe_mary_janes',
          category: '鞋',
          part: '鞋',
          layer_state: '完整',
        }),
      ),
    ).toEqual({
      clothing_id: 'shoe_mary_janes',
      slot: 'footwear',
      colors: {},
      layer_state: '完整',
      enabled: true,
      covers: [],
    });
  });

  it('replaces only target clothing blocks and keeps item snapshots', () => {
    const base = createEmptyStructuredDocument();
    const withSecond = addCharacter(base, '女');
    const firstId = withSecond.characters[0].id;
    const secondId = withSecond.characters[1].id;
    const prepared = updateGlobalBlock(
      updateCharacterBlock(
        updateCharacterBlock(withSecond, firstId, 'appearance', (block) => ({
          ...block,
          tags: ['silver hair'],
        })),
        firstId,
        'expression',
        (block) => ({ ...block, tags: ['smile'] }),
      ),
      'scene',
      (block) => ({ ...block, tags: ['rooftop'] }),
    );
    const beforeAppearance = prepared.characters[0].appearance;
    const beforeExpression = prepared.characters[0].expression;
    const beforeScene = prepared.global.scene;
    const beforeProps = prepared.props;
    const outfit: OutfitSetDefinition & {
      preset_id: string;
      version: number;
      content_hash: string;
    } = {
      preset_id: 'outfit_test',
      version: 3,
      content_hash: 'abc123',
      name: '测试套装',
      prompt: 'test top, test skirt, black shoes',
      items: [
        item('test_top', 'top', ['test top'], 0),
        item('test_skirt', 'bottom', ['test skirt'], 1),
        item('test_shoes', 'footwear', ['black shoes'], 2),
      ],
    };

    const applied = applyOutfitSetToDocument(
      prepared,
      outfit,
      secondId,
      'all',
    );

    expect(applied.characters[0].appearance).toEqual(beforeAppearance);
    expect(applied.characters[0].expression).toEqual(beforeExpression);
    expect(applied.global.scene).toEqual(beforeScene);
    expect(applied.props).toEqual(beforeProps);
    expect(applied.characters[0].clothing.tags).toEqual([
      'test top',
      'test skirt',
    ]);
    expect(applied.characters[1].clothing.tags).toEqual([
      'test top',
      'test skirt',
    ]);
    expect(applied.characters[0].clothing.footwear?.tags).toEqual([
      'black shoes',
    ]);
    expect(applied.characters[0].clothing.source).toBe('outfit_set');
    expect(applied.characters[0].clothing.preset_refs[0]).toEqual({
      preset_id: 'outfit_set:outfit_test',
      version: 3,
    });
    expect(
      (applied.characters[0].clothing.preset_snapshot as {
        outfit_set: { content_hash: string };
      }).outfit_set.content_hash,
    ).toBe('abc123');
  });

  it('applies only to the active character when requested', () => {
    const base = addCharacter(createEmptyStructuredDocument(), '女');
    const secondId = base.characters[1].id;
    const applied = applyOutfitSetToDocument(
      base,
      {
        name: '单角色套装',
        items: [item('test_top', 'top', ['test top'], 0)],
      },
      secondId,
      'current',
    );
    expect(applied.characters[0].clothing.tags).toEqual([]);
    expect(applied.characters[1].clothing.tags).toEqual(['test top']);
  });

  it('ignores disabled items when applying', () => {
    const base = createEmptyStructuredDocument();
    const applied = applyOutfitSetToDocument(
      base,
      {
        name: '停用项测试',
        items: [
          item('test_top', 'top', ['test top'], 0),
          { ...item('test_skirt', 'bottom', ['test skirt'], 1), enabled: false },
        ],
      },
      base.characters[0].id,
      'current',
    );
    expect(applied.characters[0].clothing.tags).toEqual(['test top']);
  });
});
