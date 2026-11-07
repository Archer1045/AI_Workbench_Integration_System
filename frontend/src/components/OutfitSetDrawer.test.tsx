import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OutfitSetCatalog } from '../api';
import OutfitSetDrawer from './OutfitSetDrawer';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock('../api', () => ({
  api: apiMocks,
}));

vi.mock('../stores/settings', () => ({
  settingsStore: { restrictionEnabled: false },
}));

const catalog: OutfitSetCatalog = {
  total: 1,
  categories: ['校园'],
  slots: [
    { value: 'top', label: '上装' },
    { value: 'bottom', label: '下装' },
    { value: 'footwear', label: '鞋' },
  ],
  max_items: 12,
  restricted: false,
  schema_version: 1,
  items: [
    {
      id: 'outfit_campus_cream',
      row_id: 1,
      preset_id: 'outfit_campus_cream',
      name: '奶油校园',
      description: '测试套装',
      category: '校园',
      gender_scope: '女',
      character_scope: [],
      source: 'builtin',
      version: 1,
      enabled: true,
      rating: '普通',
      content_hash: 'abc123',
      prompt: 'school uniform, loafers',
      created_at: '2026-10-26T00:00:00+08:00',
      updated_at: '2026-10-26T00:00:00+08:00',
      items: [
        {
          clothing_id: 'school_uniform_jk',
          slot: 'full_body',
          colors: {},
          layer_state: '完整',
          order: 0,
          enabled: true,
          covers: ['top', 'bottom'],
          clothing_version: 2,
          snapshot: {
            id: 'school_uniform_jk',
            label: 'JK 校服',
            translation: '白色衬衫与百褶裙',
            category: '校服/制服',
            part: '全身',
            tags: ['school uniform', 'pleated skirt'],
            draw_prompt: 'wearing a JK school uniform',
            rating: '普通',
            source: 'builtin',
            schema_version: 2,
            layer_state: '完整',
            materials: [],
            accessories: [],
          },
        },
      ],
    },
  ],
};

describe('OutfitSetDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.get.mockImplementation((url: string) => {
      if (url === '/prompt-agent/outfit-presets') {
        return Promise.resolve({ data: catalog });
      }
      return Promise.resolve({
        data: {
          items: [
            {
              id: 'school_uniform_jk',
              category: '校服/制服',
              label: 'JK 校服',
              translation: '白色衬衫与百褶裙',
              tags: ['school uniform', 'pleated skirt'],
              gender: '女',
              part: '全身',
              nsfw: false,
              rating: '普通',
            },
          ],
        },
      });
    });
  });

  it('loads saved outfits and exposes final-combination preview', async () => {
    render(<OutfitSetDrawer open onClose={() => undefined} onApply={() => true} />);

    expect((await screen.findAllByText('奶油校园')).length).toBeGreaterThan(0);
    expect(screen.getByText('套装库')).toBeInTheDocument();
    expect(screen.getByText('JK 校服')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '生成 4 张预览' }),
    ).toBeEnabled();
  });

  it('lists saved versions before an append-only rollback', async () => {
    const current = {
      ...catalog.items[0],
      source: 'user',
      version: 2,
      name: '奶油校园 v2',
    };
    const previous = {
      ...catalog.items[0],
      source: 'user',
      version: 1,
      name: '奶油校园 v1',
    };
    apiMocks.get.mockImplementation((url: string) => {
      if (url === '/prompt-agent/outfit-presets') {
        return Promise.resolve({
          data: { ...catalog, items: [current] },
        });
      }
      if (url.includes('/versions')) {
        return Promise.resolve({
          data: { items: [current, previous], total: 2 },
        });
      }
      return Promise.resolve({
        data: {
          items: [
            {
              id: 'school_uniform_jk',
              category: '校服/制服',
              label: 'JK 校服',
              translation: '白色衬衫与百褶裙',
              tags: ['school uniform', 'pleated skirt'],
              gender: '女',
              part: '全身',
              nsfw: false,
              rating: '普通',
            },
          ],
        },
      });
    });

    render(<OutfitSetDrawer open onClose={() => undefined} onApply={() => true} />);
    await screen.findAllByText('奶油校园 v2');
    fireEvent.click(screen.getByRole('button', { name: /历史版本/ }));

    await waitFor(() =>
      expect(apiMocks.get).toHaveBeenCalledWith(
        `/prompt-agent/outfit-presets/${current.preset_id}/versions`,
      ),
    );
    expect(await screen.findByText('回滚不会删除历史版本')).toBeInTheDocument();
    expect(screen.getByText('奶油校园 v1')).toBeInTheDocument();
    expect(screen.getByText('当前版本')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '恢复此版本' })).toBeInTheDocument();
  });
});
