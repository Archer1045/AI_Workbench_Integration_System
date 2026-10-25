import type {
  PresetAssetSettings,
  PresetAssetSettingsPayload,
  PresetAssetTarget,
} from './api';

export type PresetAssetSettingsField =
  | 'model'
  | 'steps'
  | 'cfg'
  | 'seed'
  | 'candidate_count'
  | 'focus_x'
  | 'focus_y'
  | 'zoom'
  | 'lora_strength_model'
  | 'lora_strength_clip'
  | 'lora_strengths'
  | 'target';

export type PresetAssetSettingsErrors = Partial<
  Record<PresetAssetSettingsField, string>
>;

type PresetAssetLimits = PresetAssetSettingsPayload['limits'];

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function validateRange(
  value: unknown,
  min: number,
  max: number,
  label: string,
): string | null {
  if (!finiteNumber(value)) return `${label}必须是数字`;
  if (value < min || value > max) {
    return `${label}需在 ${min} 到 ${max} 之间`;
  }
  return null;
}

function validateTarget(
  target: PresetAssetTarget | undefined,
  limits: PresetAssetLimits,
): string | null {
  if (!target) return '当前素材类型缺少输出规格';
  const sizes = [...target.generation_size, ...target.output_size];
  if (sizes.some((value) => !finiteNumber(value) || value <= 0)) {
    return '输出规格必须是正整数';
  }
  const [width, height] = target.generation_size;
  if (width < limits.width_min || width > limits.width_max) {
    return `生成宽度需在 ${limits.width_min} 到 ${limits.width_max} 之间`;
  }
  if (height < limits.height_min || height > limits.height_max) {
    return `生成高度需在 ${limits.height_min} 到 ${limits.height_max} 之间`;
  }
  return null;
}

export function validatePresetAssetSettings(
  settings: PresetAssetSettings,
  limits: PresetAssetLimits,
  target?: PresetAssetTarget,
  options: { requireModel?: boolean; requireTarget?: boolean } = {},
): PresetAssetSettingsErrors {
  const { requireModel = true, requireTarget = true } = options;
  const errors: PresetAssetSettingsErrors = {};
  if (requireModel && !settings.model.trim()) {
    errors.model = '请选择或输入模型';
  }

  errors.steps =
    validateRange(settings.steps, limits.steps_min, limits.steps_max, '步数') ||
    undefined;
  errors.cfg =
    validateRange(settings.cfg, limits.cfg_min, limits.cfg_max, 'CFG') || undefined;
  errors.candidate_count =
    validateRange(
      settings.candidate_count,
      limits.candidate_min,
      limits.candidate_max,
      '候选数量',
    ) || undefined;
  errors.focus_x =
    validateRange(settings.focus_x, limits.focus_min, limits.focus_max, '横向焦点') ||
    undefined;
  errors.focus_y =
    validateRange(settings.focus_y, limits.focus_min, limits.focus_max, '纵向焦点') ||
    undefined;
  errors.zoom =
    validateRange(settings.zoom, limits.zoom_min, limits.zoom_max, '缩放') ||
    undefined;
  errors.lora_strength_model =
    validateRange(
      settings.lora_strength_model,
      limits.lora_strength_min,
      limits.lora_strength_max,
      '默认模型强度',
    ) || undefined;
  errors.lora_strength_clip =
    validateRange(
      settings.lora_strength_clip,
      limits.lora_strength_min,
      limits.lora_strength_max,
      '默认 CLIP 强度',
    ) || undefined;

  if (
    settings.seed_strategy !== 'random' &&
    !finiteNumber(settings.seed)
  ) {
    errors.seed = '固定或递增策略需要填写 Seed';
  } else if (
    settings.seed !== null &&
    (!finiteNumber(settings.seed) ||
      !Number.isInteger(settings.seed) ||
      settings.seed < limits.seed_min ||
      settings.seed > limits.seed_max)
  ) {
    errors.seed = `Seed 需为 ${limits.seed_min} 到 ${limits.seed_max} 之间的整数`;
  }

  const selectedLoras = new Set(settings.loras.map((item) => item.trim()));
  for (const [name, values] of Object.entries(settings.lora_strengths)) {
    if (!selectedLoras.has(name)) {
      errors.lora_strengths = `LoRA“${name}”不在已选列表中`;
      break;
    }
    for (const [kind, label] of [
      ['model', '模型强度'],
      ['clip', 'CLIP 强度'],
    ] as const) {
      if (values[kind] == null) continue;
      const message = validateRange(
        values[kind],
        limits.lora_strength_min,
        limits.lora_strength_max,
        `LoRA“${name}”${label}`,
      );
      if (message) {
        errors.lora_strengths = message;
        break;
      }
    }
    if (errors.lora_strengths) break;
  }

  if (requireTarget) {
    errors.target = validateTarget(target, limits) || undefined;
  }
  return errors;
}

export function firstPresetAssetSettingsError(
  errors: PresetAssetSettingsErrors,
): string | null {
  return (
    Object.values(errors).find((message): message is string => Boolean(message)) ||
    null
  );
}
