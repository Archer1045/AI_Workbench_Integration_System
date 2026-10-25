import { afterEach, describe, expect, it } from 'vitest';
import {
  createPresetLibraryFilters,
  loadPresetLibraryViewState,
  savePresetLibraryViewState,
} from './presetLibraryState';

const LIBRARY_KEY = 'rider-studio:preset-library-view-v1';

afterEach(() => {
  localStorage.clear();
});

describe('preset library state', () => {
  it('migrates legacy global filters into the active preset kind', () => {
    localStorage.setItem(
      LIBRARY_KEY,
      JSON.stringify({
        activeKind: 'pose',
        selectedIds: { pose: 'pose-1' },
        viewMode: 'list',
        keyword: '站姿',
        categoryGroup: '单人',
        subcategory: '站立',
        rating: '普通',
        resource: 'with_image',
      }),
    );

    const state = loadPresetLibraryViewState();

    expect(state.activeKind).toBe('pose');
    expect(state.selectedIds).toEqual({ pose: 'pose-1' });
    expect(state.viewMode).toBe('list');
    expect(state.filtersByKind).toEqual({
      pose: {
        keyword: '站姿',
        categoryGroup: '单人',
        subcategory: '站立',
        rating: '普通',
        resource: 'with_image',
      },
    });
  });

  it('round-trips independent filters for each preset kind', () => {
    savePresetLibraryViewState({
      activeKind: 'character',
      selectedIds: { character: 'character-1' },
      viewMode: 'grid',
      filtersByKind: {
        pose: {
          ...createPresetLibraryFilters(),
          categoryGroup: '单人',
          subcategory: '站立',
        },
        character: {
          ...createPresetLibraryFilters(),
          categoryGroup: '角色',
          keyword: '礼服',
        },
      },
    });

    const state = loadPresetLibraryViewState();

    expect(state.filtersByKind.pose).toMatchObject({
      categoryGroup: '单人',
      subcategory: '站立',
      keyword: '',
    });
    expect(state.filtersByKind.character).toMatchObject({
      categoryGroup: '角色',
      subcategory: '',
      keyword: '礼服',
    });
  });
});
