import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { PresetAssetCatalogItem } from '../api';

vi.mock('../stores/presetAssetStore', () => ({
  presetAssetStore: { selection: null },
}));

import PresetAssetList from './PresetAssetList';

function item(
  presetId: string,
  overrides: Partial<PresetAssetCatalogItem> = {},
): PresetAssetCatalogItem {
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
    order: 0,
    kind_label: '体位',
    ...overrides,
  };
}

function renderList(items: PresetAssetCatalogItem[]) {
  render(
    <PresetAssetList
      items={items}
      loading={false}
      filterKey="test"
      page={1}
      pageSize={40}
      total={items.length}
      emptyText="无匹配项"
      onSelect={vi.fn()}
      onPageChange={vi.fn()}
      scrollTop={0}
      onScrollTopChange={vi.fn()}
    />,
  );
}

describe('PresetAssetList', () => {
  it('summarizes page status and exposes the next action for missing images', () => {
    renderList([
      item('ungenerated'),
      item('ready', { ready_count: 2, candidate_count: 2 }),
      item('running', {
        has_image: true,
        running_count: 1,
        candidate_count: 1,
      }),
      item('failed', {
        failed_count: 1,
        candidate_count: 1,
      }),
    ]);

    const summary = screen.getByLabelText('本页资源状态汇总');
    expect(within(summary).getByText('正式图 1')).toBeInTheDocument();
    expect(within(summary).getByText('待验收 1')).toBeInTheDocument();
    expect(within(summary).getByText('生成中 1')).toBeInTheDocument();
    expect(within(summary).getByText('失败 1')).toBeInTheDocument();
    expect(within(summary).getByText('未生成 1')).toBeInTheDocument();

    expect(
      screen.getByLabelText('ungenerated 下一步：单独生成'),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('ready 下一步：查看并人工采纳'),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('running 下一步：查看生成进度'),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('failed 下一步：查看失败结果'),
    ).toBeInTheDocument();
  });
});
