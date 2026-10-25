import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PresetAssetDetail,
  PresetAssetKind,
  PresetAssetSettingsPayload,
} from '../api';
import {
  loadPresetAssetSettingsDraft,
  PRESET_ASSET_SETTINGS_STORAGE_KEY,
} from '../presetAssetSettingsPersistence';
import { presetAssetStore } from '../stores/presetAssetStore';
import PresetAssetParamsPanel from './PresetAssetParamsPanel';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('../api', () => ({
  api: { get: apiMocks.get },
}));

vi.mock('../stores/presetAssetStore', () => ({
  apiErrorMessage: vi.fn(),
  createPresetAssetAi: vi.fn(),
  createPresetAssetCrop: vi.fn(),
  importPresetAsset: vi.fn(),
  presetAssetStore: {
    detail: null,
    settings: null,
    submitting: false,
  },
  savePresetAssetDefaults: vi.fn(),
}));

const settingsPayload: PresetAssetSettingsPayload = {
  defaults: {
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
  },
  targets: {
    pose: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'PNG',
      quality: 90,
    },
    clothing: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'WEBP',
      quality: 90,
    },
    scene: {
      generation_size: [960, 540],
      output_size: [480, 270],
      format: 'WEBP',
      quality: 90,
    },
    body: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'WEBP',
      quality: 90,
    },
    expansion: {
      generation_size: [768, 768],
      output_size: [384, 384],
      format: 'WEBP',
      quality: 90,
    },
    toy: {
      generation_size: [768, 768],
      output_size: [384, 384],
      format: 'WEBP',
      quality: 90,
    },
    character: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'WEBP',
      quality: 90,
    },
  },
  limits: {
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
  },
  template_version: '1',
};

function detailFor(
  presetId: string,
  presetType: PresetAssetKind = 'pose',
): PresetAssetDetail {
  return {
    summary: {
      preset_id: presetId,
      preset_type: presetType,
      label: presetId,
      rating: 'R18',
      image: null,
      source: null,
    },
    candidates: [],
    versions: [],
  } as unknown as PresetAssetDetail;
}

describe('PresetAssetParamsPanel', () => {
  beforeEach(() => {
    localStorage.clear();
    apiMocks.get.mockResolvedValue({ data: { loras: [] } });
    presetAssetStore.detail = detailFor('pose-a');
    presetAssetStore.settings = settingsPayload;
    presetAssetStore.submitting = false;
  });

  it('keeps edited parameters when switching to another preset', async () => {
    const user = userEvent.setup();
    const first = render(<PresetAssetParamsPanel />);
    await user.click(screen.getByText('模型与采样'));
    const steps = await screen.findByLabelText('步数');

    await user.click(steps);
    await user.keyboard('{ArrowUp}');
    expect(steps).toHaveValue('29');

    first.unmount();
    presetAssetStore.detail = detailFor('pose-b');
    render(<PresetAssetParamsPanel />);

    await user.click(screen.getByText('模型与采样'));
    expect(await screen.findByLabelText('步数')).toHaveValue('29');
  });

  it('restores persisted parameters after a fresh mount', async () => {
    localStorage.setItem(
      PRESET_ASSET_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        v: 1,
        settings: {
          ...settingsPayload.defaults,
          steps: 31,
          cfg: 8.5,
          loras: ['style.safetensors'],
        },
      }),
    );

    render(<PresetAssetParamsPanel />);
    await userEvent.click(screen.getByText('模型与采样'));

    expect(await screen.findByLabelText('步数')).toHaveValue('31');
    expect(screen.getByLabelText('CFG')).toHaveValue('8.5');
  });

  it('isolates drafts by preset material type', async () => {
    localStorage.setItem(
      PRESET_ASSET_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        v: 2,
        drafts: {
          pose: { ...settingsPayload.defaults, steps: 31 },
          clothing: { ...settingsPayload.defaults, steps: 36 },
        },
      }),
    );

    const first = render(<PresetAssetParamsPanel />);
    await userEvent.click(screen.getByText('模型与采样'));
    expect(await screen.findByLabelText('步数')).toHaveValue('31');

    first.unmount();
    presetAssetStore.detail = detailFor('clothing-a', 'clothing');
    render(<PresetAssetParamsPanel />);
    await userEvent.click(screen.getByText('模型与采样'));
    expect(await screen.findByLabelText('步数')).toHaveValue('36');
  });

  it('restores backend defaults and clears the current type draft', async () => {
    const user = userEvent.setup();
    render(<PresetAssetParamsPanel />);
    await user.click(screen.getByText('模型与采样'));
    const steps = await screen.findByLabelText('步数');
    fireEvent.change(steps, { target: { value: '31' } });
    expect(loadPresetAssetSettingsDraft('pose')?.steps).toBe(31);

    await user.click(screen.getByRole('button', { name: '清除本地草稿' }));
    expect(steps).toHaveValue('28');
    expect(loadPresetAssetSettingsDraft('pose')).toBeNull();

    fireEvent.change(steps, { target: { value: '33' } });
    await user.click(
      screen.getByRole('button', { name: /恢复后端默认值/ }),
    );
    expect(steps).toHaveValue('28');
    expect(loadPresetAssetSettingsDraft('pose')?.steps).toBe(28);
  }, 10_000);

  it('shows per-LoRA strength overrides', async () => {
    localStorage.setItem(
      PRESET_ASSET_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        v: 2,
        drafts: {
          pose: {
            ...settingsPayload.defaults,
            loras: ['style.safetensors'],
            lora_strengths: {
              'style.safetensors': { model: 1.15, clip: 0.75 },
            },
          },
        },
      }),
    );

    render(<PresetAssetParamsPanel />);
    await userEvent.click(screen.getByText('模型与采样'));

    expect(
      await screen.findByLabelText('style.safetensors 模型强度'),
    ).toHaveValue('1.15');
    expect(screen.getByLabelText('style.safetensors CLIP 强度')).toHaveValue('0.75');
  });

  it('falls back to backend defaults when persisted data is invalid', async () => {
    localStorage.setItem(PRESET_ASSET_SETTINGS_STORAGE_KEY, '{bad json');

    render(<PresetAssetParamsPanel />);
    await userEvent.click(screen.getByText('模型与采样'));

    expect(await screen.findByLabelText('步数')).toHaveValue('28');
  });

  it('edits the material draft in batch mode without a preset detail', async () => {
    const user = userEvent.setup();
    presetAssetStore.detail = null;

    render(<PresetAssetParamsPanel presetType="clothing" batchMode />);
    expect(screen.getByText('批量生成参数')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'AI 生成候选' }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByText('模型与采样'));
    const steps = await screen.findByLabelText('步数');
    fireEvent.change(steps, { target: { value: '31' } });

    expect(loadPresetAssetSettingsDraft('clothing')?.steps).toBe(31);
  });
});
