import { describe, expect, it } from 'vitest';

import type { PresetAssetCatalogItem } from './api';
import {
  isPresetAssetSelectionVisible,
  normalizePresetAssetPageState,
  presetAssetSelectionKey,
} from './presetAssetPageState';

function catalogItem(presetId: string): PresetAssetCatalogItem {
  return {
    preset_type: 'pose',
    preset_id: presetId,
    label: presetId,
    category: '测试',
    category_group: '测试',
    subcategory: '',
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
  };
}

describe('presetAssetPageState', () => {
  it('builds stable selection keys and only accepts visible current responses', () => {
    const selection = { presetType: 'pose' as const, presetId: 'pose-a' };
    const items = [catalogItem('pose-a')];
    const queryKey = '{"kind":"pose"}';

    expect(presetAssetSelectionKey(selection)).toBe('pose:pose-a');
    expect(
      isPresetAssetSelectionVisible(selection, items, queryKey, queryKey),
    ).toBe(true);
    expect(
      isPresetAssetSelectionVisible(
        selection,
        items,
        '{"kind":"old"}',
        queryKey,
      ),
    ).toBe(false);
    expect(
      isPresetAssetSelectionVisible(
        { presetType: 'pose', presetId: 'missing' },
        items,
        queryKey,
        queryKey,
      ),
    ).toBe(false);
  });

  it('normalizes malformed persisted state without blocking the workshop', () => {
    const state = normalizePresetAssetPageState({
      version: 1,
      filters: {
        kind: 'scene',
        resource: 'without-image',
        sort: 'updated_at',
        taskStatus: 'failed',
      },
      page: -3,
      selection: { presetType: 'invalid', presetId: 'x' },
      taskCenterOpen: true,
      taskFilter: 'recoverable',
      taskStatus: 'interrupted',
      listScrollTop: -12,
      taskScrollTop: 'nope',
    });

    expect(state.page).toBe(1);
    expect(state.selection).toBeNull();
    expect(state.filters.kind).toBe('scene');
    expect(state.filters.resource).toBe('without-image');
    expect(state.filters.sort).toBe('updated_at');
    expect(state.filters.taskStatus).toBe('failed');
    expect(state.taskCenterOpen).toBe(true);
    expect(state.taskFilter).toBe('recoverable');
    expect(state.taskStatus).toBe('interrupted');
    expect(state.listScrollTop).toBe(0);
    expect(state.taskScrollTop).toBe(0);

    expect(
      normalizePresetAssetPageState({ version: 1, taskStatus: 'invalid' })
        .taskStatus,
    ).toBe('');
    expect(
      normalizePresetAssetPageState({ version: 1 }).taskStatus,
    ).toBe('');
  });
});
