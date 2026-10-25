import type {
  PresetAssetCatalogItem,
  PresetAssetKind,
} from './api';
import {
  DEFAULT_PRESET_ASSET_FILTERS,
  loadPresetAssetFilters,
  normalizePresetAssetFilters,
  type PresetAssetFilters,
} from './presetAssetFilters';

export type PresetAssetTaskFilter =
  | 'active'
  | 'recoverable'
  | 'history'
  | 'all';

export type PresetAssetTaskStatusFilter =
  | ''
  | 'queued'
  | 'preparing'
  | 'running'
  | 'cancel_requested'
  | 'done'
  | 'error'
  | 'cancelled'
  | 'stopped'
  | 'interrupted';

export interface PresetAssetPageSelection {
  presetType: PresetAssetKind;
  presetId: string;
  label?: string;
}

export interface PresetAssetPageState {
  version: 1;
  filters: PresetAssetFilters;
  page: number;
  selection: PresetAssetPageSelection | null;
  taskCenterOpen: boolean;
  taskFilter: PresetAssetTaskFilter;
  taskStatus: PresetAssetTaskStatusFilter;
  listScrollTop: number;
  taskScrollTop: number;
}

export const PRESET_ASSET_PAGE_STATE_STORAGE_KEY =
  'rider-studio:preset-asset-page-v1';

const PRESET_ASSET_KINDS = new Set<PresetAssetKind>([
  'pose',
  'clothing',
  'scene',
  'body',
  'character',
]);
const TASK_FILTERS = new Set<PresetAssetTaskFilter>([
  'active',
  'recoverable',
  'history',
  'all',
]);
const TASK_STATUS_FILTERS = new Set<PresetAssetTaskStatusFilter>([
  '',
  'queued',
  'preparing',
  'running',
  'cancel_requested',
  'done',
  'error',
  'cancelled',
  'stopped',
  'interrupted',
]);

export const DEFAULT_PRESET_ASSET_PAGE_STATE: PresetAssetPageState = {
  version: 1,
  filters: { ...DEFAULT_PRESET_ASSET_FILTERS },
  page: 1,
  selection: null,
  taskCenterOpen: false,
  taskFilter: 'active',
  taskStatus: '',
  listScrollTop: 0,
  taskScrollTop: 0,
};

export function presetAssetSelectionKey(
  selection: Pick<PresetAssetPageSelection, 'presetType' | 'presetId'> | null,
): string {
  return selection
    ? `${selection.presetType}:${selection.presetId}`
    : '';
}

export function isPresetAssetSelectionVisible(
  selection: Pick<PresetAssetPageSelection, 'presetType' | 'presetId'> | null,
  items: readonly PresetAssetCatalogItem[],
  loadedQueryKey: string,
  currentQueryKey: string,
): boolean {
  if (!selection || loadedQueryKey !== currentQueryKey) return false;
  const key = presetAssetSelectionKey(selection);
  return items.some(
    (item) => `${item.preset_type}:${item.preset_id}` === key,
  );
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

function resolveStorage(storage?: StorageLike): StorageLike | null {
  if (storage) return storage;
  return typeof window === 'undefined' ? null : window.localStorage;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function normalizeScrollTop(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(0, value)
    : 0;
}

function normalizeSelection(
  value: unknown,
): PresetAssetPageSelection | null {
  if (!isRecord(value)) return null;
  const presetType = value.presetType;
  const presetId =
    typeof value.presetId === 'string' ? value.presetId.trim() : '';
  if (
    !PRESET_ASSET_KINDS.has(presetType as PresetAssetKind) ||
    !presetId
  ) {
    return null;
  }
  return {
    presetType: presetType as PresetAssetKind,
    presetId,
    ...(typeof value.label === 'string' && value.label
      ? { label: value.label }
      : {}),
  };
}

export function normalizePresetAssetPageState(
  value: unknown,
): PresetAssetPageState {
  if (!isRecord(value) || value.version !== 1) {
    return {
      ...DEFAULT_PRESET_ASSET_PAGE_STATE,
      filters: { ...DEFAULT_PRESET_ASSET_FILTERS },
    };
  }
  const page =
    typeof value.page === 'number' && Number.isFinite(value.page)
      ? Math.max(1, Math.floor(value.page))
      : 1;
  return {
    version: 1,
    filters: normalizePresetAssetFilters(value.filters),
    page,
    selection: normalizeSelection(value.selection),
    taskCenterOpen:
      typeof value.taskCenterOpen === 'boolean'
        ? value.taskCenterOpen
        : false,
    taskFilter: TASK_FILTERS.has(value.taskFilter as PresetAssetTaskFilter)
      ? (value.taskFilter as PresetAssetTaskFilter)
      : 'active',
    taskStatus: TASK_STATUS_FILTERS.has(
      value.taskStatus as PresetAssetTaskStatusFilter,
    )
      ? (value.taskStatus as PresetAssetTaskStatusFilter)
      : '',
    listScrollTop: normalizeScrollTop(value.listScrollTop),
    taskScrollTop: normalizeScrollTop(value.taskScrollTop),
  };
}

export function loadPresetAssetPageState(
  storage?: StorageLike,
): PresetAssetPageState {
  const target = resolveStorage(storage);
  if (!target) {
    return {
      ...DEFAULT_PRESET_ASSET_PAGE_STATE,
      filters: loadPresetAssetFilters(),
    };
  }
  try {
    const raw = target.getItem(PRESET_ASSET_PAGE_STATE_STORAGE_KEY);
    if (!raw) {
      return normalizePresetAssetPageState({
        ...DEFAULT_PRESET_ASSET_PAGE_STATE,
        filters: loadPresetAssetFilters(storage),
      });
    }
    return normalizePresetAssetPageState(JSON.parse(raw));
  } catch {
    return normalizePresetAssetPageState({
      ...DEFAULT_PRESET_ASSET_PAGE_STATE,
      filters: loadPresetAssetFilters(storage),
    });
  }
}

export function savePresetAssetPageState(
  state: PresetAssetPageState,
  storage?: StorageLike,
): void {
  const target = resolveStorage(storage);
  if (!target) return;
  try {
    target.setItem(
      PRESET_ASSET_PAGE_STATE_STORAGE_KEY,
      JSON.stringify(normalizePresetAssetPageState(state)),
    );
  } catch {
    // Persistence failure must not block the workshop.
  }
}
