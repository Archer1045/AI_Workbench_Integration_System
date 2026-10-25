// 绘画参数预设（localStorage）
import { drawStore, type DrawPersistState } from './draw';

const PRESETS_KEY = 'rider-studio:draw-presets-v1';

export interface DrawPreset {
  name: string;
  state: DrawPersistState;
}

export function loadPresets(): DrawPreset[] {
  try {
    const raw = localStorage.getItem(PRESETS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as DrawPreset[];
    return Array.isArray(parsed) ? parsed.filter((item) => item && item.name && item.state) : [];
  } catch {
    return [];
  }
}

export function savePreset(name: string): void {
  const state: DrawPersistState = {
    model: drawStore.model,
    groups: drawStore.groups.map((group) => ({ ...group })),
    negativePrompt: drawStore.negativePrompt,
    width: drawStore.width,
    height: drawStore.height,
    steps: drawStore.steps,
    cfg: drawStore.cfg,
    loras: [...drawStore.loras],
    loraStrengthModel: drawStore.loraStrengthModel,
    loraStrengthClip: drawStore.loraStrengthClip,
    loraStrengths: drawStore.loraStrengths,
  };
  const presets = loadPresets().filter((item) => item.name !== name);
  presets.push({ name, state });
  localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

export function deletePreset(name: string): void {
  localStorage.setItem(PRESETS_KEY, JSON.stringify(loadPresets().filter((item) => item.name !== name)));
}

export function applyPreset(name: string): boolean {
  const preset = loadPresets().find((item) => item.name === name);
  if (!preset) return false;
  const state = preset.state;
  drawStore.model = state.model;
  drawStore.groups = state.groups.map((group) => ({ ...group }));
  drawStore.negativePrompt = state.negativePrompt;
  drawStore.width = state.width;
  drawStore.height = state.height;
  drawStore.steps = state.steps;
  drawStore.cfg = state.cfg;
  drawStore.loras = [...state.loras];
  drawStore.loraStrengthModel = state.loraStrengthModel;
  drawStore.loraStrengthClip = state.loraStrengthClip;
  return true;
}
