import type {
  ExpressionPreset,
  PresetScope,
  PromptBodyBuild,
  PromptBodyProfile,
  PromptBlock,
  PromptCharacter,
  PromptDocumentV1,
  PromptHeightFrame,
  PromptPresetRef,
} from './api';

export const PROMPT_DOCUMENT_VERSION = 1;
export const CHARACTER_BLOCK_KINDS = [
  'appearance',
  'clothing',
  'body_modifications',
  'pose_or_action',
  'expression',
  'state',
] as const;
export const GLOBAL_BLOCK_KINDS = [
  'quality',
  'style',
  'scene',
  'camera',
  'lighting',
  'constraints',
] as const;
export const NEGATIVE_BLOCK_KINDS = [
  'quality',
  'anatomy',
  'composition',
  'style',
  'content',
  'custom',
] as const;

const DEFAULT_ROLE_LABELS: Record<string, string> = {
  girlA: '女A',
  girlB: '女B',
  boyA: '男A',
  boyB: '男B',
};

export const HEIGHT_FRAME_OPTIONS: ReadonlyArray<{
  value: PromptHeightFrame;
  label: string;
}> = [
  { value: 'none', label: '不设置' },
  { value: 'petite_adult', label: '娇小成年' },
  { value: 'standard_height', label: '中等身高' },
  { value: 'tall', label: '高挑' },
];

export const BODY_BUILD_OPTIONS: ReadonlyArray<{
  value: PromptBodyBuild;
  label: string;
}> = [
  { value: 'none', label: '不设置' },
  { value: 'standard', label: '标准' },
  { value: 'slim', label: '纤细' },
  { value: 'athletic', label: '运动紧致' },
  { value: 'curvy', label: '曲线丰满' },
  { value: 'plump', label: '丰腴' },
];

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function normalizeProfileValue<T extends string>(
  value: unknown,
  options: ReadonlyArray<{ value: T; label: string }>,
  fallback: T,
): T {
  const candidate = typeof value === 'string' ? value : '';
  return options.some((option) => option.value === candidate) ? (candidate as T) : fallback;
}

export function createBodyProfile(
  overrides: Partial<PromptBodyProfile> = {},
): PromptBodyProfile {
  return {
    height_frame: normalizeProfileValue(overrides.height_frame, HEIGHT_FRAME_OPTIONS, 'none'),
    body_build: normalizeProfileValue(overrides.body_build, BODY_BUILD_OPTIONS, 'none'),
  };
}

export function normalizeBodyProfile(raw: unknown): PromptBodyProfile {
  const data = raw && typeof raw === 'object' ? (raw as Partial<PromptBodyProfile>) : {};
  return createBodyProfile(data);
}

export function isBodyProfileEmpty(profile: PromptBodyProfile | null | undefined): boolean {
  const normalized = normalizeBodyProfile(profile);
  return normalized.height_frame === 'none' && normalized.body_build === 'none';
}

export function createPromptBlock(kind: string, tags: string[] = [], presetRefs: PromptPresetRef[] = []): PromptBlock {
  return {
    id: `${kind}-block`,
    kind,
    tags: [...tags],
    preset_refs: [...presetRefs],
    preset_snapshot: {},
    locked: false,
    enabled: true,
    source: 'manual',
    order: 0,
  };
}

function normalizeBlock(raw: unknown, kind: string): PromptBlock {
  const data = raw && typeof raw === 'object' ? (raw as Partial<PromptBlock>) : {};
  const refs: unknown[] = Array.isArray(data.preset_refs) ? data.preset_refs : [];
  return {
    id: typeof data.id === 'string' && data.id ? data.id : `${kind}-block`,
    kind: typeof data.kind === 'string' && data.kind ? data.kind : kind,
    tags: Array.isArray(data.tags) ? data.tags.filter((tag): tag is string => typeof tag === 'string') : [],
    preset_refs: refs
      .map((rawRef) => {
        const ref = rawRef && typeof rawRef === 'object' ? (rawRef as Partial<PromptPresetRef>) : {};
        return {
          preset_id: String(ref.preset_id || '').trim(),
          version: Math.max(1, Number(ref.version || 1)),
          ...(ref.scope ? { scope: ref.scope } : {}),
        };
      })
      .filter((ref) => Boolean(ref.preset_id)),
    preset_snapshot:
      data.preset_snapshot && typeof data.preset_snapshot === 'object' ? clone(data.preset_snapshot) : {},
    locked: data.locked === true,
    enabled: data.enabled !== false,
    source: typeof data.source === 'string' && data.source ? data.source : 'manual',
    order: Number(data.order || 0),
  };
}

export function createPromptCharacter(index = 0, overrides: Partial<PromptCharacter> = {}): PromptCharacter {
  const gender = overrides.gender || '女';
  const bodyProfile = normalizeBodyProfile(overrides);
  const roleId =
    overrides.role_id ||
    (gender === '男'
      ? index === 0
        ? 'boyA'
        : index === 1
          ? 'boyB'
          : `boy${index - 1}`
      : index === 0
        ? 'girlA'
        : index === 1
          ? 'girlB'
          : `girl${index - 1}`);
  const displayName = overrides.display_name || DEFAULT_ROLE_LABELS[roleId] || `角色${index + 1}`;
  const base = {
    id: overrides.id || `character-${index + 1}`,
    role_id: roleId,
    display_name: displayName,
    gender,
    ...bodyProfile,
    order: overrides.order ?? index,
    enabled: overrides.enabled !== false,
  };
  return CHARACTER_BLOCK_KINDS.reduce(
    (character, kind) => ({
      ...character,
      [kind]: normalizeBlock((overrides as Record<string, unknown>)[kind], kind),
    }),
    base as PromptCharacter,
  );
}

function createBaseDocument(mode: 'structured' | 'legacy'): PromptDocumentV1 {
  return {
    version: PROMPT_DOCUMENT_VERSION,
    mode,
    global: {
      quality: createPromptBlock('quality'),
      style: createPromptBlock('style'),
      scene: createPromptBlock('scene'),
      camera: createPromptBlock('camera'),
      lighting: createPromptBlock('lighting'),
      constraints: createPromptBlock('constraints'),
    },
    characters: [createPromptCharacter(0)],
    interaction: {
      action_tags: [],
      contact_tags: [],
      relationship_tags: [],
      composition_constraints: [],
    },
    custom: { global_tags: [], user_notes: '' },
    negative: {
      quality: createPromptBlock('quality'),
      anatomy: createPromptBlock('anatomy'),
      composition: createPromptBlock('composition'),
      style: createPromptBlock('style'),
      content: createPromptBlock('content'),
      custom: createPromptBlock('custom'),
    },
    raw_override: { prompt: '', negative_prompt: '' },
  };
}

export function createEmptyStructuredDocument(): PromptDocumentV1 {
  return createBaseDocument('structured');
}

export function createLegacyDocument(prompt = '', negativePrompt = ''): PromptDocumentV1 {
  const document = createBaseDocument('legacy');
  document.raw_override = { prompt, negative_prompt: negativePrompt };
  return document;
}

export function createStructuredDocumentFromLegacy(
  prompt: string,
  negativePrompt = '',
  bodyProfile: PromptBodyProfile = createBodyProfile(),
): PromptDocumentV1 {
  const document = createEmptyStructuredDocument();
  document.custom.global_tags = prompt
    .split(/[,\n]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
  document.raw_override = { prompt, negative_prompt: negativePrompt };
  if (document.characters[0]) {
    Object.assign(document.characters[0], normalizeBodyProfile(bodyProfile));
  }
  return document;
}

export function normalizePromptDocument(raw: unknown): PromptDocumentV1 {
  const data = raw && typeof raw === 'object' ? (raw as Partial<PromptDocumentV1>) : {};
  const mode = data.mode === 'legacy' ? 'legacy' : 'structured';
  const fallback = createBaseDocument(mode);
  const globalRaw: Partial<PromptDocumentV1['global']> =
    data.global && typeof data.global === 'object' ? data.global : {};
  const negativeRaw: Partial<PromptDocumentV1['negative']> =
    data.negative && typeof data.negative === 'object' ? data.negative : {};
  const interactionRaw: Partial<PromptDocumentV1['interaction']> =
    data.interaction && typeof data.interaction === 'object' ? data.interaction : {};
  const customRaw: Partial<PromptDocumentV1['custom']> =
    data.custom && typeof data.custom === 'object' ? data.custom : {};
  const rawOverride: Partial<PromptDocumentV1['raw_override']> =
    data.raw_override && typeof data.raw_override === 'object' ? data.raw_override : {};
  const charactersRaw = Array.isArray(data.characters) ? data.characters : [];
  const characters = charactersRaw.length
    ? charactersRaw.map((character, index) => createPromptCharacter(index, character))
    : fallback.characters;

  return {
    version: PROMPT_DOCUMENT_VERSION,
    mode,
    global: {
      quality: normalizeBlock(globalRaw.quality, 'quality'),
      style: normalizeBlock(globalRaw.style, 'style'),
      scene: normalizeBlock(globalRaw.scene, 'scene'),
      camera: normalizeBlock(globalRaw.camera, 'camera'),
      lighting: normalizeBlock(globalRaw.lighting, 'lighting'),
      constraints: normalizeBlock(globalRaw.constraints, 'constraints'),
    },
    characters: characters.map((character, index) => ({ ...character, order: index })),
    interaction: {
      ...(interactionRaw.pose_preset?.preset_id
        ? { pose_preset: interactionRaw.pose_preset }
        : {}),
      action_tags: Array.isArray(interactionRaw.action_tags)
        ? interactionRaw.action_tags.filter((item): item is string => typeof item === 'string')
        : [],
      contact_tags: Array.isArray(interactionRaw.contact_tags)
        ? interactionRaw.contact_tags.filter((item): item is string => typeof item === 'string')
        : [],
      relationship_tags: Array.isArray(interactionRaw.relationship_tags)
        ? interactionRaw.relationship_tags.filter((item): item is string => typeof item === 'string')
        : [],
      composition_constraints: Array.isArray(interactionRaw.composition_constraints)
        ? interactionRaw.composition_constraints.filter((item): item is string => typeof item === 'string')
        : [],
    },
    custom: {
      global_tags: Array.isArray(customRaw.global_tags)
        ? customRaw.global_tags.filter((item): item is string => typeof item === 'string')
        : [],
      user_notes: typeof customRaw.user_notes === 'string' ? customRaw.user_notes : '',
    },
    negative: {
      quality: normalizeBlock(negativeRaw.quality, 'quality'),
      anatomy: normalizeBlock(negativeRaw.anatomy, 'anatomy'),
      composition: normalizeBlock(negativeRaw.composition, 'composition'),
      style: normalizeBlock(negativeRaw.style, 'style'),
      content: normalizeBlock(negativeRaw.content, 'content'),
      custom: normalizeBlock(negativeRaw.custom, 'custom'),
    },
    raw_override: {
      prompt: typeof rawOverride.prompt === 'string' ? rawOverride.prompt : '',
      negative_prompt: typeof rawOverride.negative_prompt === 'string' ? rawOverride.negative_prompt : '',
    },
  };
}

export function clonePromptDocument(document: PromptDocumentV1): PromptDocumentV1 {
  return normalizePromptDocument(clone(document));
}

export function mergeTags(existing: string[], additions: string[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const item of [...existing, ...additions]) {
    const tag = String(item || '').trim();
    const key = tag.toLowerCase();
    if (tag && !seen.has(key)) {
      seen.add(key);
      result.push(tag);
    }
  }
  return result;
}

export function isPromptDocumentEmpty(document: PromptDocumentV1 | null | undefined): boolean {
  if (!document) return true;
  const normalized = normalizePromptDocument(document);
  if (normalized.raw_override.prompt.trim()) return false;
  if (normalized.interaction.pose_preset?.preset_id) return false;
  const hasBlock = (block: PromptBlock) => block.tags.length > 0 || block.preset_refs.length > 0;
  if (Object.values(normalized.global).some(hasBlock)) return false;
  if (Object.values(normalized.negative).some(hasBlock)) return false;
  if (normalized.characters.some((character) => CHARACTER_BLOCK_KINDS.some((kind) => hasBlock(character[kind])))) return false;
  if (
    normalized.characters.some(
      (character) => character.height_frame !== 'none' || character.body_build !== 'none',
    )
  ) {
    return false;
  }
  if (
    normalized.interaction.action_tags.length ||
    normalized.interaction.contact_tags.length ||
    normalized.interaction.relationship_tags.length ||
    normalized.interaction.composition_constraints.length
  ) {
    return false;
  }
  return normalized.custom.global_tags.length === 0 && !normalized.custom.user_notes.trim();
}

export function resolveCharacterTargets(
  document: PromptDocumentV1,
  activeCharacterId: string,
  scope: PresetScope | 'current' | 'all',
): string[] {
  if (scope === 'current') return activeCharacterId ? [activeCharacterId] : document.characters.slice(0, 1).map((item) => item.id);
  if (scope === 'all') return document.characters.map((item) => item.id);
  const matched = document.characters.filter((item) => item.role_id === scope).map((item) => item.id);
  return matched.length ? matched : activeCharacterId ? [activeCharacterId] : document.characters.slice(0, 1).map((item) => item.id);
}

export function addPresetRefToBlock(
  block: PromptBlock,
  presetId: string,
  version = 1,
  scope?: PresetScope,
): PromptBlock {
  return {
    ...block,
    preset_refs: [
      ...block.preset_refs.filter((item) => item.preset_id !== presetId),
      { preset_id: presetId, version, ...(scope ? { scope } : {}) },
    ],
  };
}

export function applyExpressionPresetToCharacter(
  document: PromptDocumentV1,
  characterId: string,
  preset: Pick<ExpressionPreset, 'id' | 'label' | 'category' | 'tags'>,
  scope?: PresetScope,
): PromptDocumentV1 {
  return updateCharacterBlock(document, characterId, 'expression', (block) => ({
    ...addPresetRefToBlock(
      {
        ...block,
        tags: mergeTags(block.tags, preset.tags),
        source: 'expression_preset',
      },
      preset.id,
      1,
      scope,
    ),
    preset_snapshot: {
      name: preset.label,
      category: preset.category,
      expression_tags: [...preset.tags],
    },
  }));
}

export function updateCharacterBlock(
  document: PromptDocumentV1,
  characterId: string,
  kind: (typeof CHARACTER_BLOCK_KINDS)[number],
  update: (block: PromptBlock) => PromptBlock,
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.characters = next.characters.map((character) =>
    character.id === characterId ? { ...character, [kind]: update(character[kind]) } : character,
  );
  return next;
}

export function updateGlobalBlock(
  document: PromptDocumentV1,
  kind: (typeof GLOBAL_BLOCK_KINDS)[number],
  update: (block: PromptBlock) => PromptBlock,
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.global[kind] = update(next.global[kind]);
  return next;
}

export function updateNegativeBlock(
  document: PromptDocumentV1,
  kind: (typeof NEGATIVE_BLOCK_KINDS)[number],
  update: (block: PromptBlock) => PromptBlock,
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.negative[kind] = update(next.negative[kind]);
  return next;
}

export function updateInteraction(
  document: PromptDocumentV1,
  update: (interaction: PromptDocumentV1['interaction']) => PromptDocumentV1['interaction'],
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.interaction = update(next.interaction);
  return next;
}

export function updateCustom(
  document: PromptDocumentV1,
  update: (custom: PromptDocumentV1['custom']) => PromptDocumentV1['custom'],
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.custom = update(next.custom);
  return next;
}

export function updateRawOverride(
  document: PromptDocumentV1,
  update: (rawOverride: PromptDocumentV1['raw_override']) => PromptDocumentV1['raw_override'],
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.raw_override = update(next.raw_override);
  return next;
}

export function updateCharacter(
  document: PromptDocumentV1,
  characterId: string,
  update: (character: PromptCharacter) => PromptCharacter,
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.characters = next.characters.map((character) =>
    character.id === characterId ? update(character) : character,
  );
  return next;
}

export function addCharacter(document: PromptDocumentV1, gender = '女'): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.characters = [...next.characters, createPromptCharacter(next.characters.length, { gender })];
  return next;
}

export function removeCharacter(document: PromptDocumentV1, characterId: string): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  if (next.characters.length <= 1) return next;
  next.characters = next.characters
    .filter((character) => character.id !== characterId)
    .map((character, index) => ({ ...character, order: index }));
  return next;
}

export function moveCharacter(
  document: PromptDocumentV1,
  characterId: string,
  direction: -1 | 1,
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  const index = next.characters.findIndex((character) => character.id === characterId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= next.characters.length) return next;
  [next.characters[index], next.characters[target]] = [next.characters[target], next.characters[index]];
  next.characters = next.characters.map((character, order) => ({ ...character, order }));
  return next;
}

export function applyAppearancePresetToCharacter(
  document: PromptDocumentV1,
  characterId: string,
  result: {
    preset_ref?: PromptPresetRef;
    snapshot?: Record<string, unknown>;
    appearance: string[];
    clothing: string[];
    expression: string[];
  },
): PromptDocumentV1 {
  let next = clonePromptDocument(document);
  const fields: Array<[keyof Pick<PromptCharacter, 'appearance' | 'clothing' | 'expression'>, string[]]> = [
    ['appearance', result.appearance],
    ['clothing', result.clothing],
    ['expression', result.expression],
  ];
  for (const [kind, tags] of fields) {
    next = updateCharacterBlock(next, characterId, kind, (block) => ({
      ...block,
      tags: mergeTags(block.tags, tags),
      preset_refs: result.preset_ref
        ? [
            ...block.preset_refs.filter((ref) => ref.preset_id !== result.preset_ref?.preset_id),
            { ...result.preset_ref },
          ]
        : block.preset_refs,
      preset_snapshot: result.snapshot ? { ...result.snapshot } : block.preset_snapshot,
      source: 'appearance_preset',
    }));
  }
  return next;
}
