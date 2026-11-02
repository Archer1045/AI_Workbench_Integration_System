import { describe, expect, it } from 'vitest';
import type { GenerationProfile } from './api';
import {
  canvasPresetOptions,
  normalizeGenerationDimension,
  normalizeGenerationSize,
  selectedCanvasPreset,
} from './generationSpecs';

const profile: GenerationProfile = {
  id: 'anima',
  label: 'Anima',
  latent_node: 'EmptyLatentImage',
  channels: 16,
  height_divisor: 8,
  width_divisor: 8,
  resolution_step: 8,
  min_size: 256,
  max_size: 4096,
  batch_max: 4096,
  downscale_ratio: 8,
  workflow_supported: true,
  workflow_support_reason: '',
  canvas_presets: [
    { id: '1:1', label: '1:1 方形', width: 1024, height: 1024 },
    { id: '9:16', label: '9:16 竖屏', width: 1080, height: 1920 },
  ],
};

describe('generation specs', () => {
  it('rounds dimensions to the model step and clamps them', () => {
    expect(normalizeGenerationDimension(1021, profile)).toBe(1024);
    expect(normalizeGenerationDimension(250, profile)).toBe(256);
    expect(normalizeGenerationDimension(9999, profile)).toBe(4096);
  });

  it('normalizes width and height together', () => {
    expect(normalizeGenerationSize(1083, 1917, profile)).toEqual([1080, 1920]);
  });

  it('finds the matching canvas preset and preserves fallback presets', () => {
    expect(selectedCanvasPreset(1080, 1920, profile)?.id).toBe('9:16');
    expect(selectedCanvasPreset(1088, 1920, profile)).toBeNull();
    expect(canvasPresetOptions(profile)).toHaveLength(2);
  });
});
