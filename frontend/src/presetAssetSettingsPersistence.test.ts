import { describe, expect, it } from 'vitest';

import type { PresetAssetSettings } from './api';
import {
  clearPresetAssetSettingsDraft,
  deletePresetAssetSettingsScheme,
  loadPresetAssetSettingsDraft,
  loadPresetAssetSettingsSchemes,
  loadPresetAssetSettingsWithDefaults,
  PRESET_ASSET_SETTINGS_STORAGE_KEY,
  savePresetAssetSettingsDraft,
  savePresetAssetSettingsScheme,
} from './presetAssetSettingsPersistence';

class MemoryStorage {
  private data = new Map<string, string>();

  getItem(key: string): string | null {
    return this.data.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.data.set(key, value);
  }
}

function settings(steps: number): PresetAssetSettings {
  return {
    version: 1,
    model: 'model.safetensors',
    loras: [],
    lora_strengths: {},
    lora_strength_model: 1,
    lora_strength_clip: 1,
    steps,
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
  };
}

describe('preset asset settings persistence', () => {
  it('migrates a v1 draft into all material types', () => {
    const storage = new MemoryStorage();
    storage.setItem(
      PRESET_ASSET_SETTINGS_STORAGE_KEY,
      JSON.stringify({ v: 1, settings: settings(32) }),
    );

    expect(loadPresetAssetSettingsDraft('pose', storage)?.steps).toBe(32);
    expect(loadPresetAssetSettingsDraft('clothing', storage)?.steps).toBe(32);
    expect(loadPresetAssetSettingsDraft('scene', storage)?.steps).toBe(32);
    expect(loadPresetAssetSettingsDraft('body', storage)?.steps).toBe(32);
    expect(
      JSON.parse(storage.getItem(PRESET_ASSET_SETTINGS_STORAGE_KEY) || '{}').v,
    ).toBe(2);
  });

  it('keeps drafts and named schemes isolated by material type', () => {
    const storage = new MemoryStorage();
    savePresetAssetSettingsDraft(settings(31), 'pose', storage);
    savePresetAssetSettingsDraft(settings(36), 'clothing', storage);
    const poseScheme = savePresetAssetSettingsScheme(
      'pose',
      '姿态常用',
      settings(34),
      storage,
    );
    savePresetAssetSettingsScheme(
      'clothing',
      '服装常用',
      settings(38),
      storage,
    );

    expect(loadPresetAssetSettingsDraft('pose', storage)?.steps).toBe(31);
    expect(loadPresetAssetSettingsDraft('clothing', storage)?.steps).toBe(36);
    expect(loadPresetAssetSettingsSchemes('pose', storage).map((item) => item.name))
      .toEqual(['姿态常用']);
    expect(
      loadPresetAssetSettingsSchemes('clothing', storage).map((item) => item.name),
    ).toEqual(['服装常用']);

    deletePresetAssetSettingsScheme(poseScheme?.id || '', storage);
    expect(loadPresetAssetSettingsSchemes('pose', storage)).toEqual([]);

    clearPresetAssetSettingsDraft('pose', storage);
    expect(loadPresetAssetSettingsDraft('pose', storage)).toBeNull();
    expect(loadPresetAssetSettingsDraft('clothing', storage)?.steps).toBe(36);
  });

  it('merges the selected material draft with backend defaults', () => {
    const storage = new MemoryStorage();
    savePresetAssetSettingsDraft(settings(31), 'pose', storage);

    expect(
      loadPresetAssetSettingsWithDefaults('pose', settings(28), storage).steps,
    ).toBe(31);
    expect(
      loadPresetAssetSettingsWithDefaults('clothing', settings(28), storage).steps,
    ).toBe(28);
  });
});
