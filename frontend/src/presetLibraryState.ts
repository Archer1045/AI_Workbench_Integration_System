export interface PresetLibraryFilters {
  keyword: string;
  categoryGroup: string;
  subcategory: string;
  rating: string;
  resource: string;
}

export interface PresetLibraryViewState {
  activeKind: string;
  selectedIds: Record<string, string>;
  viewMode: 'grid' | 'list';
  filtersByKind: Record<string, PresetLibraryFilters>;
}

export interface PresetCenterState {
  activeSection: string;
}

const LIBRARY_KEY = 'rider-studio:preset-library-view-v1';
const CENTER_KEY = 'rider-studio:preset-center-section-v1';

export function createPresetLibraryFilters(): PresetLibraryFilters {
  return {
    keyword: '',
    categoryGroup: '',
    subcategory: '',
    rating: '',
    resource: 'all',
  };
}

const DEFAULT_LIBRARY_STATE: PresetLibraryViewState = {
  activeKind: '',
  selectedIds: {},
  viewMode: 'grid',
  filtersByKind: {},
};

function normalizePresetLibraryFilters(value: unknown): PresetLibraryFilters {
  const raw =
    value && typeof value === 'object'
      ? (value as Record<string, unknown>)
      : {};
  return {
    keyword: String(raw.keyword || ''),
    categoryGroup: String(raw.categoryGroup || ''),
    subcategory: String(raw.subcategory || ''),
    rating: String(raw.rating || ''),
    resource: String(raw.resource || 'all'),
  };
}

function normalizeFiltersByKind(
  value: unknown,
): Record<string, PresetLibraryFilters> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([kind, filters]) => [
      String(kind),
      normalizePresetLibraryFilters(filters),
    ]),
  );
}

export function loadPresetLibraryViewState(): PresetLibraryViewState {
  try {
    const raw = localStorage.getItem(LIBRARY_KEY);
    if (!raw) return { ...DEFAULT_LIBRARY_STATE };
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const activeKind = String(parsed.activeKind || '');
    const filtersByKind = normalizeFiltersByKind(parsed.filtersByKind);
    if (Object.keys(filtersByKind).length === 0 && activeKind) {
      filtersByKind[activeKind] = normalizePresetLibraryFilters(parsed);
    }
    return {
      activeKind,
      selectedIds:
        parsed.selectedIds && typeof parsed.selectedIds === 'object'
          ? Object.fromEntries(
              Object.entries(
                parsed.selectedIds as Record<string, unknown>,
              ).map(([key, value]) => [String(key), String(value)]),
            )
          : {},
      viewMode: parsed.viewMode === 'list' ? 'list' : 'grid',
      filtersByKind,
    };
  } catch {
    return {
      ...DEFAULT_LIBRARY_STATE,
      selectedIds: {},
      filtersByKind: {},
    };
  }
}

export function savePresetLibraryViewState(
  state: PresetLibraryViewState,
): void {
  localStorage.setItem(LIBRARY_KEY, JSON.stringify(state));
}

export function loadPresetCenterState(): PresetCenterState {
  try {
    const raw = localStorage.getItem(CENTER_KEY);
    if (!raw) return { activeSection: 'browse' };
    const parsed = JSON.parse(raw) as Partial<PresetCenterState>;
    return { activeSection: String(parsed.activeSection || 'browse') };
  } catch {
    return { activeSection: 'browse' };
  }
}

export function savePresetCenterState(state: PresetCenterState): void {
  localStorage.setItem(CENTER_KEY, JSON.stringify(state));
}
