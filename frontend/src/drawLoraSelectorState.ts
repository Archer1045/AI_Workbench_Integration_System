import type { LoraItem } from './api';

export type DrawLoraPurposeFilter = 'all' | 'drawing' | 'unknown';

export interface DrawLoraSelectorState {
  expanded: boolean;
  search: string;
  purpose: DrawLoraPurposeFilter;
  compatibleOnly: boolean;
}

export const DRAW_LORA_SELECTOR_KEY = 'rider-studio:lora-selector-v1';

export const DEFAULT_DRAW_LORA_SELECTOR_STATE: DrawLoraSelectorState = {
  expanded: false,
  search: '',
  purpose: 'all',
  compatibleOnly: true,
};

function isPurposeFilter(value: unknown): value is DrawLoraPurposeFilter {
  return value === 'all' || value === 'drawing' || value === 'unknown';
}

export function loadDrawLoraSelectorState(
  storage: Pick<Storage, 'getItem'> = localStorage,
): DrawLoraSelectorState {
  try {
    const raw = storage.getItem(DRAW_LORA_SELECTOR_KEY);
    if (!raw) return { ...DEFAULT_DRAW_LORA_SELECTOR_STATE };
    const parsed = JSON.parse(raw) as Partial<DrawLoraSelectorState>;
    return {
      expanded:
        typeof parsed.expanded === 'boolean'
          ? parsed.expanded
          : DEFAULT_DRAW_LORA_SELECTOR_STATE.expanded,
      search: typeof parsed.search === 'string' ? parsed.search : '',
      purpose: isPurposeFilter(parsed.purpose)
        ? parsed.purpose
        : DEFAULT_DRAW_LORA_SELECTOR_STATE.purpose,
      compatibleOnly:
        typeof parsed.compatibleOnly === 'boolean'
          ? parsed.compatibleOnly
          : DEFAULT_DRAW_LORA_SELECTOR_STATE.compatibleOnly,
    };
  } catch {
    return { ...DEFAULT_DRAW_LORA_SELECTOR_STATE };
  }
}

export function saveDrawLoraSelectorState(
  state: DrawLoraSelectorState,
  storage: Pick<Storage, 'setItem'> = localStorage,
): void {
  try {
    storage.setItem(DRAW_LORA_SELECTOR_KEY, JSON.stringify(state));
  } catch {
    // Local storage may be unavailable or full.
  }
}

export function filterDrawLoraItems(
  items: LoraItem[],
  state: Pick<DrawLoraSelectorState, 'search' | 'purpose' | 'compatibleOnly'>,
): LoraItem[] {
  const keyword = state.search.trim().toLowerCase();
  return items.filter((item) => {
    if (item.purpose === 'video') return false;
    if (state.compatibleOnly && item.compatible === false) return false;
    if (
      state.purpose !== 'all' &&
      (item.purpose || 'unknown') !== state.purpose
    ) {
      return false;
    }
    if (!keyword) return true;
    return `${item.name} ${item.incompatible_reason || ''} ${item.purpose || 'unknown'}`
      .toLowerCase()
      .includes(keyword);
  });
}
