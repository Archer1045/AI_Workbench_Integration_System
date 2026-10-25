import type {
  PresetAssetCropMode,
  PresetAssetKind,
  PresetAssetLoraStrengths,
  PresetAssetSeedStrategy,
  PresetAssetSettings,
} from './api';

export const PRESET_ASSET_SETTINGS_STORAGE_KEY =
  'rider-studio:preset-asset-settings-v1';
export const PRESET_ASSET_SETTINGS_SCHEMES_STORAGE_KEY =
  'rider-studio:preset-asset-settings-schemes-v1';

const STORAGE_VERSION = 2;
const SCHEME_STORAGE_VERSION = 1;
const PRESET_ASSET_KINDS: PresetAssetKind[] = [
  'pose',
  'clothing',
  'scene',
  'body',
  'character',
];

const SEED_STRATEGIES = new Set<PresetAssetSeedStrategy>([
  'fixed',
  'random',
  'derive',
]);

const CROP_MODES = new Set<PresetAssetCropMode>(['cover', 'contain']);

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;
type DraftMap = Partial<Record<PresetAssetKind, PresetAssetSettings>>;

export interface PresetAssetSettingsScheme {
  id: string;
  name: string;
  preset_type: PresetAssetKind;
  settings: PresetAssetSettings;
  updated_at: string;
}

interface DraftDocument {
  v: 2;
  drafts: DraftMap;
}

interface SchemeDocument {
  v: 1;
  schemes: PresetAssetSettingsScheme[];
}

function resolveStorage(storage?: StorageLike): StorageLike | null {
  if (storage) return storage;
  return typeof window === 'undefined' ? null : window.localStorage;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function normalizeLoraStrengths(value: unknown): PresetAssetLoraStrengths {
  if (!isRecord(value)) return {};
  const result: PresetAssetLoraStrengths = {};
  for (const [rawName, rawStrengths] of Object.entries(value)) {
    const name = rawName.trim();
    if (!name || !isRecord(rawStrengths)) continue;
    const strengths: PresetAssetLoraStrengths[string] = {};
    if (isFiniteNumber(rawStrengths.model)) {
      strengths.model = rawStrengths.model;
    }
    if (isFiniteNumber(rawStrengths.clip)) {
      strengths.clip = rawStrengths.clip;
    }
    if (Object.keys(strengths).length > 0) {
      result[name] = strengths;
    }
  }
  return result;
}

export function normalizePresetAssetSettings(
  value: unknown,
): PresetAssetSettings | null {
  if (!isRecord(value)) return null;

  const {
    version,
    model,
    loras,
    lora_strengths,
    lora_strength_model,
    lora_strength_clip,
    steps,
    cfg,
    seed_strategy,
    seed,
    crop_mode,
    focus_x,
    focus_y,
    zoom,
    candidate_count,
    style_positive,
    style_negative,
    user_positive,
    user_negative,
  } = value;

  if (
    !isFiniteNumber(version) ||
    typeof model !== 'string' ||
    !isStringArray(loras) ||
    !isFiniteNumber(lora_strength_model) ||
    !isFiniteNumber(lora_strength_clip) ||
    !isFiniteNumber(steps) ||
    !isFiniteNumber(cfg) ||
    !SEED_STRATEGIES.has(seed_strategy as PresetAssetSeedStrategy) ||
    (seed !== null && !isFiniteNumber(seed)) ||
    !CROP_MODES.has(crop_mode as PresetAssetCropMode) ||
    !isFiniteNumber(focus_x) ||
    !isFiniteNumber(focus_y) ||
    !isFiniteNumber(zoom) ||
    !isFiniteNumber(candidate_count) ||
    typeof style_positive !== 'string' ||
    typeof style_negative !== 'string' ||
    typeof user_positive !== 'string' ||
    typeof user_negative !== 'string'
  ) {
    return null;
  }

  return {
    version,
    model,
    loras: [...new Set(loras.map((item) => item.trim()).filter(Boolean))],
    lora_strengths: normalizeLoraStrengths(lora_strengths),
    lora_strength_model,
    lora_strength_clip,
    steps,
    cfg,
    seed_strategy: seed_strategy as PresetAssetSeedStrategy,
    seed,
    crop_mode: crop_mode as PresetAssetCropMode,
    focus_x,
    focus_y,
    zoom,
    candidate_count,
    style_positive,
    style_negative,
    user_positive,
    user_negative,
  };
}

function clonePresetAssetSettings(
  settings: PresetAssetSettings,
): PresetAssetSettings {
  return {
    ...settings,
    loras: [...settings.loras],
    lora_strengths: Object.fromEntries(
      Object.entries(settings.lora_strengths).map(([name, values]) => [
        name,
        { ...values },
      ]),
    ),
  };
}

export function mergePresetAssetSettingsWithDefaults(
  defaults: PresetAssetSettings,
  remembered: PresetAssetSettings,
): PresetAssetSettings {
  return clonePresetAssetSettings({
    ...defaults,
    ...remembered,
    loras: [...remembered.loras],
    lora_strengths: { ...remembered.lora_strengths },
    model: remembered.model || defaults.model,
  });
}

function migrateLegacyDraft(settings: PresetAssetSettings): DraftDocument {
  const drafts = Object.fromEntries(
    PRESET_ASSET_KINDS.map((presetType) => [
      presetType,
      normalizePresetAssetSettings(settings),
    ]),
  ) as DraftMap;
  return { v: STORAGE_VERSION, drafts };
}

function readDraftDocument(storage?: StorageLike): DraftDocument {
  const target = resolveStorage(storage);
  if (!target) return { v: STORAGE_VERSION, drafts: {} };
  try {
    const raw = target.getItem(PRESET_ASSET_SETTINGS_STORAGE_KEY);
    if (!raw) return { v: STORAGE_VERSION, drafts: {} };
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) return { v: STORAGE_VERSION, drafts: {} };

    if (parsed.v === 1) {
      const legacy = normalizePresetAssetSettings(parsed.settings);
      if (!legacy) return { v: STORAGE_VERSION, drafts: {} };
      const migrated = migrateLegacyDraft(legacy);
      target.setItem(
        PRESET_ASSET_SETTINGS_STORAGE_KEY,
        JSON.stringify(migrated),
      );
      return migrated;
    }

    if (parsed.v !== STORAGE_VERSION || !isRecord(parsed.drafts)) {
      return { v: STORAGE_VERSION, drafts: {} };
    }
    const drafts: DraftMap = {};
    for (const presetType of PRESET_ASSET_KINDS) {
      const normalized = normalizePresetAssetSettings(parsed.drafts[presetType]);
      if (normalized) drafts[presetType] = normalized;
    }
    return { v: STORAGE_VERSION, drafts };
  } catch {
    return { v: STORAGE_VERSION, drafts: {} };
  }
}

function writeDraftDocument(
  document: DraftDocument,
  storage?: StorageLike,
): void {
  const target = resolveStorage(storage);
  if (!target) return;
  try {
    target.setItem(PRESET_ASSET_SETTINGS_STORAGE_KEY, JSON.stringify(document));
  } catch {
    // Persistence failure must not block candidate generation.
  }
}

export function loadPresetAssetSettingsDraft(
  presetType: PresetAssetKind,
  storage?: StorageLike,
): PresetAssetSettings | null {
  return readDraftDocument(storage).drafts[presetType] || null;
}

export function loadPresetAssetSettingsWithDefaults(
  presetType: PresetAssetKind,
  defaults: PresetAssetSettings,
  storage?: StorageLike,
): PresetAssetSettings {
  const draft = loadPresetAssetSettingsDraft(presetType, storage);
  return draft
    ? mergePresetAssetSettingsWithDefaults(defaults, draft)
    : clonePresetAssetSettings(defaults);
}

export function savePresetAssetSettingsDraft(
  settings: PresetAssetSettings,
  presetType: PresetAssetKind,
  storage?: StorageLike,
): void {
  const normalized = normalizePresetAssetSettings(settings);
  if (!normalized) return;
  const document = readDraftDocument(storage);
  document.drafts[presetType] = normalized;
  writeDraftDocument(document, storage);
}

export function clearPresetAssetSettingsDraft(
  presetType: PresetAssetKind,
  storage?: StorageLike,
): void {
  const document = readDraftDocument(storage);
  delete document.drafts[presetType];
  writeDraftDocument(document, storage);
}

function readSchemeDocument(storage?: StorageLike): SchemeDocument {
  const target = resolveStorage(storage);
  if (!target) return { v: SCHEME_STORAGE_VERSION, schemes: [] };
  try {
    const raw = target.getItem(PRESET_ASSET_SETTINGS_SCHEMES_STORAGE_KEY);
    if (!raw) return { v: SCHEME_STORAGE_VERSION, schemes: [] };
    const parsed = JSON.parse(raw) as unknown;
    if (
      !isRecord(parsed) ||
      parsed.v !== SCHEME_STORAGE_VERSION ||
      !Array.isArray(parsed.schemes)
    ) {
      return { v: SCHEME_STORAGE_VERSION, schemes: [] };
    }
    const schemes: PresetAssetSettingsScheme[] = [];
    for (const item of parsed.schemes) {
      if (
        !isRecord(item) ||
        typeof item.id !== 'string' ||
        typeof item.name !== 'string' ||
        !PRESET_ASSET_KINDS.includes(item.preset_type as PresetAssetKind) ||
        typeof item.updated_at !== 'string'
      ) {
        continue;
      }
      const settings = normalizePresetAssetSettings(item.settings);
      if (!settings || !item.id.trim() || !item.name.trim()) continue;
      schemes.push({
        id: item.id,
        name: item.name.trim(),
        preset_type: item.preset_type as PresetAssetKind,
        settings,
        updated_at: item.updated_at,
      });
    }
    return { v: SCHEME_STORAGE_VERSION, schemes };
  } catch {
    return { v: SCHEME_STORAGE_VERSION, schemes: [] };
  }
}

function writeSchemeDocument(
  document: SchemeDocument,
  storage?: StorageLike,
): void {
  const target = resolveStorage(storage);
  if (!target) return;
  try {
    target.setItem(
      PRESET_ASSET_SETTINGS_SCHEMES_STORAGE_KEY,
      JSON.stringify(document),
    );
  } catch {
    // Scheme persistence failure must not block the active editor.
  }
}

function makeSchemeId(): string {
  if (
    typeof globalThis.crypto !== 'undefined' &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID();
  }
  return `scheme-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function loadPresetAssetSettingsSchemes(
  presetType: PresetAssetKind,
  storage?: StorageLike,
): PresetAssetSettingsScheme[] {
  return readSchemeDocument(storage).schemes
    .filter((scheme) => scheme.preset_type === presetType)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

export function savePresetAssetSettingsScheme(
  presetType: PresetAssetKind,
  name: string,
  settings: PresetAssetSettings,
  storage?: StorageLike,
): PresetAssetSettingsScheme | null {
  const normalized = normalizePresetAssetSettings(settings);
  const normalizedName = name.trim();
  if (!normalized || !normalizedName) return null;
  const document = readSchemeDocument(storage);
  const existing = document.schemes.find(
    (scheme) =>
      scheme.preset_type === presetType &&
      scheme.name.toLocaleLowerCase() === normalizedName.toLocaleLowerCase(),
  );
  const scheme: PresetAssetSettingsScheme = {
    id: existing?.id || makeSchemeId(),
    name: normalizedName,
    preset_type: presetType,
    settings: normalized,
    updated_at: new Date().toISOString(),
  };
  document.schemes = [
    scheme,
    ...document.schemes.filter((item) => item.id !== scheme.id),
  ];
  writeSchemeDocument(document, storage);
  return scheme;
}

export function deletePresetAssetSettingsScheme(
  schemeId: string,
  storage?: StorageLike,
): void {
  const document = readSchemeDocument(storage);
  document.schemes = document.schemes.filter((item) => item.id !== schemeId);
  writeSchemeDocument(document, storage);
}
