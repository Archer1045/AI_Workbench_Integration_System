import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CharacterAppearanceModal, {
  characterPresetPromptForCopy,
} from './CharacterAppearanceModal';

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

const characterPreset = {
  id: 1,
  preset_id: 'appearance_kiyohime',
  name: '清姬 Lancer',
  work: 'Fate/Grand Order',
  category: '角色',
  identity_tags: ['kiyohime_(lancer)_(fate)'],
  appearance_tags: ['long purple hair'],
  clothing_tags: ['ignored flat clothing tag'],
  expression_tags: ['soft smile'],
  outfit_id: 'outfit_kiyohime_default',
  outfit_set_id: 'outfit_set_kiyohime',
  outfit_set_version: 2,
  note: '',
  source: 'user',
  version: 1,
  enabled: true,
  created_at: '2026-11-03T00:00:00+08:00',
  updated_at: '2026-11-03T00:00:00+08:00',
};

const applyResult = {
  preset_ref: { preset_id: characterPreset.preset_id, version: 1 },
  snapshot: {
    name: characterPreset.name,
    category: characterPreset.category,
    identity_tags: characterPreset.identity_tags,
    appearance_tags: characterPreset.appearance_tags,
    clothing_tags: characterPreset.clothing_tags,
    expression_tags: characterPreset.expression_tags,
    outfit_id: characterPreset.outfit_id,
    outfit_set_id: characterPreset.outfit_set_id,
    outfit_set_version: characterPreset.outfit_set_version,
    note: '',
  },
  identity: characterPreset.identity_tags,
  visual_appearance: characterPreset.appearance_tags,
  appearance: [
    ...characterPreset.identity_tags,
    ...characterPreset.appearance_tags,
  ],
  clothing: characterPreset.clothing_tags,
  expression: characterPreset.expression_tags,
  default_outfit_id: characterPreset.outfit_id,
  default_outfit_set: {
    preset_id: characterPreset.outfit_set_id,
    version: characterPreset.outfit_set_version,
    content_hash: 'test-content-hash',
    name: '清姬默认套装 v2',
    prompt: 'wearing a white kimono',
    rating: '普通',
    items: [],
  },
};

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
      screen.getByPlaceholderText('例如 kiyohime_(lancer)_(fate)'),
      { target: { value: 'kiyohime_(lancer)_(fate)' } },
    );
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
      identity_tags: ['kiyohime_(lancer)_(fate)'],
      outfit_id: 'outfit_atomic_default',
      outfit_set_id: 'outfit_campus_cream',
      outfit_set_version: 2,
    });
  });

  it('builds the same prompt combination used when applying the preset', () => {
    expect(
      characterPresetPromptForCopy(
        applyResult as Parameters<typeof characterPresetPromptForCopy>[0],
      ),
    ).toBe(
      'kiyohime_(lancer)_(fate), long purple hair, wearing a white kimono, soft smile',
    );
  });

  it('copies character prompt text without applying the preset', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    apiMocks.get.mockImplementation((url: string) => {
      if (url === '/prompt-agent/appearance-presets') {
        return Promise.resolve({
          data: {
            items: [characterPreset],
            total: 1,
            categories: ['角色'],
            sources: ['user'],
            works: ['Fate/Grand Order'],
          },
        });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    apiMocks.post.mockResolvedValue({ data: applyResult });
    const onApply = vi.fn();

    render(
      <CharacterAppearanceModal
        open
        onClose={() => undefined}
        onApply={onApply}
      />,
    );

    await screen.findByText('清姬 Lancer');
    fireEvent.click(screen.getByRole('button', { name: '复制提示词' }));

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        'kiyohime_(lancer)_(fate), long purple hair, wearing a white kimono, soft smile',
      ),
    );
    expect(apiMocks.post).toHaveBeenCalledWith(
      '/prompt-agent/appearance-presets/appearance_kiyohime/apply',
      { version: 1 },
    );
    expect(onApply).not.toHaveBeenCalled();
  });
});
