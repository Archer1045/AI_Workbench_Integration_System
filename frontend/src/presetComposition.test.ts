import { describe, expect, it } from 'vitest';
import {
  formatScenePresetInsert,
  normalizeSelectionsForSinglePerson,
  poseCoreTags,
  posePromptForInsert,
  scenePromptForPeoplePolicy,
  stripPeopleExclusions,
} from './presetComposition';

describe('normalizeSelectionsForSinglePerson', () => {
  it('resets scoped selections to all characters', () => {
    const items = [
      { id: 'a', scope: 'girlA' as const },
      { id: 'b', scope: 'boyA' as const },
    ];
    expect(normalizeSelectionsForSinglePerson(items, 3)).toEqual([
      { id: 'a', scope: 'all' },
      { id: 'b', scope: 'all' },
    ]);
  });

  it('trims selections to the single-person limit', () => {
    const items = [
      { id: 'a', scope: 'all' as const },
      { id: 'b', scope: 'girlA' as const },
      { id: 'c', scope: 'girlB' as const },
      { id: 'd', scope: 'all' as const },
    ];
    expect(normalizeSelectionsForSinglePerson(items, 3)).toEqual([
      { id: 'a', scope: 'all' },
      { id: 'b', scope: 'all' },
      { id: 'c', scope: 'all' },
    ]);
  });

  it('keeps an already normalized list unchanged', () => {
    const items = [{ id: 'a', scope: 'all' as const }];
    expect(normalizeSelectionsForSinglePerson(items, 3)).toBe(items);
  });
});

describe('scene people policy', () => {
  const preset = {
    tags: ['bathroom'],
    draw_prompt: 'a home bathroom, no people and no shower curtain',
    empty_scene_prompt: 'a home bathroom, no people and no shower curtain',
    occupied_scene_prompt: 'a home bathroom and no shower curtain',
  };

  it('uses the occupied prompt by default and preserves the empty variant', () => {
    expect(scenePromptForPeoplePolicy(preset, 'occupied')).toBe(
      'a home bathroom and no shower curtain',
    );
    expect(scenePromptForPeoplePolicy(preset, 'empty')).toBe(
      'a home bathroom, no people and no shower curtain',
    );
  });

  it('provides a safe fallback for older API payloads', () => {
    expect(
      stripPeopleExclusions(
        'a quiet library without people and no visible posters',
      ),
    ).toBe('a quiet library and no visible posters');
    expect(
      scenePromptForPeoplePolicy(
        { draw_prompt: 'a quiet library, no people' },
        'occupied',
      ),
    ).toBe('a quiet library');
  });

  it('formats the selected scene policy with the target scope', () => {
    expect(formatScenePresetInsert(preset, 'all', 'occupied')).toBe(
      'a home bathroom and no shower curtain',
    );
    expect(formatScenePresetInsert(preset, 'girlA', 'empty')).toBe(
      'for the first girl: a home bathroom, no people and no shower curtain',
    );
  });
});

describe('pose people constraint', () => {
  it('prefixes a duo pose with deterministic count and body separation', () => {
    const preset = {
      tags: ['face to face', '2 people'],
      draw_prompt: 'face-to-face seated pose',
      people: '双人',
      people_count: 2,
      people_prompt: 'exactly 2 people, two separate bodies',
      role_slots: ['角色A', '角色B'],
    };
    expect(posePromptForInsert(preset)).toBe(
      'exactly 2 people, two separate bodies, face to face',
    );
    expect(posePromptForInsert(preset, 'full')).toBe(
      'exactly 2 people, two separate bodies, face to face, face-to-face seated pose',
    );
  });

  it('supports a three-person pose and an older payload fallback', () => {
    expect(
      posePromptForInsert({
        tags: ['triangular formation'],
        people: '多人',
        role_slots: ['角色A', '角色B', '角色C'],
      }),
    ).toBe(
      'exactly three people, three separate bodies, triangular formation',
    );
  });

  it('does not duplicate an existing people constraint', () => {
    expect(
      posePromptForInsert({
        tags: [],
        draw_prompt: 'exactly 2 people, two separate bodies, standing close',
        people_count: 2,
        people_prompt: 'exactly 2 people, two separate bodies',
      }, 'full'),
    ).toBe('exactly 2 people, two separate bodies, standing close');
  });

  it('keeps action and consent context in the short prompt but drops boilerplate', () => {
    const preset = {
      tags: [
        'two adults',
        'same-age adult partners',
        'consensual',
        'missionary position',
        'knees bent',
        'uncensored',
      ],
      draw_prompt:
        'missionary position with bent knees; visible faces and separate bodies; no extra limbs',
      people_count: 2,
      people_prompt: 'exactly 2 people, two separate bodies',
    };

    expect(poseCoreTags(preset)).toEqual([
      'missionary position',
      'knees bent',
      'adult characters',
      'consensual',
    ]);
    const core = posePromptForInsert(preset);
    expect(core).toBe(
      'exactly 2 people, two separate bodies, missionary position, knees bent, adult characters, consensual',
    );
    expect(core).not.toContain('uncensored');
    expect(core).not.toContain('no extra limbs');
    expect(posePromptForInsert(preset, 'full')).toContain('visible faces and separate bodies');
  });
});
