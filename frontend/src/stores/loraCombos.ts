// AI 绘画常用 LoRA 搭配（localStorage，初始为空，不内置旧推荐组合）
import { drawStore } from './draw';

const LORA_COMBOS_KEY = 'rider-studio:draw-lora-combos-v1';

export interface LoraCombo {
  id: string;
  name: string;
  loras: string[];
  strengths: Record<string, { model: number; clip: number }>;
}

export function loadLoraCombos(): LoraCombo[] {
  try {
    const raw = localStorage.getItem(LORA_COMBOS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as LoraCombo[];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item) =>
        item &&
        typeof item.id === 'string' &&
        typeof item.name === 'string' &&
        Array.isArray(item.loras),
    );
  } catch {
    return [];
  }
}

function persist(combos: LoraCombo[]): void {
  try {
    localStorage.setItem(LORA_COMBOS_KEY, JSON.stringify(combos));
  } catch {
    // 隐私模式或存储满时静默失败
  }
}

export function saveLoraCombo(name: string, loras: string[], strengths: LoraCombo['strengths']): void {
  const combos = loadLoraCombos().filter((item) => item.name !== name);
  combos.push({
    id: `${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    name,
    loras: [...loras],
    strengths,
  });
  persist(combos);
}

export function deleteLoraCombo(id: string): void {
  persist(loadLoraCombos().filter((item) => item.id !== id));
}

export function applyLoraCombo(combo: LoraCombo): void {
  drawStore.loras = [...combo.loras];
  const strengths: Record<string, { model: number; clip: number }> = {};
  for (const name of combo.loras) {
    const value = combo.strengths?.[name] || drawStore.loraStrengths[name];
    strengths[name] = value || { model: drawStore.loraStrengthModel, clip: drawStore.loraStrengthClip };
  }
  drawStore.loraStrengths = strengths;
}
