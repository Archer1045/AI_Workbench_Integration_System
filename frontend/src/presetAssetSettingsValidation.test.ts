import { describe, expect, it } from 'vitest';

import type {
  PresetAssetSettings,
  PresetAssetSettingsPayload,
  PresetAssetTarget,
} from './api';
import {
  firstPresetAssetSettingsError,
  validatePresetAssetSettings,
} from './presetAssetSettingsValidation';

const limits: PresetAssetSettingsPayload['limits'] = {
  candidate_min: 1,
  candidate_max: 4,
  batch_max_items: 20,
  upload_max_bytes: 20 * 1024 * 1024,
  upload_max_pixels: 40_000_000,
  width_min: 64,
  width_max: 2048,
  height_min: 64,
  height_max: 2048,
  steps_min: 1,
  steps_max: 80,
  cfg_min: 0.5,
  cfg_max: 20,
  cfg_step: 0.5,
  seed_min: 0,
  seed_max: 4_294_967_295,
  focus_min: 0,
  focus_max: 1,
  focus_step: 0.01,
  zoom_min: 0.05,
  zoom_max: 3,
  zoom_step: 0.05,
  lora_strength_min: 0,
  lora_strength_max: 2,
  lora_strength_step: 0.05,
};

const target: PresetAssetTarget = {
  generation_size: [540, 960],
  output_size: [270, 480],
  format: 'PNG',
  quality: 90,
};

function settings(overrides: Partial<PresetAssetSettings> = {}): PresetAssetSettings {
  return {
    version: 1,
    model: 'model.safetensors',
    loras: [],
    lora_strengths: {},
    lora_strength_model: 1,
    lora_strength_clip: 1,
    steps: 28,
    cfg: 7,
    seed_strategy: 'random',
    seed: null,
    crop_mode: 'cover',
    focus_x: 0.5,
    focus_y: 0.5,
    zoom: 1,
    candidate_count: 2,
    style_positive: '',
    style_negative: '',
    user_positive: '',
    user_negative: '',
    ...overrides,
  };
}

describe('preset asset settings validation', () => {
  it('accepts valid values and independent LoRA strengths', () => {
    const errors = validatePresetAssetSettings(
      settings({
        loras: ['style.safetensors'],
        lora_strengths: {
          'style.safetensors': { model: 1.1, clip: 0.8 },
        },
      }),
      limits,
      target,
    );

    expect(firstPresetAssetSettingsError(errors)).toBeNull();
  });

  it('reports field-level range and seed errors', () => {
    const errors = validatePresetAssetSettings(
      settings({
        steps: 0,
        cfg: 21,
        seed_strategy: 'fixed',
        seed: null,
        candidate_count: 5,
        focus_x: -0.1,
        zoom: 4,
        lora_strength_model: -0.1,
        lora_strength_clip: 2.5,
      }),
      limits,
      target,
    );

    expect(errors.steps).toContain('步数');
    expect(errors.cfg).toContain('CFG');
    expect(errors.seed).toContain('Seed');
    expect(errors.candidate_count).toContain('候选数量');
    expect(errors.focus_x).toContain('横向焦点');
    expect(errors.zoom).toContain('缩放');
    expect(errors.lora_strength_model).toContain('默认模型强度');
    expect(errors.lora_strength_clip).toContain('默认 CLIP 强度');
  });

  it('rejects LoRA strength outside the configured range', () => {
    const errors = validatePresetAssetSettings(
      settings({
        loras: ['style.safetensors'],
        lora_strengths: {
          'style.safetensors': { model: 2.5 },
        },
      }),
      limits,
      target,
    );

    expect(errors.lora_strengths).toContain('模型强度');
  });
});
