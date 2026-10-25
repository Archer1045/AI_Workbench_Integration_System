import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  fetchPresetTypes: vi.fn(),
}));

vi.mock('../api', () => ({
  api: { get: apiMocks.get },
  fetchPresetTypes: apiMocks.fetchPresetTypes,
}));

vi.mock('../stores/settings', () => ({
  settingsStore: { restrictionEnabled: false },
}));

import PresetLibraryPanel from './PresetLibraryPanel';

const expression = {
  id: 'expression_soft_smile',
  category: '基础情绪',
  label: '柔和微笑',
  translation: '闭口、温和且自然的微笑',
  tags: ['soft smile', 'gentle smile', 'closed mouth'],
  intensity: '轻',
  character_scope: ['通用'],
  rating: '普通',
  nsfw: false,
  source: 'builtin',
  aliases: [],
};

beforeEach(() => {
  localStorage.clear();
  apiMocks.get.mockImplementation((url: string) => {
    if (url === '/prompt-agent/preset-catalog') {
      return Promise.resolve({
        data: {
          poses: [],
          clothing: [],
          scenes: [],
          body_modifications: [],
          expansions: [],
          toys: [],
          characters: [],
        },
      });
    }
    if (url === '/prompt-agent/expression-presets') {
      return Promise.resolve({ data: { items: [expression] } });
    }
    if (url === '/prompt-agent/water-presets') {
      return Promise.resolve({ data: { items: [] } });
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
  apiMocks.fetchPresetTypes.mockResolvedValue({
    items: [
      {
        kind: 'pose',
        label: '体位',
        order: 0,
        catalog_key: 'poses',
        api_path: '/prompt-agent/pose-presets',
        image_directory: 'pose-presets',
        image_extension: 'png',
        taxonomy_key: 'pose',
        composition_field: 'pose_id',
        scope_capable: false,
        max_per_scope: null,
        selection_type: 'single',
        supports_colors: false,
        supports_thumbnail: true,
        composition_enabled: true,
      },
    ],
    composition: { max_items: 12 },
  });
});

describe('PresetLibraryPanel', () => {
  it('loads expression presets into the unified selector and applies with options', async () => {
    const onApply = vi.fn();
    render(<PresetLibraryPanel variant="drawer" onApply={onApply} />);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^体位/ })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: /^表情/ }));
    await waitFor(() =>
      expect(screen.getAllByText('柔和微笑').length).toBeGreaterThan(0),
    );

    fireEvent.click(
      screen.getByRole('button', { name: '应用到当前提示词' }),
    );

    expect(onApply).toHaveBeenCalledWith(
      'expression',
      expect.objectContaining({ id: expression.id }),
      {
        scope: 'all',
        poseDetail: 'core',
        scenePeoplePolicy: 'occupied',
      },
    );
  }, 15000);

  it('supports favorites and recent-use filtering within the active type', async () => {
    render(<PresetLibraryPanel variant="drawer" onApply={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^体位/ })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: /^表情/ }));
    await waitFor(() =>
      expect(screen.getAllByText('柔和微笑').length).toBeGreaterThan(0),
    );

    fireEvent.click(
      screen.getByRole('button', { name: '应用到当前提示词' }),
    );
    fireEvent.click(
      screen.getByRole('button', { name: '收藏预设' }),
    );

    expect(
      screen.getByRole('button', { name: '取消收藏预设' }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '只看最近使用' }));
    expect(screen.getAllByText('柔和微笑').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: '只看收藏' }));
    expect(screen.getAllByText('柔和微笑').length).toBeGreaterThan(0);
  }, 15000);
});
