import type { PresetComposition, PresetScope } from './api';

const PEOPLE_EXCLUSION_PATTERN =
  /(?:,?\s*(?:and\s+)?)?(?:no\s+(?:visible\s+)?(?:people|humans?|characters?)|without\s+(?:visible\s+)?people|people[-\s]+free)\b/gi;

export type ScenePeoplePolicy = 'occupied' | 'empty';

const PEOPLE_NUMBER_WORDS: Record<number, string> = {
  1: 'one',
  2: 'two',
  3: 'three',
  4: 'four',
  5: 'five',
  6: 'six',
};
const COUNT_ONLY_TAG_PATTERN =
  /^(?:exactly\s+)?(?:\d+|one|two|three|four|five|six)\s+(?:separate\s+)?(?:people|characters?)$/i;
const POSE_QUALITY_ONLY_TAGS = new Set([
  'best quality',
  'high quality',
  'masterpiece',
  'uncensored',
  'anime rendering',
]);
const POSE_CONTEXT_TAGS = new Set([
  'consensual',
  'same-age adult partners',
  'female receiver',
  'young-looking adult male',
  'young-looking adult female',
]);

function poseContextRank(tag: string): number | null {
  const normalized = tag.trim().toLowerCase();
  if (normalized === 'consensual') return 0;
  if (/^(?:two|three|four|multiple) adults?$|^adult characters?$/.test(normalized)) return 1;
  if (normalized === 'same-age adult partners') return 2;
  if (normalized === 'female receiver') return 3;
  if (normalized === 'young-looking adult male' || normalized === 'young-looking adult female') {
    return 4;
  }
  return null;
}

function uniqueTags(values: string[]): string[] {
  const seen = new Set<string>();
  return values
    .map((value) => value.trim())
    .filter((value) => {
      const key = value.toLowerCase();
      if (!value || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

export const PRESET_SCOPE_OPTIONS: { label: string; value: PresetScope }[] = [
  { label: '全部角色', value: 'all' },
  { label: '女A', value: 'girlA' },
  { label: '女B', value: 'girlB' },
  { label: '男A', value: 'boyA' },
  { label: '男B', value: 'boyB' },
];

const SCOPE_LABELS: Record<Exclude<PresetScope, 'all'>, string> = {
  girlA: 'the first girl',
  girlB: 'the second girl',
  boyA: 'the first boy',
  boyB: 'the second boy',
};

export function formatPresetInsert(
  preset: { tags: string[]; draw_prompt?: string | null },
  scope: PresetScope,
): string {
  const tags = preset.tags.join(', ');
  const fragment = preset.draw_prompt || tags;
  if (scope === 'all') return fragment;
  return `for ${SCOPE_LABELS[scope]}: ${fragment}`;
}

export function stripPeopleExclusions(prompt: string): string {
  return prompt
    .replace(PEOPLE_EXCLUSION_PATTERN, '')
    .replace(/\s+,/g, ',')
    .replace(/,\s*,+/g, ', ')
    .replace(/\s{2,}/g, ' ')
    .replace(/^[\s,]+|[\s,]+$/g, '');
}

export function scenePromptForPeoplePolicy(
  preset: {
    draw_prompt?: string | null;
    empty_scene_prompt?: string | null;
    occupied_scene_prompt?: string | null;
  },
  policy: ScenePeoplePolicy,
): string {
  if (policy === 'empty') {
    return (
      preset.empty_scene_prompt ||
      `${stripPeopleExclusions(preset.draw_prompt || '')}, no people`
    );
  }
  return (
    preset.occupied_scene_prompt ||
    stripPeopleExclusions(preset.draw_prompt || '')
  );
}

export function formatScenePresetInsert(
  preset: {
    tags: string[];
    draw_prompt?: string | null;
    empty_scene_prompt?: string | null;
    occupied_scene_prompt?: string | null;
  },
  scope: PresetScope,
  policy: ScenePeoplePolicy,
): string {
  return formatPresetInsert(
    {
      ...preset,
      draw_prompt: scenePromptForPeoplePolicy(preset, policy),
    },
    scope,
  );
}

export function poseCoreTags(preset: {
  tags: string[];
  draw_prompt?: string | null;
}): string[] {
  const tags = uniqueTags(preset.tags).filter(
    (tag) =>
      !COUNT_ONLY_TAG_PATTERN.test(tag) &&
      !POSE_QUALITY_ONLY_TAGS.has(tag.toLowerCase()),
  );
  const signal = tags.filter(
    (tag) => poseContextRank(tag) === null && !POSE_CONTEXT_TAGS.has(tag.toLowerCase()),
  );
  const context: string[] = [];
  if (tags.some((tag) => [1, 2, 4].includes(poseContextRank(tag) ?? -1))) {
    context.push('adult characters');
  }
  if (tags.some((tag) => tag.toLowerCase() === 'consensual')) {
    context.push('consensual');
  }
  const contextLength = context.join(', ').length;
  const budget = Math.max(0, 76 - contextLength - (context.length ? 2 : 0));
  const selected: string[] = [];
  for (const tag of signal) {
    if (selected.length >= 5) break;
    const candidate = [...selected, tag].join(', ');
    if (selected.length > 0 && candidate.length > budget) break;
    selected.push(tag);
    if (candidate.length >= budget) break;
  }
  selected.push(...context);
  if (selected.length > 0) return selected;
  const fallback = (preset.draw_prompt || '').split(';', 1)[0].trim();
  return fallback ? [fallback.slice(0, 180)] : [];
}

export type PosePromptDetail = 'core' | 'full';

export function posePromptForInsert(preset: {
  tags: string[];
  draw_prompt?: string | null;
  people?: string | null;
  people_count?: number | null;
  people_prompt?: string | null;
  role_slots?: string[];
  core_tags?: string[];
}, detail: PosePromptDetail = 'core'): string {
  const fallbackCount =
    preset.people === '单人'
      ? 1
      : preset.people === '双人'
        ? 2
        : (preset.role_slots?.length ?? 0);
  const count = preset.people_count || fallbackCount;
  const number = PEOPLE_NUMBER_WORDS[count];
  const peoplePrompt =
    preset.people_prompt ||
    (number
      ? count === 1
        ? 'exactly 1 person'
        : `exactly ${number} people, ${number} separate bodies`
      : '');
  const tags =
    detail === 'core'
      ? (preset.core_tags?.length ? preset.core_tags : poseCoreTags(preset))
      : uniqueTags(preset.tags).filter((tag) => !COUNT_ONLY_TAG_PATTERN.test(tag));
  const body = [
    tags.join(', '),
    detail === 'full' ? preset.draw_prompt?.trim() || '' : '',
  ]
    .filter(Boolean)
    .join(', ');
  if (!peoplePrompt) return body;
  if (body.toLowerCase().includes(peoplePrompt.toLowerCase())) return body;
  return body ? `${peoplePrompt}, ${body}` : peoplePrompt;
}

export function isPresetHidden(
  preset: { rating?: string | null; nsfw?: boolean | null },
  restrictionEnabled: boolean,
): boolean {
  return restrictionEnabled && (preset.rating === 'R18' || Boolean(preset.nsfw));
}

export function normalizeSelectionsForSinglePerson<T extends { scope: PresetScope }>(
  items: T[],
  limit: number,
): T[] {
  const needsScopeReset = items.slice(0, limit).some((item) => item.scope !== 'all');
  if (!needsScopeReset && items.length <= limit) return items;
  return items.slice(0, limit).map((item) =>
    item.scope === 'all' ? item : { ...item, scope: 'all' },
  );
}

export function parsePresetComposition(value: unknown): PresetComposition | null {
  let raw = value;
  if (typeof raw === 'string') {
    if (!raw.trim() || raw.trim() === '{}') return null;
    try {
      raw = JSON.parse(raw) as unknown;
    } catch {
      return null;
    }
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const clothing = Array.isArray(record.clothing) ? record.clothing : [];
  const bodyModifications = Array.isArray(record.body_modifications) ? record.body_modifications : [];
  const expansions = Array.isArray(record.expansions) ? record.expansions : [];
  const toys = Array.isArray(record.toys) ? record.toys : [];
  const poseId = typeof record.pose_id === 'string' ? record.pose_id : null;
  const sceneId = typeof record.scene_id === 'string' ? record.scene_id : null;
  if (
    !poseId &&
    !sceneId &&
    clothing.length === 0 &&
    bodyModifications.length === 0 &&
    expansions.length === 0 &&
    toys.length === 0
  ) {
    return null;
  }
  return {
    pose_id: poseId,
    scene_id: sceneId,
    clothing: clothing as PresetComposition['clothing'],
    body_modifications: bodyModifications as PresetComposition['body_modifications'],
    expansions: expansions as PresetComposition['expansions'],
    toys: toys as PresetComposition['toys'],
  };
}
