import { afterEach, describe, expect, it } from 'vitest';
import {
  diffPromptTags,
  loadDrawPromptHistory,
  recordDrawPromptVersion,
  saveDrawPromptHistory,
  type DrawPromptHistory,
} from './drawPromptHistory';
import { createEmptyStructuredDocument } from './promptDocument';

afterEach(() => {
  localStorage.clear();
});

describe('draw prompt history', () => {
  it('records deduplicated versions in newest-first order with a limit', () => {
    let history: DrawPromptHistory = {};
    const now = new Date('2026-10-26T04:00:00+08:00');
    history = recordDrawPromptVersion(
      history,
      'group-1',
      { mode: 'legacy', prompt: 'one', document: null },
      { limit: 2, now },
    );
    history = recordDrawPromptVersion(
      history,
      'group-1',
      { mode: 'legacy', prompt: 'one', document: null },
      { limit: 2, now },
    );
    history = recordDrawPromptVersion(
      history,
      'group-1',
      { mode: 'legacy', prompt: 'two', document: null },
      { limit: 2, now },
    );
    history = recordDrawPromptVersion(
      history,
      'group-1',
      { mode: 'structured', prompt: 'three', document: createEmptyStructuredDocument() },
      { limit: 2, now },
    );

    expect(history['group-1']).toHaveLength(2);
    expect(history['group-1'][0].prompt).toBe('three');
    expect(history['group-1'][1].prompt).toBe('two');

    saveDrawPromptHistory(history);
    expect(loadDrawPromptHistory()['group-1']).toHaveLength(2);
  });

  it('computes added and removed prompt tags', () => {
    expect(diffPromptTags('one, two, same', 'two, three, same')).toEqual({
      added: ['three'],
      removed: ['one'],
    });
  });
});
