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

export interface PresetLibraryActivity {
  favoritesByKind: Record<string, string[]>;
  recentByKind: Record<string, string[]>;
}

const LIBRARY_KEY = 'rider-studio:preset-library-view-v1';
const CENTER_KEY = 'rider-studio:preset-center-section-v1';
const ACTIVITY_KEY = 'rider-studio:preset-library-activity-v1';

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

function normalizeIdsByKind(value: unknown): Record<string, string[]> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([kind, ids]) => [
      String(kind),
      Array.from(
        new Set(
          (Array.isArray(ids) ? ids : [])
            .map((id) => String(id).trim())
            .filter(Boolean),
        ),
      ),
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

export function loadPresetLibraryActivity(): PresetLibraryActivity {
  try {
    const raw = localStorage.getItem(ACTIVITY_KEY);
    if (!raw) return { favoritesByKind: {}, recentByKind: {} };
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      favoritesByKind: normalizeIdsByKind(parsed.favoritesByKind),
      recentByKind: normalizeIdsByKind(parsed.recentByKind),
    };
  } catch {
    return { favoritesByKind: {}, recentByKind: {} };
  }
}

export function savePresetLibraryActivity(
  state: PresetLibraryActivity,
): void {
  localStorage.setItem(
    ACTIVITY_KEY,
    JSON.stringify({
      favoritesByKind: normalizeIdsByKind(state.favoritesByKind),
      recentByKind: normalizeIdsByKind(state.recentByKind),
    }),
  );
}

export function togglePresetLibraryFavorite(
  state: PresetLibraryActivity,
  kind: string,
  id: string,
): PresetLibraryActivity {
  const current = state.favoritesByKind[kind] || [];
  return {
    ...state,
    favoritesByKind: {
      ...state.favoritesByKind,
      [kind]: current.includes(id)
        ? current.filter((item) => item !== id)
        : [id, ...current],
    },
  };
}

export function recordPresetLibraryRecent(
  state: PresetLibraryActivity,
  kind: string,
  id: string,
  limit = 8,
): PresetLibraryActivity {
  const current = state.recentByKind[kind] || [];
  return {
    ...state,
    recentByKind: {
      ...state.recentByKind,
      [kind]: [id, ...current.filter((item) => item !== id)].slice(
        0,
        Math.max(1, limit),
      ),
    },
  };
}
