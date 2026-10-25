import { describe, expect, it } from 'vitest';
import { runbookTeamMemberName } from './runbookDraft';

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
});
