import { afterEach, describe, expect, it } from 'vitest';
import type { ExternalGalleryItem } from './api';
import {
  createExternalGalleryFilters,
  externalGalleryBindingKey,
  filterExternalGalleryItems,
  loadExternalGalleryActivity,
  recordExternalGalleryRecent,
  saveExternalGalleryActivity,
  toggleExternalGalleryFavorite,
} from './externalGalleryState';

function item(
  id: string,
  overrides: Partial<ExternalGalleryItem> = {},
): ExternalGalleryItem {
  return {
    id,
    name: id,
    category: '',
    system: '',
    angle: '',
    group: '',
    tags: [],
    path: `${id}.png`,
    thumb: '',
    search: id.toLocaleLowerCase(),
    image_url: `/image/${id}.png`,
    thumbnail_url: `/thumb/${id}.png`,
    ...overrides,
  };
}

afterEach(() => {
  localStorage.clear();
});

describe('external gallery state', () => {
  it('filters by keyword, metadata and tag', () => {
    const items = [
      item('pose-1', {
        name: '侧身站姿',
        category: '站姿',
        system: '基础',
        angle: '侧面',
        tags: ['全身', '自然'],
        search: 'pose-1 侧身站姿 站姿 基础 侧面 全身 自然',
      }),
      item('pose-2', {
        name: '坐姿',
        category: '坐姿',
        system: '基础',
        angle: '正面',
        tags: ['全身'],
        search: 'pose-2 坐姿 坐姿 基础 正面 全身',
      }),
    ];
    expect(
      filterExternalGalleryItems(
        items,
        {
          ...createExternalGalleryFilters(),
          keyword: '侧身',
          category: '站姿',
          system: '基础',
          angle: '侧面',
          tag: '自然',
          posePreset: '',
        },
        'all',
        [],
        [],
      ),
    ).toEqual([items[0]]);
  });

  it('persists favorites and recent items independently per binding', () => {
    const poseKey = externalGalleryBindingKey('pose', 'binding-a');
    const costumeKey = externalGalleryBindingKey('costume', 'binding-b');
    let activity = { favoritesByBinding: {}, recentByBinding: {} };
    activity = toggleExternalGalleryFavorite(activity, poseKey, 'pose-1');
    activity = recordExternalGalleryRecent(activity, poseKey, 'pose-2');
    activity = recordExternalGalleryRecent(activity, poseKey, 'pose-1');
    activity = toggleExternalGalleryFavorite(activity, costumeKey, 'costume-1');

    saveExternalGalleryActivity(activity);
    const loaded = loadExternalGalleryActivity();

    expect(loaded.favoritesByBinding[poseKey]).toEqual(['pose-1']);
    expect(loaded.favoritesByBinding[costumeKey]).toEqual(['costume-1']);
    expect(loaded.recentByBinding[poseKey]).toEqual(['pose-1', 'pose-2']);

    const recentItems = filterExternalGalleryItems(
      [item('pose-1'), item('pose-2')],
      createExternalGalleryFilters(),
      'recent',
      loaded.favoritesByBinding[poseKey],
      loaded.recentByBinding[poseKey],
    );
    expect(recentItems.map((entry) => entry.id)).toEqual(['pose-1', 'pose-2']);
  });

  it('filters managed pose images by their linked canonical preset', () => {
    const items = [
      item('pose-reference-1', { pose_preset_id: 'lying_back' }),
      item('pose-reference-2', { pose_preset_id: 'kneeling' }),
    ];
    expect(
      filterExternalGalleryItems(
        items,
        { ...createExternalGalleryFilters(), posePreset: 'lying_back' },
        'all',
        [],
        [],
      ).map((entry) => entry.id),
    ).toEqual(['pose-reference-1']);
  });
});
