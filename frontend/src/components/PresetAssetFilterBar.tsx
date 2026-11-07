import { ClearOutlined } from '@ant-design/icons';
import { Button, Input, Select, Tabs, Tag } from 'antd';
import type {
  PresetAssetCatalogQueryResponse,
  PresetAssetCatalogSort,
  PresetAssetKind,
} from '../api';
import {
  type PresetAssetCandidateStatusFilter,
  type PresetAssetFilters,
  type PresetAssetResourceFilter,
  type PresetAssetTaskStatusFilter,
} from '../presetAssetFilters';

const RESOURCE_OPTIONS: {
  label: string;
  value: PresetAssetResourceFilter;
}[] = [
  { label: '全部资源状态', value: 'all' },
  { label: '有正式图', value: 'with-image' },
  { label: '无正式图', value: 'without-image' },
  { label: '有源图', value: 'with-source' },
  { label: '无源图', value: 'without-source' },
  { label: '有候选', value: 'with-candidate' },
  { label: '待验收', value: 'ready' },
  { label: '生成中', value: 'running' },
  { label: '失败', value: 'failed' },
];

const SORT_OPTIONS: {
  label: string;
  value: PresetAssetCatalogSort;
}[] = [
  { label: '默认顺序', value: 'default' },
  { label: '按名称', value: 'name' },
  { label: '最近更新', value: 'updated_at' },
];

const CANDIDATE_STATUS_OPTIONS: {
  label: string;
  value: Exclude<PresetAssetCandidateStatusFilter, ''>;
}[] = [
  { label: '排队中', value: 'queued' },
  { label: '准备中', value: 'preparing' },
  { label: '生成中', value: 'running' },
  { label: '取消中', value: 'cancel_requested' },
  { label: '待验收', value: 'ready' },
  { label: '已取消', value: 'cancelled' },
  { label: '已中断', value: 'interrupted' },
  { label: '失败', value: 'failed' },
];

const TASK_STATUS_OPTIONS: {
  label: string;
  value: Exclude<PresetAssetTaskStatusFilter, ''>;
}[] = [
  { label: '排队中', value: 'queued' },
  { label: '准备中', value: 'preparing' },
  { label: '生成中', value: 'running' },
  { label: '取消中', value: 'cancel_requested' },
  { label: '已完成', value: 'done' },
  { label: '失败', value: 'failed' },
  { label: '已取消', value: 'cancelled' },
  { label: '已中断', value: 'interrupted' },
];

export default function PresetAssetFilterBar({
  catalog,
  filters,
  visibleCount,
  onChange,
  onReset,
}: {
  catalog: PresetAssetCatalogQueryResponse | null;
  filters: PresetAssetFilters;
  visibleCount: number;
  onChange: (patch: Partial<PresetAssetFilters>) => void;
  onReset: () => void;
}) {
  const kindFacets = catalog?.facets.kinds || [];
  const categoryGroups = catalog?.facets.category_groups || [];
  const subcategories = catalog?.facets.subcategories || [];
  const taskStatusFacets = catalog?.facets.task_statuses || [];
  const taskStatusOptions = taskStatusFacets.length
    ? taskStatusFacets.map((facet) => ({
        label: `${facet.label} (${facet.count})`,
        value: facet.value as Exclude<PresetAssetTaskStatusFilter, ''>,
      }))
    : TASK_STATUS_OPTIONS;
  if (
    filters.taskStatus &&
    !taskStatusOptions.some((option) => option.value === filters.taskStatus)
  ) {
    const fallback = TASK_STATUS_OPTIONS.find(
      (option) => option.value === filters.taskStatus,
    );
    if (fallback) taskStatusOptions.unshift(fallback);
  }
  const totalCount = catalog?.total || 0;
  const hasActiveFilters = Boolean(
    filters.keyword ||
      filters.resource !== 'all' ||
      filters.candidateStatus ||
      filters.taskStatus ||
      filters.rating ||
      filters.categoryGroup ||
      filters.subcategory ||
      filters.sort !== 'default',
  );

  return (
    <section className="preset-asset-filter-bar">
      <Tabs
        className="preset-asset-filter-tabs"
        size="small"
        activeKey={filters.kind}
        onChange={(value) =>
          onChange({
            kind: value as PresetAssetKind,
            categoryGroup: '',
            subcategory: '',
          })
        }
        items={kindFacets.map((facet) => ({
          key: facet.value,
          label: (
            <span>
              {facet.label}
              <Tag>{facet.count}</Tag>
            </span>
          ),
          children: null,
        }))}
      />
      <div className="preset-asset-filter-grid">
        <Input.Search
          allowClear
          value={filters.keyword}
          onChange={(event) => onChange({ keyword: event.target.value })}
          placeholder="搜索名称、ID、分类"
          size="small"
        />
        <Select
          size="small"
          value={filters.resource}
          options={RESOURCE_OPTIONS}
          onChange={(value) => onChange({ resource: value })}
        />
        <Select
          allowClear
          size="small"
          value={filters.candidateStatus || undefined}
          placeholder="全部候选状态"
          options={CANDIDATE_STATUS_OPTIONS}
          onChange={(value) => onChange({ candidateStatus: value || '' })}
        />
        <Select
          allowClear
          size="small"
          value={filters.taskStatus || undefined}
          placeholder="全部任务项状态"
          options={taskStatusOptions}
          onChange={(value) => onChange({ taskStatus: value || '' })}
        />
        <Select
          size="small"
          value={filters.sort}
          options={SORT_OPTIONS}
          onChange={(value) => onChange({ sort: value })}
        />
        <Select
          allowClear
          size="small"
          value={filters.rating || undefined}
          placeholder="全部评级"
          options={[
            { label: '普通', value: '普通' },
            { label: 'R18', value: 'R18' },
          ]}
          onChange={(value) => onChange({ rating: value || '' })}
        />
        <Select
          allowClear
          size="small"
          value={filters.categoryGroup || undefined}
          placeholder="全部一级分类"
          options={categoryGroups.map((facet) => ({
            label: `${facet.label} (${facet.count})`,
            value: facet.value,
          }))}
          onChange={(value) =>
            onChange({
              categoryGroup: value || '',
              subcategory: '',
            })
          }
        />
        <Select
          allowClear
          disabled={!filters.categoryGroup}
          size="small"
          value={filters.subcategory || undefined}
          placeholder={filters.categoryGroup ? '全部二级分类' : '先选一级分类'}
          options={subcategories.map((facet) => ({
            label: `${facet.label} (${facet.count})`,
            value: facet.value,
          }))}
          onChange={(value) => onChange({ subcategory: value || '' })}
        />
      </div>
      <div className="preset-asset-filter-summary">
        <span>
          本页 <strong>{visibleCount}</strong> / 共 {totalCount} 项
        </span>
        <Button
          type="link"
          size="small"
          icon={<ClearOutlined />}
          disabled={!hasActiveFilters}
          onClick={onReset}
        >
          清空筛选
        </Button>
      </div>
    </section>
  );
}
