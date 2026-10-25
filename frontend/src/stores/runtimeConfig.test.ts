import { describe, expect, it, vi } from 'vitest';

import type { RuntimeConfig } from '../api';

const apiMocks = vi.hoisted(() => ({
  fetchRuntimeConfig: vi.fn(),
}));

vi.mock('../api', () => apiMocks);

import { FALLBACK_RUNTIME_CONFIG, loadRuntimeConfig } from './runtimeConfig';

const expectedTargets = {
  pose: {
    generation_size: [832, 1216],
    output_size: [512, 768],
    format: 'PNG',
    quality: 95,
  },
  clothing: {
    generation_size: [540, 960],
    output_size: [270, 480],
    format: 'WEBP',
    quality: 90,
  },
  scene: {
    generation_size: [1024, 576],
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
};

describe('runtimeConfig', () => {
  it('keeps the full preset asset target fallback contract', () => {
    expect(FALLBACK_RUNTIME_CONFIG.preset_assets.targets).toEqual(expectedTargets);
  });

  it('preserves target entries when merging a partial runtime response', async () => {
    const partial = {
      preset_assets: {
        targets: {
          pose: {
            generation_size: [768, 1152],
            output_size: [512, 768],
            format: 'PNG',
            quality: 100,
          },
        },
      },
    } as RuntimeConfig;
    apiMocks.fetchRuntimeConfig.mockResolvedValueOnce(partial);

    const loaded = await loadRuntimeConfig();

    expect(loaded.preset_assets.targets.pose).toEqual(partial.preset_assets.targets.pose);
    expect(loaded.preset_assets.targets.character).toEqual(
      FALLBACK_RUNTIME_CONFIG.preset_assets.targets.character,
    );
    expect(Object.keys(loaded.preset_assets.targets)).toEqual(Object.keys(expectedTargets));
  });
});
