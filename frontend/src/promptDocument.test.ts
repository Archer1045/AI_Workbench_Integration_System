import { describe, expect, it } from 'vitest';
import {
  addCharacter,
  applyAppearancePresetToCharacter,
  applyExpressionPresetToCharacter,
  createBodyProfile,
  createEmptyStructuredDocument,
  createLegacyDocument,
  createStructuredDocumentFromLegacy,
  isBodyProfileEmpty,
  isPromptDocumentEmpty,
  moveCharacter,
  normalizePromptDocument,
  removeCharacter,
  resolveCharacterTargets,
  updateCharacter,
  updateCharacterBlock,
} from './promptDocument';

describe('prompt document model', () => {
  it('normalizes a partial document into a complete editable shape', () => {
    const document = normalizePromptDocument({
      mode: 'structured',
      characters: [
        {
          id: 'hero',
          role_id: 'girlA',
          display_name: 'Hero',
          gender: '女',
          appearance: { tags: ['long hair'] },
        },
      ],
    });

    expect(document.version).toBe(1);
    expect(document.characters).toHaveLength(1);
    expect(document.characters[0].appearance.tags).toEqual(['long hair']);
    expect(document.characters[0].clothing.preset_refs).toEqual([]);
    expect(document.global.quality.enabled).toBe(true);
    expect(document.negative.quality.tags).toEqual([]);
  });

  it('adds, moves, and removes characters without losing the minimum role', () => {
    const first = createEmptyStructuredDocument();
    const withGirl = addCharacter(first, '女');
    const withBoy = addCharacter(withGirl, '男');

    expect(withBoy.characters.map((character) => character.role_id)).toEqual([
      'girlA',
      'girlB',
      'boy1',
    ]);

    const moved = moveCharacter(withBoy, withBoy.characters[2].id, -1);
    expect(moved.characters.map((character) => character.role_id)).toEqual([
      'girlA',
      'boy1',
      'girlB',
    ]);

    const removed = removeCharacter(moved, moved.characters[1].id);
    expect(removed.characters.map((character) => character.role_id)).toEqual(['girlA', 'girlB']);
    expect(removed.characters.map((character) => character.order)).toEqual([0, 1]);

    const minimum = removeCharacter(removeCharacter(removed, removed.characters[0].id), removed.characters[1].id);
    expect(minimum.characters).toHaveLength(1);
  });

  it('updates one character block without mutating the original document', () => {
    const original = createEmptyStructuredDocument();
    const updated = updateCharacterBlock(original, original.characters[0].id, 'appearance', (block) => ({
      ...block,
      tags: ['green eyes'],
    }));

    expect(updated.characters[0].appearance.tags).toEqual(['green eyes']);
    expect(original.characters[0].appearance.tags).toEqual([]);
  });

  it('normalizes and stores independent body profile selections per character', () => {
    const document = createEmptyStructuredDocument();
    const withFirst = updateCharacter(document, document.characters[0].id, (character) => ({
      ...character,
      height_frame: 'tall',
      body_build: 'slim',
    }));
    const withSecond = addCharacter(withFirst, '女');
    const updated = updateCharacter(withSecond, withSecond.characters[1].id, (character) => ({
      ...character,
      height_frame: 'petite_adult',
      body_build: 'curvy',
    }));

    expect(updated.characters[0].height_frame).toBe('tall');
    expect(updated.characters[0].body_build).toBe('slim');
    expect(updated.characters[1].height_frame).toBe('petite_adult');
    expect(updated.characters[1].body_build).toBe('curvy');
    expect(isPromptDocumentEmpty(updated)).toBe(false);
  });

  it('falls back to no body profile for missing or unknown values', () => {
    const document = normalizePromptDocument({
      mode: 'structured',
      characters: [
        {
          id: 'hero',
          role_id: 'girlA',
          display_name: 'Hero',
          gender: '女',
          height_frame: 'unknown',
        },
      ],
    });

    expect(document.characters[0].height_frame).toBe('none');
    expect(document.characters[0].body_build).toBe('none');
  });

  it('keeps legacy text mode while applying an independent body profile', () => {
    const profile = createBodyProfile({
      height_frame: 'tall',
      body_build: 'curvy',
    });
    const document = createStructuredDocumentFromLegacy(
      '1girl, city',
      'low quality',
      profile,
    );

    expect(isBodyProfileEmpty(profile)).toBe(false);
    expect(document.custom.global_tags).toEqual(['1girl', 'city']);
    expect(document.raw_override).toEqual({
      prompt: '1girl, city',
      negative_prompt: 'low quality',
    });
    expect(document.characters[0].height_frame).toBe('tall');
    expect(document.characters[0].body_build).toBe('curvy');
  });

  it('resolves current, all, and role scoped character targets', () => {
    const document = addCharacter(addCharacter(createEmptyStructuredDocument(), '男'), '男');

    expect(resolveCharacterTargets(document, document.characters[1].id, 'current')).toEqual([
      document.characters[1].id,
    ]);
    expect(resolveCharacterTargets(document, document.characters[0].id, 'all')).toEqual(
      document.characters.map((character) => character.id),
    );
    expect(resolveCharacterTargets(document, document.characters[0].id, 'boyB')).toEqual([
      document.characters[1].id,
    ]);
  });

  it('applies appearance tags and a stable preset reference to one character', () => {
    const document = createEmptyStructuredDocument();
    const updated = applyAppearancePresetToCharacter(document, document.characters[0].id, {
      preset_ref: { preset_id: 'look-1', version: 3 },
      snapshot: { name: 'Look' },
      appearance: ['silver hair'],
      clothing: ['black coat'],
      expression: ['calm gaze'],
    });

    expect(updated.characters[0].appearance.tags).toEqual(['silver hair']);
    expect(updated.characters[0].clothing.tags).toEqual(['black coat']);
    expect(updated.characters[0].expression.tags).toEqual(['calm gaze']);
    expect(updated.characters[0].appearance.preset_refs).toEqual([{ preset_id: 'look-1', version: 3 }]);
    expect(updated.characters[0].appearance.source).toBe('appearance_preset');
  });

  it('writes an expression preset into the target expression block without touching other blocks', () => {
    const document = createEmptyStructuredDocument();
    const preset = {
      id: 'expression_soft_smile',
      label: '柔和微笑',
      category: '基础情绪',
      tags: ['soft smile', 'gentle smile', 'closed mouth'],
    };
    const updated = applyExpressionPresetToCharacter(
      document,
      document.characters[0].id,
      preset,
      'girlA',
    );

    expect(updated.characters[0].expression.tags).toEqual(preset.tags);
    expect(updated.characters[0].expression.preset_refs).toEqual([
      { preset_id: preset.id, version: 1, scope: 'girlA' },
    ]);
    expect(updated.characters[0].expression.preset_snapshot).toEqual({
      name: '柔和微笑',
      category: '基础情绪',
      expression_tags: preset.tags,
    });
    expect(updated.characters[0].expression.source).toBe('expression_preset');
    expect(updated.characters[0].appearance.tags).toEqual([]);
  });

  it('distinguishes empty documents from legacy and structured content', () => {
    const empty = createEmptyStructuredDocument();
    const structured = normalizePromptDocument({
      ...empty,
      custom: { global_tags: ['city'], user_notes: '' },
    });
    const legacy = createLegacyDocument('1girl, city', 'low quality');

    expect(isPromptDocumentEmpty(empty)).toBe(true);
    expect(isPromptDocumentEmpty(structured)).toBe(false);
    expect(isPromptDocumentEmpty(legacy)).toBe(false);
  });
});
