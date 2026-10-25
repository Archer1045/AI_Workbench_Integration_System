import { describe, expect, it } from 'vitest';
import {
  DRAW_PROMPT_FRAGMENTS,
  applyDrawPromptFragment,
} from './drawPromptFragments';
import { createEmptyStructuredDocument } from './promptDocument';

describe('draw prompt fragments', () => {
  it('has unique fragments across positive and negative categories', () => {
    const ids = DRAW_PROMPT_FRAGMENTS.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(
      DRAW_PROMPT_FRAGMENTS.some((item) => item.target.startsWith('negative_')),
    ).toBe(true);
    expect(
      DRAW_PROMPT_FRAGMENTS.some((item) => !item.target.startsWith('negative_')),
    ).toBe(true);
  });

  it('applies positive and negative fragments to their independent blocks', () => {
    const lighting = DRAW_PROMPT_FRAGMENTS.find(
      (item) => item.id === 'fragment_light_soft',
    )!;
    const hands = DRAW_PROMPT_FRAGMENTS.find(
      (item) => item.id === 'fragment_negative_hands',
    )!;
    let document = createEmptyStructuredDocument();
    document = applyDrawPromptFragment(document, lighting);
    document = applyDrawPromptFragment(document, hands);

    expect(document.global.lighting.tags).toEqual(lighting.tags);
    expect(document.negative.anatomy.tags).toEqual(hands.tags);
    expect(document.global.lighting.source).toBe('prompt_fragment');
    expect(document.negative.anatomy.source).toBe('prompt_fragment');
  });
});
