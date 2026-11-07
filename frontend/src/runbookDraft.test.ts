import { describe, expect, it } from 'vitest';
import {
  buildRunbookCardChoices,
  runbookTeamMemberName,
} from './runbookDraft';

const servants = [
  { name: '刑部姬', class_name: 'Archer' },
  { name: '刑部姬', class_name: 'Assassin' },
  { name: '“山中老人”', class_name: 'Assassin' },
];

describe('runbookTeamMemberName', () => {
  it('adds the class suffix for ambiguous servant names', () => {
    expect(runbookTeamMemberName('刑部姬|Assassin', servants)).toBe(
      '刑部姬(Assassin)',
    );
  });

  it('keeps unique names unchanged', () => {
    expect(runbookTeamMemberName('“山中老人”|Assassin', servants)).toBe(
      '“山中老人”',
    );
  });

  it('builds an ordered explicit owner and fallback chain', () => {
    const team = [
      '刑部姬|Assassin',
      '“山中老人”|Assassin',
      '',
    ];
    expect(
      buildRunbookCardChoices(
        [
          { ownerSlot: 2, card: 'buster' },
          { ownerSlot: 2, card: 'arts' },
          { ownerSlot: 1, card: 'any' },
          { ownerSlot: 0, card: 'any' },
        ],
        team,
        servants,
      ),
    ).toEqual([
      { owner: '“山中老人”', card: 'buster', position: 'leftmost' },
      { owner: '“山中老人”', card: 'arts', position: 'leftmost' },
      { owner: '刑部姬(Assassin)', card: 'any', position: 'leftmost' },
      { card: 'any', position: 'leftmost' },
    ]);
  });

  it('rejects an owner preference whose team slot is empty', () => {
    expect(() =>
      buildRunbookCardChoices(
        [{ ownerSlot: 3, card: 'buster' }],
        ['刑部姬|Assassin', '', ''],
        servants,
      ),
    ).toThrow('卡主站位 3 为空');
  });
});
