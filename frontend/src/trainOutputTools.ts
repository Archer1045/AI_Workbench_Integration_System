export type TrainingOutputKind = 'all' | 'raw' | 'comfy';

export interface TrainingOutputLike {
  name: string;
  modified_at?: string;
}

export interface TrainingOutputGroup<T extends TrainingOutputLike> {
  key: string;
  label: string;
  items: T[];
  favorite: boolean;
  latest: number;
}

export function trainingOutputKind(name: string): 'raw' | 'comfy' {
  return name.endsWith('_comfy.safetensors') ? 'comfy' : 'raw';
}

export function trainingOutputFamily(name: string): string {
  const filename = name.replace(/\\/g, '/').split('/').pop() || name;
  return filename
    .replace(/\.safetensors$/i, '')
    .replace(/_comfy$/i, '')
    .replace(/-(?:\d{4,8}-state|state|\d{4,8})$/i, '');
}

export function buildTrainingOutputGroups<T extends TrainingOutputLike>(
  items: T[],
  options: {
    search: string;
    kind: TrainingOutputKind;
    favorites: string[];
  },
): TrainingOutputGroup<T>[] {
  const query = options.search.trim().toLowerCase();
  const favorites = new Set(options.favorites);
  const groups = new Map<string, TrainingOutputGroup<T>>();

  for (const item of items) {
    if (options.kind !== 'all' && trainingOutputKind(item.name) !== options.kind) {
      continue;
    }
    const key = trainingOutputFamily(item.name);
    if (query && !item.name.toLowerCase().includes(query) && !key.toLowerCase().includes(query)) {
      continue;
    }
    const modified = item.modified_at ? Date.parse(item.modified_at) || 0 : 0;
    const group = groups.get(key) || {
      key,
      label: key,
      items: [],
      favorite: false,
      latest: 0,
    };
    group.items.push(item);
    group.favorite ||= favorites.has(item.name);
    group.latest = Math.max(group.latest, modified);
    groups.set(key, group);
  }

  return [...groups.values()]
    .map((group) => ({
      ...group,
      items: [...group.items].sort((left, right) => {
        const favoriteDelta =
          Number(favorites.has(right.name)) - Number(favorites.has(left.name));
        const modifiedDelta =
          (right.modified_at ? Date.parse(right.modified_at) || 0 : 0) -
          (left.modified_at ? Date.parse(left.modified_at) || 0 : 0);
        return favoriteDelta || modifiedDelta || left.name.localeCompare(right.name);
      }),
    }))
    .sort(
      (left, right) =>
        Number(right.favorite) - Number(left.favorite) ||
        right.latest - left.latest ||
        left.label.localeCompare(right.label),
    );
}

export function toggleFavoriteName(values: string[], name: string): string[] {
  return values.includes(name)
    ? values.filter((item) => item !== name)
    : [...values, name];
}

export function addRecentCompareCombo(
  combos: string[][],
  names: string[],
  limit = 5,
): string[][] {
  const normalized = [...new Set(names.filter(Boolean))];
  if (normalized.length === 0) return combos;
  const signature = [...normalized].sort().join('\u0000');
  return [
    normalized,
    ...combos.filter((combo) => [...combo].sort().join('\u0000') !== signature),
  ].slice(0, limit);
}
