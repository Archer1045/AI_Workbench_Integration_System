import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CharacterAppearanceModal from './CharacterAppearanceModal';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock('../api', () => ({
  api: apiMocks,
}));

vi.mock('../stores/presetAssetStore', () => ({}));

describe('CharacterAppearanceModal default outfit set binding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.get.mockImplementation((url: string) => {
      if (url === '/prompt-agent/appearance-presets') {
        return Promise.resolve({
          data: {
            items: [],
            total: 0,
            categories: ['角色'],
            sources: ['builtin', 'user'],
            works: [],
          },
        });
      }
      if (url === '/prompt-agent/outfit-presets') {
        return Promise.resolve({
          data: {
            items: [
              {
                preset_id: 'outfit_campus_cream',
                name: '奶油校园',
                category: '校园',
                version: 2,
                items: [],
              },
            ],
          },
        });
      }
      if (url.includes('/versions')) {
        return Promise.resolve({
          data: {
            items: [
              { preset_id: 'outfit_campus_cream', name: '奶油校园 v2', version: 2 },
              { preset_id: 'outfit_campus_cream', name: '奶油校园 v1', version: 1 },
            ],
          },
        });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    apiMocks.post.mockResolvedValue({
      data: {
        item: {
          preset_id: 'appearance_test',
          version: 1,
        },
      },
    });
  });

  it('saves the atomic outfit and pinned set version separately', async () => {
    render(
      <CharacterAppearanceModal
        open
        onClose={() => undefined}
        onApply={() => undefined}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /新建/ }));
    fireEvent.change(screen.getByPlaceholderText('预设名称'), {
      target: { value: '测试角色' },
    });
    fireEvent.change(
      screen.getByPlaceholderText('例如 outfit_genshin_columbina_default'),
      { target: { value: 'outfit_atomic_default' } },
    );

    const setField = screen
      .getByText('默认服装套装（可选）')
      .closest('.setting-field');
    expect(setField).not.toBeNull();
    fireEvent.mouseDown(
      within(setField as HTMLElement).getAllByRole('combobox')[0],
    );
    fireEvent.click(await screen.findByText('奶油校园 · 校园 · v2'));

    await waitFor(() =>
      expect(apiMocks.get).toHaveBeenCalledWith(
        '/prompt-agent/outfit-presets/outfit_campus_cream/versions',
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => expect(apiMocks.post).toHaveBeenCalled());
    expect(apiMocks.post.mock.calls[0][1]).toMatchObject({
      outfit_id: 'outfit_atomic_default',
      outfit_set_id: 'outfit_campus_cream',
      outfit_set_version: 2,
    });
  });
});
