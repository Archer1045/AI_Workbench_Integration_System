import type {
  PresetAssetCatalog,
  PresetAssetCatalogItem,
  PresetAssetCatalogSort,
  PresetAssetCandidateStatus,
  PresetAssetKind,
  PresetAssetTaskStatus,
} from './api';

export type PresetAssetResourceFilter =
  | 'all'
  | 'with-image'
  | 'without-image'
  | 'with-source'
  | 'without-source'
  | 'with-candidate'
  | 'ready'
  | 'running'
  | 'failed';

export type PresetAssetCandidateStatusFilter =
  | ''
  | PresetAssetCandidateStatus;

export type PresetAssetTaskStatusFilter = '' | PresetAssetTaskStatus;

export interface PresetAssetFilters {
  kind: PresetAssetKind;
  keyword: string;
  resource: PresetAssetResourceFilter;
  candidateStatus: PresetAssetCandidateStatusFilter;
  taskStatus: PresetAssetTaskStatusFilter;
  rating: string;
  categoryGroup: string;
  subcategory: string;
  sort: PresetAssetCatalogSort;
}

export const DEFAULT_PRESET_ASSET_FILTERS: PresetAssetFilters = {
  kind: 'pose',
  keyword: '',
  resource: 'all',
  candidateStatus: '',
  taskStatus: '',
  rating: '',
  categoryGroup: '',
  subcategory: '',
  sort: 'default',
};

export const PRESET_ASSET_FILTERS_STORAGE_KEY =
  'rider-studio:preset-asset-filters-v1';

const PRESET_ASSET_KINDS = new Set<PresetAssetKind>([
  'pose',
  'clothing',
  'scene',
  'body',
  'character',
]);

const RESOURCE_FILTERS = new Set<PresetAssetResourceFilter>([
  'all',
  'with-image',
  'without-image',
  'with-source',
  'without-source',
  'with-candidate',
  'ready',
  'running',
  'failed',
]);

const CATALOG_SORTS = new Set<PresetAssetCatalogSort>([
  'default',
  'name',
  'updated_at',
]);

const CANDIDATE_STATUSES = new Set<PresetAssetCandidateStatus>([
  'queued',
  'preparing',
  'running',
  'cancel_requested',
  'ready',
  'cancelled',
  'interrupted',
  'failed',
]);
const TASK_STATUSES = new Set<PresetAssetTaskStatus>([
  'queued',
  'preparing',
  'running',
  'cancel_requested',
  'done',
  'failed',
  'cancelled',
  'interrupted',
]);

function itemCategoryGroup(item: PresetAssetCatalogItem): string {
  return item.category_group || item.category || '其他';
}

function itemSubcategory(item: PresetAssetCatalogItem): string {
  return item.subcategory || '其他';
}

function matchesResource(
  item: PresetAssetCatalogItem,
  resource: PresetAssetResourceFilter,
): boolean {
  switch (resource) {
    case 'with-image':
      return item.has_image;
    case 'without-image':
      return !item.has_image;
    case 'with-source':
      return Boolean(item.source);
    case 'without-source':
      return !item.source;
    case 'with-candidate':
      return item.candidate_count > 0;
    case 'ready':
      return item.ready_count > 0;
    case 'running':
      return item.running_count > 0;
    case 'failed':
      return item.failed_count > 0;
    default:
      return true;
  }
}

export function normalizePresetAssetFilters(
  value: unknown,
): PresetAssetFilters {
  if (!value || typeof value !== 'object') {
    return { ...DEFAULT_PRESET_ASSET_FILTERS };
  }
  const candidate = value as Partial<PresetAssetFilters>;
  const kind =
    candidate.kind && PRESET_ASSET_KINDS.has(candidate.kind)
      ? candidate.kind
      : DEFAULT_PRESET_ASSET_FILTERS.kind;
  const resource =
    candidate.resource && RESOURCE_FILTERS.has(candidate.resource)
      ? candidate.resource
      : DEFAULT_PRESET_ASSET_FILTERS.resource;
  const sort =
    candidate.sort && CATALOG_SORTS.has(candidate.sort)
      ? candidate.sort
      : DEFAULT_PRESET_ASSET_FILTERS.sort;
  const candidateStatus =
    candidate.candidateStatus &&
    CANDIDATE_STATUSES.has(candidate.candidateStatus)
      ? candidate.candidateStatus
      : DEFAULT_PRESET_ASSET_FILTERS.candidateStatus;
  const taskStatus =
    candidate.taskStatus && TASK_STATUSES.has(candidate.taskStatus)
      ? candidate.taskStatus
      : DEFAULT_PRESET_ASSET_FILTERS.taskStatus;
  return {
    kind,
    keyword:
      typeof candidate.keyword === 'string' ? candidate.keyword : '',
    resource,
    candidateStatus,
    taskStatus,
    rating: typeof candidate.rating === 'string' ? candidate.rating : '',
    categoryGroup:
      typeof candidate.categoryGroup === 'string'
        ? candidate.categoryGroup
        : '',
    subcategory:
      typeof candidate.subcategory === 'string'
        ? candidate.subcategory
        : '',
    sort,
  };
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

function resolveStorage(storage?: StorageLike): StorageLike | null {
  if (storage) return storage;
  return typeof window === 'undefined' ? null : window.localStorage;
}

export function loadPresetAssetFilters(
  storage?: StorageLike,
): PresetAssetFilters {
  const target = resolveStorage(storage);
  if (!target) return { ...DEFAULT_PRESET_ASSET_FILTERS };
  try {
    const raw = target.getItem(PRESET_ASSET_FILTERS_STORAGE_KEY);
    return normalizePresetAssetFilters(raw ? JSON.parse(raw) : null);
  } catch {
    return { ...DEFAULT_PRESET_ASSET_FILTERS };
  }
}

export function savePresetAssetFilters(
  filters: PresetAssetFilters,
  storage?: StorageLike,
): void {
  const target = resolveStorage(storage);
  if (!target) return;
  try {
    target.setItem(
      PRESET_ASSET_FILTERS_STORAGE_KEY,
      JSON.stringify(normalizePresetAssetFilters(filters)),
    );
  } catch {
    // Persistence failure must not block the workshop.
  }
}

export function filterPresetAssetItems(
  items: PresetAssetCatalogItem[],
  filters: PresetAssetFilters,
): PresetAssetCatalogItem[] {
  const keyword = filters.keyword.trim().toLowerCase();
  return items.filter((item) => {
    if (!matchesResource(item, filters.resource)) return false;
    if (
      filters.candidateStatus &&
      Number(
        item.candidate_status_counts?.[filters.candidateStatus] || 0,
      ) <= 0
    ) {
      return false;
    }
    if (
      filters.taskStatus &&
      Number(item.task_status_counts?.[filters.taskStatus] || 0) <= 0
    ) {
      return false;
    }
    if (filters.rating && item.rating !== filters.rating) return false;
    if (
      filters.categoryGroup &&
      itemCategoryGroup(item) !== filters.categoryGroup
    ) {
      return false;
    }
    if (
      filters.subcategory &&
      itemSubcategory(item) !== filters.subcategory
    ) {
      return false;
    }
    if (!keyword) return true;
    return [
      item.label,
      item.preset_id,
      item.category,
      item.category_group,
      item.subcategory,
      item.kind_label,
    ]
      .join(' ')
      .toLowerCase()
      .includes(keyword);
  });
}

export function getPresetAssetKindItems(
  catalog: PresetAssetCatalog | null,
  kind: PresetAssetKind,
): PresetAssetCatalogItem[] {
  return catalog?.items.find((group) => group.kind === kind)?.items || [];
}

export function presetAssetCategoryGroups(
  items: PresetAssetCatalogItem[],
): string[] {
  return Array.from(new Set(items.map(itemCategoryGroup))).sort((left, right) =>
    left.localeCompare(right, 'zh-CN'),
  );
}

export function presetAssetSubcategories(
  items: PresetAssetCatalogItem[],
  categoryGroup: string,
): string[] {
  return Array.from(
    new Set(
      items
        .filter(
          (item) => !categoryGroup || itemCategoryGroup(item) === categoryGroup,
        )
        .map(itemSubcategory),
    ),
  ).sort((left, right) => left.localeCompare(right, 'zh-CN'));
}
