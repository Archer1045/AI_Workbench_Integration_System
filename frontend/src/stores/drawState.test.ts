import { afterEach, describe, expect, it } from 'vitest';
import {
  DRAW_STATE_KEY,
  LEGACY_DRAW_STATE_KEY,
  createNewPromptGroup,
  loadDrawState,
} from './draw';

afterEach(() => {
  localStorage.clear();
});

describe('draw state migration', () => {
  it('migrates the legacy v1 prompt format into a lossless legacy document', () => {
    localStorage.setItem(
      LEGACY_DRAW_STATE_KEY,
      JSON.stringify({
        v: 1,
        model: 'test-model.safetensors',
        groups: [{ id: 'group-1', prompt: '1girl, long hair', count: 2 }],
        negativePrompt: 'low quality',
        width: 1080,
        height: 1920,
        steps: 18,
        cfg: 1,
        loras: [],
        loraStrengthModel: 0.8,
        loraStrengthClip: 0.8,
        loraStrengths: {},
      }),
    );

    const state = loadDrawState();
    expect(state).not.toBeNull();
    expect(state?.groups).toHaveLength(1);
    expect(state?.groups[0].mode).toBe('legacy');
    expect(state?.groups[0].prompt_document?.raw_override.prompt).toBe('1girl, long hair');
    expect(state?.groups[0].prompt_document?.raw_override.negative_prompt).toBe('low quality');
    expect(state?.negativePrompt).toBe('low quality');
  });

  it('loads v2 structured documents without converting them back to legacy', () => {
    const structured = {
      version: 1,
      mode: 'structured',
      global: {},
      characters: [
        {
          id: 'hero',
          role_id: 'girlA',
          display_name: 'Hero',
          gender: '女',
          order: 0,
          enabled: true,
          appearance: { tags: ['long hair'] },
          clothing: { tags: ['red dress'] },
          body_modifications: { tags: [] },
          pose_or_action: { tags: [] },
          expression: { tags: [] },
          state: { tags: [] },
        },
      ],
      interaction: {
        action_tags: [],
        contact_tags: [],
        relationship_tags: [],
        composition_constraints: [],
      },
      custom: { global_tags: [], user_notes: '' },
      negative: {},
      raw_override: { prompt: '', negative_prompt: '' },
    };
    localStorage.setItem(
      DRAW_STATE_KEY,
      JSON.stringify({
        v: 2,
        model: 'test-model.safetensors',
        groups: [{ id: 'group-1', prompt: '', mode: 'structured', prompt_document: structured, count: 1 }],
        negativePrompt: 'low quality',
        width: 1080,
        height: 1920,
        steps: 18,
        cfg: 1,
        loras: [],
        loraStrengthModel: 0.8,
        loraStrengthClip: 0.8,
        loraStrengths: {},
      }),
    );

    const state = loadDrawState();
    expect(state?.groups[0].mode).toBe('structured');
    expect(state?.groups[0].prompt_document?.characters[0].appearance.tags).toEqual(['long hair']);
  });

  it('creates new prompt groups in the compact legacy text mode', () => {
    const group = createNewPromptGroup();
    expect(group.mode).toBe('legacy');
    expect(group.prompt_document?.mode).toBe('legacy');
  });

  it('loads independent body profile state in a legacy text group', () => {
    localStorage.setItem(
      DRAW_STATE_KEY,
      JSON.stringify({
        v: 2,
        model: 'test-model.safetensors',
        groups: [
          {
            id: 'group-1',
            prompt: '1girl, city',
            mode: 'legacy',
            body_profile: { height_frame: 'tall', body_build: 'slim' },
            prompt_document: null,
            count: 1,
          },
        ],
        negativePrompt: 'low quality',
        width: 1080,
        height: 1920,
        steps: 18,
        cfg: 1,
        loras: [],
        loraStrengthModel: 0.8,
        loraStrengthClip: 0.8,
        loraStrengths: {},
      }),
    );

    const state = loadDrawState();
    expect(state?.groups[0].mode).toBe('legacy');
    expect(state?.groups[0].body_profile).toEqual({
      height_frame: 'tall',
      body_build: 'slim',
    });
  });

  it('ignores malformed or wrong-version saved state', () => {
    localStorage.setItem(DRAW_STATE_KEY, JSON.stringify({ v: 1, groups: [] }));
    expect(loadDrawState()).toBeNull();
  });
});
