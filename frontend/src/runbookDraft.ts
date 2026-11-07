export interface RunbookAccountServant {
  name: string;
  class_name: string;
}

export interface RunbookCardPreference {
  ownerSlot: number;
  card: string;
}

export function runbookTeamMemberName(
  slotKey: string,
  servants: RunbookAccountServant[],
): string {
  const [name, className = ''] = slotKey.split('|');
  const sameNameCount = servants.filter((servant) => servant.name === name).length;
  return sameNameCount > 1 && className ? `${name}(${className})` : name;
}

export function buildRunbookCardChoices(
  preferences: RunbookCardPreference[],
  team: string[],
  servants: RunbookAccountServant[],
) {
  return preferences.map((preference) => {
    const ownerKey = preference.ownerSlot > 0
      ? team[preference.ownerSlot - 1] || ''
      : '';
    if (preference.ownerSlot > 0 && !ownerKey) {
      throw new Error(`卡主站位 ${preference.ownerSlot} 为空`);
    }
    return {
      ...(ownerKey
        ? { owner: runbookTeamMemberName(ownerKey, servants) }
        : {}),
      card: preference.card || 'any',
      position: 'leftmost',
    };
  });
}
