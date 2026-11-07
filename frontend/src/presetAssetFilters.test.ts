import { describe, expect, it } from 'vitest';
import type { PresetAssetCatalogItem } from './api';
import {
  DEFAULT_PRESET_ASSET_FILTERS,
  PRESET_ASSET_FILTERS_STORAGE_KEY,
  filterPresetAssetItems,
  loadPresetAssetFilters,
  normalizePresetAssetFilters,
  savePresetAssetFilters,
} from './presetAssetFilters';

function item(
  overrides: Partial<PresetAssetCatalogItem>,
): PresetAssetCatalogItem {
  return {
    preset_type: 'pose',
    preset_id: 'pose_default',
    label: '默认体位',
    category: '单人',
    category_group: '姿势',
    subcategory: '站立',
    rating: '普通',
    restricted: false,
    image: null,
    has_image: false,
    active_version: null,
    source: null,
    ready_count: 0,
    running_count: 0,
    failed_count: 0,
    candidate_count: 0,
    order: 1,
    kind_label: '体位',
    ...overrides,
  };
}

describe('presetAssetFilters', () => {
  it('normalizes invalid persisted values to safe defaults', () => {
    expect(
      normalizePresetAssetFilters({
        kind: 'invalid',
        keyword: 42,
        resource: 'unknown',
        candidateStatus: 'unknown',
        taskStatus: 'unknown',
      }),
    ).toEqual(DEFAULT_PRESET_ASSET_FILTERS);
  });

  it('combines keyword, rating, category, and subcategory filters', () => {
    const items = [
      item({ preset_id: 'standing_a', label: '正面站立' }),
      item({
        preset_id: 'standing_b',
        label: '侧面站立',
        rating: 'R18',
        category_group: '姿势',
        subcategory: '坐姿',
      }),
      item({
        preset_id: 'scene_a',
        label: '室内站立',
        preset_type: 'scene',
        kind_label: '场景',
      }),
    ];
    expect(
      filterPresetAssetItems(items, {
        ...DEFAULT_PRESET_ASSET_FILTERS,
        keyword: '站立',
        rating: 'R18',
        categoryGroup: '姿势',
        subcategory: '坐姿',
      }).map((entry) => entry.preset_id),
    ).toEqual(['standing_b']);
  });

  it('filters by resource and task status', () => {
    const items = [
      item({ preset_id: 'missing' }),
      item({
        preset_id: 'ready',
        has_image: true,
        ready_count: 2,
        candidate_count: 2,
        candidate_status_counts: { ready: 2 },
      }),
      item({ preset_id: 'candidate', candidate_count: 3 }),
      item({
        preset_id: 'running',
        running_count: 1,
        candidate_status_counts: { running: 1 },
      }),
      item({
        preset_id: 'failed',
        failed_count: 1,
        candidate_status_counts: { failed: 1 },
      }),
    ];
    expect(
      filterPresetAssetItems(items, {
        ...DEFAULT_PRESET_ASSET_FILTERS,
        resource: 'ready',
      }).map((entry) => entry.preset_id),
    ).toEqual(['ready']);
    expect(
      filterPresetAssetItems(items, {
        ...DEFAULT_PRESET_ASSET_FILTERS,
        resource: 'without-image',
      }).map((entry) => entry.preset_id),
    ).toEqual(['missing', 'candidate', 'running', 'failed']);
    expect(
      filterPresetAssetItems(items, {
        ...DEFAULT_PRESET_ASSET_FILTERS,
        resource: 'with-candidate',
      }).map((entry) => entry.preset_id),
    ).toEqual(['ready', 'candidate']);
    expect(
      filterPresetAssetItems(items, {
        ...DEFAULT_PRESET_ASSET_FILTERS,
        candidateStatus: 'running',
      }).map((entry) => entry.preset_id),
    ).toEqual(['running']);
  });

  it('combines material, candidate, and task status filters', () => {
    const items = [
      item({
        preset_id: 'matching',
        candidate_status_counts: { ready: 1 },
        task_status_counts: { failed: 1 },
      }),
      item({
        preset_id: 'wrong-candidate',
        candidate_status_counts: { running: 1 },
        task_status_counts: { failed: 1 },
      }),
      item({
        preset_id: 'wrong-task',
        candidate_status_counts: { ready: 1 },
        task_status_counts: { done: 1 },
      }),
    ];

    expect(
      filterPresetAssetItems(items, {
        ...DEFAULT_PRESET_ASSET_FILTERS,
        resource: 'without-image',
        candidateStatus: 'ready',
        taskStatus: 'failed',
      }).map((entry) => entry.preset_id),
    ).toEqual(['matching']);
  });

  it('loads and saves normalized filter state', () => {
    localStorage.clear();
    expect(loadPresetAssetFilters()).toEqual(DEFAULT_PRESET_ASSET_FILTERS);

    savePresetAssetFilters({
      ...DEFAULT_PRESET_ASSET_FILTERS,
      kind: 'clothing',
      keyword: '泳装',
      resource: 'without-image',
      candidateStatus: 'interrupted',
      taskStatus: 'failed',
    });
    expect(loadPresetAssetFilters()).toMatchObject({
      kind: 'clothing',
      keyword: '泳装',
      resource: 'without-image',
      candidateStatus: 'interrupted',
      taskStatus: 'failed',
    });

    localStorage.setItem(PRESET_ASSET_FILTERS_STORAGE_KEY, '{bad json');
    expect(loadPresetAssetFilters()).toEqual(DEFAULT_PRESET_ASSET_FILTERS);
  });
});
