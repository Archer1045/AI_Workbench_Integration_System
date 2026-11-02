import type {
  ExternalGalleryItem,
  ExternalGalleryKind,
} from './api';

export interface ExternalGalleryFilters {
  keyword: string;
  category: string;
  system: string;
  angle: string;
  tag: string;
  posePreset: string;
}

export type ExternalGalleryActivityMode = 'all' | 'favorites' | 'recent';

export interface ExternalGalleryActivity {
  favoritesByBinding: Record<string, string[]>;
  recentByBinding: Record<string, string[]>;
}

const ACTIVITY_KEY = 'rider-studio:external-gallery-activity-v1';

export function createExternalGalleryFilters(): ExternalGalleryFilters {
  return {
    keyword: '',
    category: '',
    system: '',
    angle: '',
    tag: '',
    posePreset: '',
  };
}

export function externalGalleryBindingKey(
  kind: ExternalGalleryKind,
  bindingId: string,
): string {
  return `${kind}:${bindingId || 'unbound'}`;
}

function normalizeIds(value: unknown): Record<string, string[]> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, raw]) => [
      key,
      Array.from(
        new Set(
          (Array.isArray(raw) ? raw : [])
            .map((item) => String(item).trim())
            .filter(Boolean),
        ),
      ),
    ]),
  );
}

export function loadExternalGalleryActivity(): ExternalGalleryActivity {
  try {
    const raw = localStorage.getItem(ACTIVITY_KEY);
    if (!raw) return { favoritesByBinding: {}, recentByBinding: {} };
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      favoritesByBinding: normalizeIds(parsed.favoritesByBinding),
      recentByBinding: normalizeIds(parsed.recentByBinding),
    };
  } catch {
    return { favoritesByBinding: {}, recentByBinding: {} };
  }
}

export function saveExternalGalleryActivity(
  activity: ExternalGalleryActivity,
): void {
  localStorage.setItem(
    ACTIVITY_KEY,
    JSON.stringify({
      favoritesByBinding: normalizeIds(activity.favoritesByBinding),
      recentByBinding: normalizeIds(activity.recentByBinding),
    }),
  );
}

export function toggleExternalGalleryFavorite(
  activity: ExternalGalleryActivity,
  bindingKey: string,
  itemId: string,
): ExternalGalleryActivity {
  const current = activity.favoritesByBinding[bindingKey] || [];
  return {
    ...activity,
    favoritesByBinding: {
      ...activity.favoritesByBinding,
      [bindingKey]: current.includes(itemId)
        ? current.filter((item) => item !== itemId)
        : [itemId, ...current],
    },
  };
}

export function recordExternalGalleryRecent(
  activity: ExternalGalleryActivity,
  bindingKey: string,
  itemId: string,
  limit = 20,
): ExternalGalleryActivity {
  const current = activity.recentByBinding[bindingKey] || [];
  return {
    ...activity,
    recentByBinding: {
      ...activity.recentByBinding,
      [bindingKey]: [itemId, ...current.filter((item) => item !== itemId)].slice(
        0,
        Math.max(1, limit),
      ),
    },
  };
}

export function filterExternalGalleryItems(
  items: ExternalGalleryItem[],
  filters: ExternalGalleryFilters,
  activityMode: ExternalGalleryActivityMode,
  favorites: string[],
  recent: string[],
): ExternalGalleryItem[] {
  const keyword = filters.keyword.trim().toLocaleLowerCase();
  const reference = activityMode === 'recent' ? recent : [];
  const filtered = items.filter((item) => {
    if (keyword && !item.search.includes(keyword)) return false;
    if (filters.category && item.category !== filters.category) return false;
    if (filters.system && item.system !== filters.system) return false;
    if (filters.angle && item.angle !== filters.angle) return false;
    if (filters.tag && !item.tags.includes(filters.tag)) return false;
    if (filters.posePreset && item.pose_preset_id !== filters.posePreset) {
      return false;
    }
    if (activityMode === 'favorites' && !favorites.includes(item.id)) return false;
    if (activityMode === 'recent' && !recent.includes(item.id)) return false;
    return true;
  });
  if (activityMode !== 'recent') return filtered;
  return filtered.sort(
    (left, right) => reference.indexOf(left.id) - reference.indexOf(right.id),
  );
}
