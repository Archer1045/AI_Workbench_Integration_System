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

const EXPRESSION_INTENSITY_VALUES: Record<string, number> = {
  轻: 0.4,
  中: 0.7,
  强: 1,
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

function normalizeStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function normalizeIntensity(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0.7;
  return Math.min(1, Math.max(0, numeric));
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

function applyBlockExtensions(
  block: PromptBlock,
  kind: string,
  data: Partial<PromptBlock> = {},
): PromptBlock {
  if (kind === 'expression') {
    return {
      ...block,
      gaze: normalizeStringArray(data.gaze),
      face_details: normalizeStringArray(data.face_details),
      intensity: normalizeIntensity(data.intensity),
    };
  }
  if (kind === 'clothing') {
    return {
      ...block,
      clothing_state: normalizeStringArray(data.clothing_state),
      footwear: normalizeBlock(data.footwear, 'footwear'),
    };
  }
  if (kind === 'camera') {
    return {
      ...block,
      framing: normalizeStringArray(data.framing),
      angle: normalizeStringArray(data.angle),
      focus: normalizeStringArray(data.focus),
    };
  }
  if (kind === 'scene') {
    return {
      ...block,
      time: normalizeStringArray(data.time),
      weather: normalizeStringArray(data.weather),
      foreground: normalizeStringArray(data.foreground),
      background: normalizeStringArray(data.background),
    };
  }
  if (kind === 'lighting') {
    return {
      ...block,
      palette: normalizeStringArray(data.palette),
      mood: normalizeStringArray(data.mood),
    };
  }
  return block;
}

export function createPromptBlock(kind: string, tags: string[] = [], presetRefs: PromptPresetRef[] = []): PromptBlock {
  return applyBlockExtensions({
    id: `${kind}-block`,
    kind,
    tags: [...tags],
    preset_refs: [...presetRefs],
    preset_snapshot: {},
    locked: false,
    enabled: true,
    source: 'manual',
    order: 0,
  }, kind);
}

function normalizeBlock(raw: unknown, kind: string): PromptBlock {
  const data = raw && typeof raw === 'object' ? (raw as Partial<PromptBlock>) : {};
  const refs: unknown[] = Array.isArray(data.preset_refs) ? data.preset_refs : [];
  return applyBlockExtensions({
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
  }, kind, data);
}

function normalizeProps(raw: unknown): PromptDocumentV1['props'] {
  const data = raw && typeof raw === 'object'
    ? (raw as Partial<PromptDocumentV1['props']>)
    : {};
  const charactersRaw =
    data.characters && typeof data.characters === 'object'
      ? data.characters
      : {};
  return {
    global: normalizeBlock(data.global, 'props'),
    characters: Object.fromEntries(
      Object.entries(charactersRaw).map(([roleId, block]) => [
        roleId,
        normalizeBlock(block, 'props'),
      ]),
    ),
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
    props: {
      global: createPromptBlock('props'),
      characters: {},
    },
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
  const propsRaw = normalizeProps(data.props);
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
    props: propsRaw,
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

export function mergeTags(...groups: string[][]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const item of group || []) {
      const tag = String(item || '').trim();
      const key = tag.toLowerCase();
      if (tag && !seen.has(key)) {
        seen.add(key);
        result.push(tag);
      }
    }
  }
  return result;
}

export function promptBlockDetailTags(block: PromptBlock): string[] {
  const detailFields =
    block.kind === 'expression'
      ? [block.gaze, block.face_details]
      : block.kind === 'clothing'
        ? [
            block.footwear ? promptBlockDetailTags(block.footwear) : [],
            block.clothing_state,
          ]
        : block.kind === 'camera'
          ? [block.framing, block.angle, block.focus]
          : block.kind === 'scene'
            ? [block.time, block.weather, block.foreground, block.background]
            : block.kind === 'lighting'
              ? [block.palette, block.mood]
              : [];
  return mergeTags(
    block.tags,
    ...detailFields.filter((field): field is string[] => Array.isArray(field)),
  );
}

function hasPromptBlockContent(block: PromptBlock): boolean {
  return (
    block.tags.length > 0 ||
    block.preset_refs.length > 0 ||
    promptBlockDetailTags(block).length > block.tags.length
  );
}

export function isPromptDocumentEmpty(document: PromptDocumentV1 | null | undefined): boolean {
  if (!document) return true;
  const normalized = normalizePromptDocument(document);
  if (normalized.raw_override.prompt.trim()) return false;
  if (normalized.interaction.pose_preset?.preset_id) return false;
  const hasBlock = (block: PromptBlock) => hasPromptBlockContent(block);
  if (Object.values(normalized.global).some(hasBlock)) return false;
  if (Object.values(normalized.negative).some(hasBlock)) return false;
  if (hasBlock(normalized.props.global)) return false;
  if (Object.values(normalized.props.characters).some(hasBlock)) return false;
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
  preset: Pick<ExpressionPreset, 'id' | 'label' | 'category' | 'tags'> &
    Partial<
      Pick<
        ExpressionPreset,
        | 'expression_tags'
        | 'gaze'
        | 'face_details'
        | 'intensity'
        | 'intensity_value'
      >
    >,
  scope?: PresetScope,
): PromptDocumentV1 {
  const expressionTags =
    preset.expression_tags && preset.expression_tags.length
      ? preset.expression_tags
      : preset.tags;
  return updateCharacterBlock(document, characterId, 'expression', (block) => ({
    ...addPresetRefToBlock(
      {
        ...block,
        tags: mergeTags(block.tags, expressionTags),
        gaze: mergeTags(block.gaze || [], preset.gaze || []),
        face_details: mergeTags(
          block.face_details || [],
          preset.face_details || [],
        ),
        intensity: normalizeIntensity(
          preset.intensity_value ??
            (preset.intensity
              ? EXPRESSION_INTENSITY_VALUES[preset.intensity]
              : undefined) ??
            block.intensity,
        ),
        source: 'expression_preset',
      },
      preset.id,
      1,
      scope,
    ),
    preset_snapshot: {
      name: preset.label,
      category: preset.category,
      expression_tags: [...expressionTags],
      gaze: [...(preset.gaze || [])],
      face_details: [...(preset.face_details || [])],
      intensity:
        preset.intensity_value ??
        (preset.intensity
          ? EXPRESSION_INTENSITY_VALUES[preset.intensity]
          : undefined) ??
        0.7,
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

export function updateGlobalPropsBlock(
  document: PromptDocumentV1,
  update: (block: PromptBlock) => PromptBlock,
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  next.props.global = update(next.props.global);
  return next;
}

export function updateCharacterPropsBlock(
  document: PromptDocumentV1,
  roleId: string,
  update: (block: PromptBlock) => PromptBlock,
): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  const block = next.props.characters[roleId] || createPromptBlock('props');
  next.props.characters = {
    ...next.props.characters,
    [roleId]: update(block),
  };
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
