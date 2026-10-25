export interface RunbookAccountServant {
  name: string;
  class_name: string;
}

export function runbookTeamMemberName(
  slotKey: string,
  servants: RunbookAccountServant[],
): string {
  const [name, className = ''] = slotKey.split('|');
  const sameNameCount = servants.filter((servant) => servant.name === name).length;
  return sameNameCount > 1 && className ? `${name}(${className})` : name;
}
