export interface DrawLoraFields {
  loras_json?: string | null;
  lora_anima_turbo?: number | string | boolean | null;
  lora_high_contrast?: number | string | boolean | null;
}

const LEGACY_LORAS: [keyof DrawLoraFields, string][] = [
  ['lora_anima_turbo', 'anima-turbo-lora-v0.2'],
  ['lora_high_contrast', 'high-contrast aesthetic'],
];

function isEnabled(value: number | string | boolean | null | undefined): boolean {
  return value === 1 || value === '1' || value === true;
}

export function parseDrawLoras(record: DrawLoraFields): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  const append = (value: unknown) => {
    const name = String(value ?? '').trim().replace(/\.safetensors$/i, '');
    if (!name) return;
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    names.push(name);
  };

  try {
    const parsed = JSON.parse(String(record.loras_json || '[]'));
    if (Array.isArray(parsed)) parsed.forEach(append);
  } catch {
    // Historical records may contain malformed JSON. Legacy fields below still apply.
  }

  for (const [key, name] of LEGACY_LORAS) {
    if (isEnabled(record[key])) append(name);
  }
  return names;
}

export function visibleDrawLoras(record: DrawLoraFields, limit = 3): {
  names: string[];
  visible: string[];
  hiddenCount: number;
  tooltip: string;
} {
  const names = parseDrawLoras(record);
  const visible = names.slice(0, Math.max(0, limit));
  return {
    names,
    visible,
    hiddenCount: Math.max(0, names.length - visible.length),
    tooltip: names.join(' + '),
  };
}
