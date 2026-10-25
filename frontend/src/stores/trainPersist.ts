import { getRuntimeConfig } from './runtimeConfig';

// LoRA 训练/打标配置持久化：刷新后恢复表单，避免每次手动重填
export type CaptionMode = 'wd14' | 'qwen';
export type CaptionLanguage = 'tags' | 'description';

export interface TrainPersistState {
  mode: CaptionMode;
  language: CaptionLanguage;
  skipExisting: boolean;
  threshold: number;
  captionBatchSize: number;
  removeUnderscore: boolean;
  dit: string;
  outputName: string;
  resolution: number;
  repeats: number;
  trainBatchSize: number;
  networkDim: number;
  networkAlpha: number;
  learningRate: number;
  epochs: number;
  saveEvery: number;
  maxSteps: number;
  autoConvert: boolean;
  optimizerType: string;
  lrScheduler: string;
  mixedPrecision: string;
  gradientAccumulation: number;
  warmupSteps: number;
  discreteFlowShift: number;
  gradientCheckpointing: boolean;
  cacheLatents: boolean;
  cacheLatentsToDisk: boolean;
  saveState: boolean;
  shuffleCaption: boolean;
  keepTokens: number;
  bucketMinReso: number;
  bucketMaxReso: number;
  bucketResoSteps: number;
}

export const TRAIN_STATE_KEY = 'rider-studio:train-config-v1';
const TRAIN_STATE_VERSION = 1;

export interface TrainComparePersistState {
  prompt: string;
  negativePrompt: string;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  seedText: string;
  loras: string[];
  comboLoras: string[];
  comboStrengths: Record<string, { model: number; clip: number }>;
  skipTurboDuplicate: boolean;
}

export const TRAIN_COMPARE_STATE_KEY = 'rider-studio:train-compare-config-v1';
const TRAIN_COMPARE_STATE_VERSION = 1;

function runtimeDefaults(): TrainPersistState {
  const config = getRuntimeConfig().train;
  return {
    mode: 'wd14',
    language: 'tags',
    skipExisting: config.default_skip_existing,
    threshold: config.default_caption_threshold,
    captionBatchSize: config.default_caption_batch_size,
    removeUnderscore: config.default_remove_underscore,
    dit: '',
    outputName: '',
    resolution: config.default_resolution,
    repeats: config.default_repeats,
    trainBatchSize: config.default_batch_size,
    networkDim: config.default_network_dim,
    networkAlpha: config.default_network_alpha,
    learningRate: config.default_learning_rate,
    epochs: config.default_epochs,
    saveEvery: config.default_save_every,
    maxSteps: config.default_max_steps,
    autoConvert: config.default_auto_convert,
    optimizerType: 'AdamW8bit',
    lrScheduler: 'cosine',
    mixedPrecision: 'bf16',
    gradientAccumulation: 1,
    warmupSteps: 100,
    discreteFlowShift: 1,
    gradientCheckpointing: true,
    cacheLatents: true,
    cacheLatentsToDisk: true,
    saveState: true,
    shuffleCaption: false,
    keepTokens: 1,
    bucketMinReso: 512,
    bucketMaxReso: 1536,
    bucketResoSteps: 64,
  };
}

function clamp(value: unknown, min: number, max: number, fallback: number): number {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

export function loadTrainState(): TrainPersistState {
  const defaults = runtimeDefaults();
  const trainConfig = getRuntimeConfig().train;
  try {
    const raw = localStorage.getItem(TRAIN_STATE_KEY);
    if (!raw) return { ...defaults };
    const parsed = JSON.parse(raw) as Partial<TrainPersistState> & { v?: number };
    if (!parsed || parsed.v !== TRAIN_STATE_VERSION) return { ...defaults };
    return {
      mode: parsed.mode === 'qwen' ? 'qwen' : 'wd14',
      language: parsed.language === 'description' ? 'description' : 'tags',
      skipExisting:
        typeof parsed.skipExisting === 'boolean' ? parsed.skipExisting : defaults.skipExisting,
      threshold: clamp(
        parsed.threshold,
        trainConfig.caption_threshold_min,
        trainConfig.caption_threshold_max,
        defaults.threshold,
      ),
      captionBatchSize: Math.round(
        clamp(
          parsed.captionBatchSize,
          trainConfig.caption_batch_min,
          trainConfig.caption_batch_max,
          defaults.captionBatchSize,
        ),
      ),
      removeUnderscore:
        typeof parsed.removeUnderscore === 'boolean'
          ? parsed.removeUnderscore
          : defaults.removeUnderscore,
      dit: typeof parsed.dit === 'string' ? parsed.dit : '',
      outputName: typeof parsed.outputName === 'string' ? parsed.outputName : '',
      resolution: Math.round(clamp(parsed.resolution, trainConfig.resolution_min, trainConfig.resolution_max, defaults.resolution)),
      repeats: Math.round(clamp(parsed.repeats, trainConfig.repeats_min, trainConfig.repeats_max, defaults.repeats)),
      trainBatchSize: Math.round(
        clamp(parsed.trainBatchSize, trainConfig.batch_size_min, trainConfig.batch_size_max, defaults.trainBatchSize),
      ),
      networkDim: Math.round(clamp(parsed.networkDim, trainConfig.network_dim_min, trainConfig.network_dim_max, defaults.networkDim)),
      networkAlpha: Math.round(
        clamp(parsed.networkAlpha, trainConfig.network_alpha_min, trainConfig.network_alpha_max, defaults.networkAlpha),
      ),
      learningRate: clamp(parsed.learningRate, trainConfig.learning_rate_min, trainConfig.learning_rate_max, defaults.learningRate),
      epochs: Math.round(clamp(parsed.epochs, trainConfig.epochs_min, trainConfig.epochs_max, defaults.epochs)),
      saveEvery: Math.round(clamp(parsed.saveEvery, trainConfig.save_every_min, trainConfig.save_every_max, defaults.saveEvery)),
      maxSteps: Math.round(clamp(parsed.maxSteps, trainConfig.max_steps_min, trainConfig.max_steps_max, defaults.maxSteps)),
      autoConvert:
        typeof parsed.autoConvert === 'boolean' ? parsed.autoConvert : defaults.autoConvert,
      optimizerType: typeof parsed.optimizerType === 'string' ? parsed.optimizerType : defaults.optimizerType,
      lrScheduler: typeof parsed.lrScheduler === 'string' ? parsed.lrScheduler : defaults.lrScheduler,
      mixedPrecision: typeof parsed.mixedPrecision === 'string' ? parsed.mixedPrecision : defaults.mixedPrecision,
      gradientAccumulation: Math.round(clamp(parsed.gradientAccumulation, 1, 64, defaults.gradientAccumulation)),
      warmupSteps: Math.round(clamp(parsed.warmupSteps, 0, 100000, defaults.warmupSteps)),
      discreteFlowShift: clamp(parsed.discreteFlowShift, 0.1, 10, defaults.discreteFlowShift),
      gradientCheckpointing: typeof parsed.gradientCheckpointing === 'boolean' ? parsed.gradientCheckpointing : defaults.gradientCheckpointing,
      cacheLatents: typeof parsed.cacheLatents === 'boolean' ? parsed.cacheLatents : defaults.cacheLatents,
      cacheLatentsToDisk: typeof parsed.cacheLatentsToDisk === 'boolean' ? parsed.cacheLatentsToDisk : defaults.cacheLatentsToDisk,
      saveState: typeof parsed.saveState === 'boolean' ? parsed.saveState : defaults.saveState,
      shuffleCaption: typeof parsed.shuffleCaption === 'boolean' ? parsed.shuffleCaption : defaults.shuffleCaption,
      keepTokens: Math.round(clamp(parsed.keepTokens, 0, 100, defaults.keepTokens)),
      bucketMinReso: Math.round(clamp(parsed.bucketMinReso, 256, 4096, defaults.bucketMinReso)),
      bucketMaxReso: Math.round(clamp(parsed.bucketMaxReso, 256, 4096, defaults.bucketMaxReso)),
      bucketResoSteps: Math.round(clamp(parsed.bucketResoSteps, 8, 256, defaults.bucketResoSteps)),
    };
  } catch {
    return { ...defaults };
  }
}

export function saveTrainState(state: TrainPersistState): void {
  try {
    localStorage.setItem(TRAIN_STATE_KEY, JSON.stringify({ v: TRAIN_STATE_VERSION, ...state }));
  } catch {
    // 隐私模式或存储满时静默失败
  }
}

export function loadTrainCompareState(): TrainComparePersistState | null {
  try {
    const raw = localStorage.getItem(TRAIN_COMPARE_STATE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<TrainComparePersistState> & { v?: number };
    if (!parsed || parsed.v !== TRAIN_COMPARE_STATE_VERSION) return null;
    const runtimeConfig = getRuntimeConfig();
    const config = runtimeConfig.compare;
    const drawConfig = runtimeConfig.draw;
    const rawStrengths = parsed.comboStrengths;
    const comboStrengths: Record<string, { model: number; clip: number }> = {};
    if (rawStrengths && typeof rawStrengths === 'object') {
      for (const [name, value] of Object.entries(rawStrengths)) {
        if (value && typeof value.model === 'number' && typeof value.clip === 'number') {
          comboStrengths[name] = {
            model: clamp(
              value.model,
              drawConfig.lora_strength_min,
              drawConfig.lora_strength_max,
              drawConfig.default_lora_strength_model,
            ),
            clip: clamp(
              value.clip,
              drawConfig.lora_strength_min,
              drawConfig.lora_strength_max,
              drawConfig.default_lora_strength_clip,
            ),
          };
        }
      }
    }
    return {
      prompt: typeof parsed.prompt === 'string' ? parsed.prompt : '',
      negativePrompt: typeof parsed.negativePrompt === 'string' ? parsed.negativePrompt : '',
      width: Math.round(clamp(parsed.width, config.width_min, config.width_max, config.default_width)),
      height: Math.round(clamp(parsed.height, config.height_min, config.height_max, config.default_height)),
      steps: Math.round(clamp(parsed.steps, config.steps_min, config.steps_max, config.default_steps)),
      cfg: clamp(parsed.cfg, config.cfg_min, config.cfg_max, config.default_cfg),
      seedText: typeof parsed.seedText === 'string' ? parsed.seedText : '',
      loras: Array.isArray(parsed.loras)
        ? parsed.loras.filter((item): item is string => typeof item === 'string')
        : [],
      comboLoras: Array.isArray(parsed.comboLoras)
        ? parsed.comboLoras.filter((item): item is string => typeof item === 'string')
        : [],
      comboStrengths,
      skipTurboDuplicate: parsed.skipTurboDuplicate !== false,
    };
  } catch {
    return null;
  }
}

export function saveTrainCompareState(state: TrainComparePersistState): void {
  try {
    localStorage.setItem(
      TRAIN_COMPARE_STATE_KEY,
      JSON.stringify({ v: TRAIN_COMPARE_STATE_VERSION, ...state }),
    );
  } catch {
    // 隐私模式或存储满时静默失败
  }
}
