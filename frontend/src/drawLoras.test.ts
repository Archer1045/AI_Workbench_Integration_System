import { describe, expect, it } from 'vitest';

import { parseDrawLoras, visibleDrawLoras } from './drawLoras';

describe('draw loras', () => {
  it('parses and deduplicates structured LoRA names', () => {
    expect(
      parseDrawLoras({
        loras_json: JSON.stringify([
          'style-a.safetensors',
          'style-a.safetensors',
          'character-b.safetensors',
        ]),
      }),
    ).toEqual(['style-a', 'character-b']);
  });

  it('falls back to legacy flags when structured JSON is missing or malformed', () => {
    expect(
      parseDrawLoras({
        loras_json: '{broken',
        lora_anima_turbo: 1,
        lora_high_contrast: '1',
      }),
    ).toEqual(['anima-turbo-lora-v0.2', 'high-contrast aesthetic']);
  });

  it('limits visible entries while preserving the complete tooltip', () => {
    const result = visibleDrawLoras({
      loras_json: JSON.stringify(['a', 'b', 'c', 'd.safetensors']),
    });
    expect(result.visible).toEqual(['a', 'b', 'c']);
    expect(result.hiddenCount).toBe(1);
    expect(result.tooltip).toBe('a + b + c + d');
  });
});
