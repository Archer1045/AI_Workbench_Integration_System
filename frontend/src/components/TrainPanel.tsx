// LoRA 训练工作区：数据集管理 + 批量打标 + 训练配置与产物
import { Line } from '@ant-design/charts';
import { EditOutlined, ExperimentOutlined, FolderOpenOutlined, InfoCircleOutlined, LeftOutlined, PlayCircleOutlined, ReloadOutlined, RightOutlined, SearchOutlined, StarFilled, StarOutlined, StopOutlined } from '@ant-design/icons';
import { Button, Checkbox, Collapse, Image, Input, InputNumber, message, Modal, Pagination, Popconfirm, Progress, Radio, Segmented, Select, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useRef, useState } from 'react';
import { api, type CaptionJob, type CompareJob, type DatasetCheck, type DatasetInfo, type DatasetReviewJob, type DatasetReviewResult, type DatasetTagReplaceResult, type LoraItem, type MergeJob, type ModelItem, type TrainingJob, type TrainingOutput } from '../api';
import { drawStore } from '../stores/draw';
import { busyBlockMessage, showBusyWarning } from '../stores/busy';
import { getRuntimeConfig } from '../stores/runtimeConfig';
import {
  loadTrainCompareState,
  loadTrainState,
  saveTrainCompareState,
  saveTrainState,
  type TrainComparePersistState,
  type TrainPersistState,
} from '../stores/trainPersist';
import {
  addRecentCompareCombo,
  buildTrainingOutputGroups,
  toggleFavoriteName,
  type TrainingOutputKind,
} from '../trainOutputTools';

const COMPARE_TASK_KEY = 'rider-studio:compare-task-v1';
const COMPARE_LAST_KEY = 'rider-studio:compare-last-v1';
const OUTPUT_FAVORITES_KEY = 'rider-studio:train-output-favorites-v1';
const RECENT_COMPARE_COMBOS_KEY = 'rider-studio:train-recent-compares-v1';
const TRAIN_OUTPUT_PAGE_SIZE = 20;
const savedTrainState = loadTrainState();

function loadStoredStringArray(key: string): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '[]') as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is string => typeof item === 'string');
  } catch {
    return [];
  }
}

function loadStoredStringMatrix(key: string): string[][] {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '[]') as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((combo): combo is string[] => Array.isArray(combo))
      .map((combo) => combo.filter((item): item is string => typeof item === 'string'))
      .filter((combo) => combo.length > 0)
      .slice(0, 5);
  } catch {
    return [];
  }
}

function saveStoredValue(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 隐私模式或存储满时静默失败
  }
}

function saveCompareTask(jobId: string): void {
  try {
    localStorage.setItem(COMPARE_TASK_KEY, JSON.stringify({ jobId }));
  } catch {
    // 忽略存储失败
  }
}

function loadCompareTask(): string {
  try {
    const raw = localStorage.getItem(COMPARE_TASK_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { jobId?: string };
      if (parsed?.jobId) return parsed.jobId;
    }
  } catch {
    // 忽略解析失败
  }
  return '';
}

function clearCompareTask(): void {
  try {
    localStorage.removeItem(COMPARE_TASK_KEY);
  } catch {
    // 忽略存储失败
  }
}

function saveCompareLast(job: CompareJob): void {
  try {
    localStorage.setItem(
      COMPARE_LAST_KEY,
      JSON.stringify({
        v: 1,
        job_id: job.job_id,
        status: job.status,
        total: job.total,
        done: job.done,
        results: job.results || [],
        error: job.error ?? null,
      }),
    );
  } catch {
    // 忽略存储失败
  }
}

function loadCompareLast(): CompareJob | null {
  try {
    const raw = localStorage.getItem(COMPARE_LAST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CompareJob> & { v?: number };
    if (parsed?.v !== 1 || !Array.isArray(parsed.results)) return null;
    return {
      job_id: parsed.job_id || '',
      status:
        parsed.status === 'error' || parsed.status === 'stopped' ? parsed.status : ('done' as const),
      total: Number(parsed.total) || 0,
      done: Number(parsed.done) || 0,
      results: parsed.results,
      error: parsed.error ?? null,
    };
  } catch {
    return null;
  }
}

function clearCompareLast(): void {
  try {
    localStorage.removeItem(COMPARE_LAST_KEY);
  } catch {
    // 忽略存储失败
  }
}

function CompareEllipsis({ text, color }: { text: string; color?: string }) {
  return (
    <Tooltip title={text}>
      <span
        style={{
          display: 'block',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: 12,
          color: color || '#374151',
        }}
      >
        {text}
      </span>
    </Tooltip>
  );
}

function formatDuration(seconds?: number): string {
  if (!seconds) return '';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours > 0 ? `${hours}小时${minutes}分钟` : `${minutes}分钟`;
}

const optimizerOptions = [
  { value: 'AdamW8bit', label: 'AdamW8bit' },
  { value: 'AdamW', label: 'AdamW' },
  { value: 'Lion', label: 'Lion' },
  { value: 'Prodigy', label: 'Prodigy' },
];

const lrSchedulerOptions = [
  { value: 'constant', label: 'constant' },
  { value: 'constant_with_warmup', label: 'constant_with_warmup' },
  { value: 'cosine', label: 'cosine' },
  { value: 'cosine_with_restarts', label: 'cosine_with_restarts' },
  { value: 'linear', label: 'linear' },
];

const precisionOptions = [
  { value: 'bf16', label: 'bf16' },
  { value: 'fp16', label: 'fp16' },
  { value: 'no', label: 'no' },
];

const characterLoraPreset = {
  resolution: 1024,
  repeats: 10,
  trainBatchSize: 1,
  networkDim: 16,
  networkAlpha: 8,
  learningRate: 0.00005,
  epochs: 5,
  saveEvery: 1,
  maxSteps: 0,
  optimizerType: 'AdamW8bit',
  lrScheduler: 'cosine',
  mixedPrecision: 'bf16',
  gradientAccumulation: 1,
  warmupSteps: 200,
  discreteFlowShift: 1,
  gradientCheckpointing: true,
  cacheLatents: true,
  cacheLatentsToDisk: true,
  shuffleCaption: false,
  keepTokens: 1,
  bucketMinReso: 512,
  bucketMaxReso: 1536,
  bucketResoSteps: 64,
};

const styleLoraPreset = {
  resolution: 1024,
  repeats: 10,
  trainBatchSize: 1,
  networkDim: 16,
  networkAlpha: 8,
  learningRate: 0.00005,
  epochs: 8,
  saveEvery: 1,
  maxSteps: 0,
  optimizerType: 'AdamW8bit',
  lrScheduler: 'cosine',
  mixedPrecision: 'bf16',
  gradientAccumulation: 1,
  warmupSteps: 200,
  discreteFlowShift: 1,
  gradientCheckpointing: true,
  cacheLatents: true,
  cacheLatentsToDisk: true,
  shuffleCaption: true,
  keepTokens: 1,
  bucketMinReso: 512,
  bucketMaxReso: 1536,
  bucketResoSteps: 64,
};

// 2026-10-11 起常驻区只暴露成对的 dim/alpha 档位，避免出现 dim 32 配 alpha 7 这类畸形搭配。
const DIM_OPTIONS = [
  { label: '16 / 8（角色、画风通用）', value: 16 },
  { label: '32 / 16（细节更多，也更易过拟合）', value: 32 },
  { label: '64 / 32（复杂服装或特效）', value: 64 },
];

function presetNameFor(state: {
  networkDim: number;
  networkAlpha: number;
  learningRate: number;
  repeats: number;
  epochs: number;
}): 'character' | 'style' | 'custom' {
  const matches = (preset: typeof characterLoraPreset) =>
    state.networkDim === preset.networkDim &&
    state.networkAlpha === preset.networkAlpha &&
    state.learningRate === preset.learningRate &&
    state.repeats === preset.repeats &&
    state.epochs === preset.epochs;
  if (matches(characterLoraPreset)) return 'character';
  if (matches(styleLoraPreset)) return 'style';
  return 'custom';
}

function formatPlainDecimal(value: number | string | null | undefined, maxDigits = 10): string {
  if (value === null || value === undefined || value === '') return '';
  const num = Number(value);
  if (!Number.isFinite(num)) return '';
  return num
    .toFixed(maxDigits)
    .replace(/(\.\d*?[1-9])0+$/, '$1')
    .replace(/\.0+$/, '');
}

function parsePlainDecimal(value: string | undefined): number {
  if (!value) return 0;
  const num = Number(value.replace(/,/g, '').trim());
  return Number.isFinite(num) ? num : 0;
}

export default function TrainPanel() {
  const runtimeConfig = getRuntimeConfig();
  const compareConfig = runtimeConfig.compare;
  const drawConfig = runtimeConfig.draw;
  const trainConfig = runtimeConfig.train;
  const [initialCompareState] = useState<TrainComparePersistState | null>(loadTrainCompareState);
  const [info, setInfo] = useState<DatasetInfo | null>(null);
  const [mode, setMode] = useState<'wd14' | 'qwen'>(savedTrainState.mode);
  const [language, setLanguage] = useState<'tags' | 'description'>(savedTrainState.language);
  const [skipExisting, setSkipExisting] = useState(savedTrainState.skipExisting);
  const [threshold, setThreshold] = useState(savedTrainState.threshold);
  const [captionBatchSize, setCaptionBatchSize] = useState(savedTrainState.captionBatchSize);
  const [removeUnderscore, setRemoveUnderscore] = useState(savedTrainState.removeUnderscore);
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState<CaptionJob | null>(null);
  const [starting, setStarting] = useState(false);

  const [models, setModels] = useState<ModelItem[]>([]);
  const [dit, setDit] = useState(savedTrainState.dit);
  const [outputName, setOutputName] = useState(savedTrainState.outputName);
  const [resolution, setResolution] = useState(savedTrainState.resolution);
  const [repeats, setRepeats] = useState(savedTrainState.repeats);
  const [trainBatchSize, setTrainBatchSize] = useState(savedTrainState.trainBatchSize);
  const [networkDim, setNetworkDim] = useState(savedTrainState.networkDim);
  const [networkAlpha, setNetworkAlpha] = useState(savedTrainState.networkAlpha);
  const [learningRate, setLearningRate] = useState(savedTrainState.learningRate);
  const [epochs, setEpochs] = useState(savedTrainState.epochs);
  const [saveEvery, setSaveEvery] = useState(savedTrainState.saveEvery);
  const [maxSteps, setMaxSteps] = useState(savedTrainState.maxSteps);
  const [autoConvert, setAutoConvert] = useState(savedTrainState.autoConvert);
  const [optimizerType, setOptimizerType] = useState(savedTrainState.optimizerType);
  const [lrScheduler, setLrScheduler] = useState(savedTrainState.lrScheduler);
  const [mixedPrecision, setMixedPrecision] = useState(savedTrainState.mixedPrecision);
  const [gradientAccumulation, setGradientAccumulation] = useState(savedTrainState.gradientAccumulation);
  const [warmupSteps, setWarmupSteps] = useState(savedTrainState.warmupSteps);
  const [discreteFlowShift, setDiscreteFlowShift] = useState(savedTrainState.discreteFlowShift);
  const [gradientCheckpointing, setGradientCheckpointing] = useState(savedTrainState.gradientCheckpointing);
  const [cacheLatents, setCacheLatents] = useState(savedTrainState.cacheLatents);
  const [cacheLatentsToDisk, setCacheLatentsToDisk] = useState(savedTrainState.cacheLatentsToDisk);
  const [saveState, setSaveState] = useState(savedTrainState.saveState);
  const [shuffleCaption, setShuffleCaption] = useState(savedTrainState.shuffleCaption);
  const [keepTokens, setKeepTokens] = useState(savedTrainState.keepTokens);
  const [bucketMinReso, setBucketMinReso] = useState(savedTrainState.bucketMinReso);
  const [bucketMaxReso, setBucketMaxReso] = useState(savedTrainState.bucketMaxReso);
  const [bucketResoSteps, setBucketResoSteps] = useState(savedTrainState.bucketResoSteps);
  const [trainJobId, setTrainJobId] = useState('');
  const [trainJob, setTrainJob] = useState<TrainingJob | null>(null);
  const [resuming, setResuming] = useState(false);
  const [reviewJobId, setReviewJobId] = useState('');
  const [reviewJob, setReviewJob] = useState<DatasetReviewJob | null>(null);
  const [reviewConfirmOpen, setReviewConfirmOpen] = useState(false);
  const [nameConflicts, setNameConflicts] = useState<string[]>([]);
  const [suggestedName, setSuggestedName] = useState('');
  const [nameConflictOpen, setNameConflictOpen] = useState(false);
  const overwriteOutputRef = useRef(false);
  const [selectedReviewFiles, setSelectedReviewFiles] = useState<string[]>([]);
  const [reviewFilter, setReviewFilter] = useState<'all' | 'broken'>('all');
  const [signatureItems, setSignatureItems] = useState<{ filename: string; caption_name: string; matched: string[] }[]>([]);
  const [signatureOpen, setSignatureOpen] = useState(false);
  const [signatureLoading, setSignatureLoading] = useState(false);
  const [mergeSourceA, setMergeSourceA] = useState('');
  const [mergeSourceB, setMergeSourceB] = useState('');
  const [mergeRatioA, setMergeRatioA] = useState(trainConfig.merge_ratio_default);
  const [mergeRatioB, setMergeRatioB] = useState(trainConfig.merge_ratio_default);
  const [mergeOutputName, setMergeOutputName] = useState('');
  const [mergeOverwrite, setMergeOverwrite] = useState(false);
  const [mergeJob, setMergeJob] = useState<MergeJob | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const [comparePrompt, setComparePrompt] = useState(
    initialCompareState?.prompt || drawStore.groups.find((group) => group.prompt.trim())?.prompt || '',
  );
  const [compareNegative, setCompareNegative] = useState(
    initialCompareState?.negativePrompt ?? drawStore.negativePrompt,
  );
  const [compareWidth, setCompareWidth] = useState(
    initialCompareState?.width ?? compareConfig.default_width,
  );
  const [compareHeight, setCompareHeight] = useState(
    initialCompareState?.height ?? compareConfig.default_height,
  );
  const [compareSteps, setCompareSteps] = useState(
    initialCompareState?.steps ?? compareConfig.default_steps,
  );
  const [compareCfg, setCompareCfg] = useState(initialCompareState?.cfg ?? compareConfig.default_cfg);
  const [compareSeed, setCompareSeed] = useState(initialCompareState?.seedText || '');
  const [compareLoras, setCompareLoras] = useState<string[]>(
    initialCompareState?.loras.filter((name) =>
      drawStore.loras.some((available) => available === name),
    ) ?? [],
  );
  const [compareComboLoras, setCompareComboLoras] = useState<string[]>(
    initialCompareState?.comboLoras ?? [],
  );
  const [compareComboStrengths, setCompareComboStrengths] = useState<
    Record<string, { model: number; clip: number }>
  >(initialCompareState?.comboStrengths ?? {});
  const [skipTurboDuplicate, setSkipTurboDuplicate] = useState(
    initialCompareState?.skipTurboDuplicate ?? true,
  );
  const [compareJob, setCompareJob] = useState<CompareJob | null>(null);
  const [compareStarting, setCompareStarting] = useState(false);
  const [compareElapsed, setCompareElapsed] = useState(0);
  const [comparePreviewIndex, setComparePreviewIndex] = useState(0);
  const [trainStarting, setTrainStarting] = useState(false);
  const [outputs, setOutputs] = useState<TrainingOutput[]>([]);
  const [lorasList, setLorasList] = useState<LoraItem[]>([]);
  const [lorasLoading, setLorasLoading] = useState(false);
  const [copying, setCopying] = useState('');
  const [highlightName, setHighlightName] = useState('');
  const [outputFilter, setOutputFilter] = useState<TrainingOutputKind>('all');
  const [outputSearch, setOutputSearch] = useState('');
  const [outputFavorites, setOutputFavorites] = useState<string[]>(() =>
    loadStoredStringArray(OUTPUT_FAVORITES_KEY),
  );
  const [outputPage, setOutputPage] = useState(1);
  const [expandedOutputFamilies, setExpandedOutputFamilies] = useState<string[]>([]);
  const [compareSearch, setCompareSearch] = useState('');
  const [expandedCompareFamilies, setExpandedCompareFamilies] = useState<string[]>([]);
  const [recentCompareCombos, setRecentCompareCombos] = useState<string[][]>(() =>
    loadStoredStringMatrix(RECENT_COMPARE_COMBOS_KEY),
  );
  const [checkOpen, setCheckOpen] = useState(false);
  const [checkData, setCheckData] = useState<DatasetCheck | null>(null);
  const [checkLoading, setCheckLoading] = useState(false);
  const [tagEditOpen, setTagEditOpen] = useState(false);
  const [tagFrom, setTagFrom] = useState('');
  const [tagTo, setTagTo] = useState('');
  const [tagPreview, setTagPreview] = useState<DatasetTagReplaceResult | null>(null);
  const [tagPreviewing, setTagPreviewing] = useState(false);
  const [tagApplying, setTagApplying] = useState(false);
  const highlightRef = useRef<Record<string, HTMLDivElement | null>>({});
  const drawingLoras = lorasList.filter((item) => item.compatible !== false);
  const outputGroups = buildTrainingOutputGroups(outputs, {
    search: outputSearch,
    kind: outputFilter,
    favorites: outputFavorites,
  });
  const filteredOutputFileCount = outputGroups.reduce(
    (total, group) => total + group.items.length,
    0,
  );
  const outputPageCount = Math.max(1, Math.ceil(outputGroups.length / TRAIN_OUTPUT_PAGE_SIZE));
  const currentOutputPage = Math.min(outputPage, outputPageCount);
  const visibleOutputGroups = outputGroups.slice(
    (currentOutputPage - 1) * TRAIN_OUTPUT_PAGE_SIZE,
    currentOutputPage * TRAIN_OUTPUT_PAGE_SIZE,
  );
  const compareGroups = buildTrainingOutputGroups(drawingLoras, {
    search: compareSearch,
    kind: 'all',
    favorites: [],
  });
  const effectiveCompareFamilies = compareSearch.trim()
    ? compareGroups.map((group) => group.key)
    : expandedCompareFamilies;

  const loadDataset = () => {
    api
      .get<DatasetInfo>('/train/dataset')
      .then((res) => setInfo(res.data))
      .catch(() => setInfo(null));
  };

  const loadOutputs = () => {
    api
      .get<{ items: TrainingOutput[] }>('/train/outputs')
      .then((res) => setOutputs(res.data.items || []))
      .catch(() => setOutputs([]));
  };

  const loadLoras = () => {
    setLorasLoading(true);
    api
      .get<{ loras: LoraItem[] }>('/loras')
      .then((res) => {
        const list = res.data.loras || [];
        setLorasList(list);
        const usable = list.filter((item) => item.compatible !== false);
        if (!mergeSourceA && usable.length > 0) {
          const turbo = usable.find((item) => item.name.includes('anima-turbo-lora-v0.2'));
          const style =
            usable.find((item) => item.name.includes('my_nekojira_thea_turbo_comfy_v3')) || usable[1] || usable[0];
          setMergeSourceA(turbo?.name || usable[0].name);
          setMergeSourceB(style?.name || usable[0].name);
        }
      })
      .catch(() => setLorasList([]))
      .finally(() => setLorasLoading(false));
  };

  useEffect(() => {
    loadDataset();
    loadOutputs();
    loadLoras();
    api
      .get<TrainingJob>('/train/training')
      .then((res) => {
        if (res.data && res.data.job_id) {
          setTrainJobId(res.data.job_id);
          setTrainJob(res.data);
        }
      })
      .catch(() => undefined);
    api
      .get<{ models: ModelItem[]; default: string }>('/models')
      .then((res) => {
        setModels(res.data.models || []);
        const preferred =
          (res.data.models || []).find((item) => item.name.includes('_net')) ||
          (res.data.models || []).find((item) => item.name.includes('miaomiaoHarem'));
        setDit((current) => current || preferred?.name || res.data.default || '');
      })
      .catch(() => setModels([]));
  }, []);

  useEffect(() => {
    const state: TrainPersistState = {
      mode,
      language,
      skipExisting,
      threshold,
      captionBatchSize,
      removeUnderscore,
      dit,
      outputName,
      resolution,
      repeats,
      trainBatchSize,
      networkDim,
      networkAlpha,
      learningRate,
      epochs,
      saveEvery,
      maxSteps,
      autoConvert,
      optimizerType,
      lrScheduler,
      mixedPrecision,
      gradientAccumulation,
      warmupSteps,
      discreteFlowShift,
      gradientCheckpointing,
      cacheLatents,
      cacheLatentsToDisk,
      saveState,
      shuffleCaption,
      keepTokens,
      bucketMinReso,
      bucketMaxReso,
      bucketResoSteps,
    };
    saveTrainState(state);
  }, [
    mode,
    language,
    skipExisting,
    threshold,
    captionBatchSize,
    removeUnderscore,
    dit,
    outputName,
    resolution,
    repeats,
    trainBatchSize,
    networkDim,
    networkAlpha,
    learningRate,
    epochs,
    saveEvery,
    maxSteps,
    autoConvert,
    optimizerType,
    lrScheduler,
    mixedPrecision,
    gradientAccumulation,
    warmupSteps,
    discreteFlowShift,
    gradientCheckpointing,
    cacheLatents,
    cacheLatentsToDisk,
    saveState,
    shuffleCaption,
    keepTokens,
    bucketMinReso,
    bucketMaxReso,
    bucketResoSteps,
  ]);

  useEffect(() => {
    saveTrainCompareState({
      prompt: comparePrompt,
      negativePrompt: compareNegative,
      width: compareWidth,
      height: compareHeight,
      steps: compareSteps,
      cfg: compareCfg,
      seedText: compareSeed,
      loras: compareLoras,
      comboLoras: compareComboLoras,
      comboStrengths: compareComboStrengths,
      skipTurboDuplicate,
    });
  }, [
    comparePrompt,
    compareNegative,
    compareWidth,
    compareHeight,
    compareSteps,
    compareCfg,
    compareSeed,
    compareLoras,
    compareComboLoras,
    compareComboStrengths,
    skipTurboDuplicate,
  ]);

  useEffect(() => {
    saveStoredValue(OUTPUT_FAVORITES_KEY, outputFavorites);
  }, [outputFavorites]);

  useEffect(() => {
    saveStoredValue(RECENT_COMPARE_COMBOS_KEY, recentCompareCombos);
  }, [recentCompareCombos]);

  useEffect(() => {
    if (!jobId) return;
    let timer = 0;
    const tick = () => {
      api
        .get<CaptionJob>(`/train/caption/${jobId}`)
        .then((res) => {
          setJob(res.data);
          if (res.data.status === 'running') {
            timer = window.setTimeout(tick, 2000);
          } else {
            loadDataset();
          }
        })
        .catch(() => {
          timer = window.setTimeout(tick, 5000);
        });
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [jobId]);

  useEffect(() => {
    if (!trainJobId) return;
    let timer = 0;
    const tick = () => {
      api
        .get<TrainingJob>(`/train/training/${trainJobId}`)
        .then((res) => {
          setTrainJob(res.data);
          if (res.data.converting) {
            loadOutputs();
            timer = window.setTimeout(tick, 3000);
          } else if (res.data.status === 'running') {
            timer = window.setTimeout(tick, 3000);
          } else {
            loadOutputs();
          }
        })
        .catch(() => {
          timer = window.setTimeout(tick, 5000);
        });
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [trainJobId]);

  useEffect(() => {
    if (!reviewJobId) return;
    let timer = 0;
    const tick = () => {
      api
        .get<DatasetReviewJob>(`/train/dataset/review/${reviewJobId}`)
        .then((res) => {
          setReviewJob(res.data);
          if (res.data.status === 'running') {
            timer = window.setTimeout(tick, 2000);
          } else {
            loadDataset();
          }
        })
        .catch(() => {
          timer = window.setTimeout(tick, 5000);
        });
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [reviewJobId]);

  useEffect(() => {
    const savedId = loadCompareTask();
    const last = loadCompareLast();
    if (!savedId) {
      if (last && last.results && last.results.length > 0) {
        setCompareJob(last);
      }
      return;
    }
    let cancelled = false;
    api
      .get<CompareJob>(`/train/compare/${savedId}`)
      .then((res) => {
        if (cancelled) return;
        if (res.data.status === 'running') {
          setCompareJob({ ...res.data, results: res.data.results || [] });
          const poll = async () => {
            while (true) {
              await new Promise((resolve) => setTimeout(resolve, 2000));
              try {
                const next = await api.get<CompareJob>(`/train/compare/${savedId}`);
                if (cancelled) return;
                setCompareJob(next.data);
                if (next.data.status !== 'running') {
                  saveCompareLast(next.data);
                  clearCompareTask();
                  return;
                }
              } catch {
                return;
              }
            }
          };
          void poll();
        } else {
          saveCompareLast(res.data);
          clearCompareTask();
        }
      })
      .catch(() => clearCompareTask());
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (compareJob?.status !== 'running') {
      setCompareElapsed(0);
      return;
    }
    setCompareElapsed(0);
    const timer = window.setInterval(() => setCompareElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [compareJob?.status]);

  useEffect(() => {
    if (!highlightName) return;
    const element = highlightRef.current[highlightName];
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const timer = window.setTimeout(() => setHighlightName(''), 2500);
    return () => window.clearTimeout(timer);
  }, [highlightName]);

  const handleStartCaption = async () => {
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    setStarting(true);
    try {
      const { data } = await api.post<{ job_id: string; status: string }>('/train/caption', {
        mode,
        skip_existing: skipExisting,
        threshold,
        batch_size: captionBatchSize,
        remove_underscore: removeUnderscore,
        language,
      });
      setJobId(data.job_id);
      setJob({
        job_id: data.job_id,
        mode,
        status: 'running',
        total: 0,
        done: 0,
        last_file: '',
        log: '',
        error: null,
      });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '启动失败');
    } finally {
      setStarting(false);
    }
  };

  const handleStopCaption = async () => {
    if (!jobId) return;
    try {
      await api.post(`/train/caption/${jobId}/stop`);
    } catch {
      message.error('停止失败');
    }
  };

  const handleOpen = () => {
    api.post('/train/open-dataset').catch(() => message.error('打开数据集失败'));
  };

  const handleCheck = async () => {
    setCheckLoading(true);
    try {
      const { data } = await api.get<DatasetCheck>('/train/dataset-check');
      setCheckData(data);
      setCheckOpen(true);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '体检失败');
    } finally {
      setCheckLoading(false);
    }
  };

  const handleTagPreview = async () => {
    const from = tagFrom.trim();
    if (!from) {
      message.warning('请先输入原标签');
      return;
    }
    setTagPreviewing(true);
    try {
      const { data } = await api.post<DatasetTagReplaceResult>('/train/dataset/tags/replace', {
        from_tag: from,
        to_tag: tagTo.trim(),
        dry_run: true,
      });
      setTagPreview(data);
      if (data.affected_files === 0) message.info('没有标签文件包含该标签');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '预览失败');
    } finally {
      setTagPreviewing(false);
    }
  };

  const handleTagApply = async () => {
    if (!tagPreview) return;
    setTagApplying(true);
    try {
      const { data } = await api.post<DatasetTagReplaceResult>('/train/dataset/tags/replace', {
        from_tag: tagFrom.trim(),
        to_tag: tagTo.trim(),
        dry_run: false,
      });
      message.success(
        `已替换 ${data.affected_files} 个文件，共 ${data.affected_tags} 处${data.backup_dir ? `；备份：${data.backup_dir}` : ''}`,
      );
      loadDataset();
      setTagEditOpen(false);
      setTagFrom('');
      setTagTo('');
      setTagPreview(null);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '替换失败');
    } finally {
      setTagApplying(false);
    }
  };

  // 训练产物同名检查：表单默认沿用上次的 LoRA 名称，提前提示会覆盖哪些已有产物
  useEffect(() => {
    const name = outputName.trim();
    if (!name) {
      setNameConflicts([]);
      setSuggestedName('');
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .get<{ conflicts: string[]; suggested_name: string }>('/train/output-name-check', {
          params: { output_name: name },
        })
        .then(({ data }) => {
          if (cancelled) return;
          setNameConflicts(data.conflicts || []);
          setSuggestedName(data.suggested_name || '');
        })
        .catch(() => {
          if (cancelled) return;
          setNameConflicts([]);
          setSuggestedName('');
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [outputName]);

  const applyCharacterLoraPreset = () => {
    setResolution(characterLoraPreset.resolution);
    setRepeats(characterLoraPreset.repeats);
    setTrainBatchSize(characterLoraPreset.trainBatchSize);
    setNetworkDim(characterLoraPreset.networkDim);
    setNetworkAlpha(characterLoraPreset.networkAlpha);
    setLearningRate(characterLoraPreset.learningRate);
    setEpochs(characterLoraPreset.epochs);
    setSaveEvery(characterLoraPreset.saveEvery);
    setMaxSteps(characterLoraPreset.maxSteps);
    setOptimizerType(characterLoraPreset.optimizerType);
    setLrScheduler(characterLoraPreset.lrScheduler);
    setMixedPrecision(characterLoraPreset.mixedPrecision);
    setGradientAccumulation(characterLoraPreset.gradientAccumulation);
    setWarmupSteps(characterLoraPreset.warmupSteps);
    setDiscreteFlowShift(characterLoraPreset.discreteFlowShift);
    setGradientCheckpointing(characterLoraPreset.gradientCheckpointing);
    setCacheLatents(characterLoraPreset.cacheLatents);
    setCacheLatentsToDisk(characterLoraPreset.cacheLatentsToDisk);
    setShuffleCaption(characterLoraPreset.shuffleCaption);
    setKeepTokens(characterLoraPreset.keepTokens);
    setBucketMinReso(characterLoraPreset.bucketMinReso);
    setBucketMaxReso(characterLoraPreset.bucketMaxReso);
    setBucketResoSteps(characterLoraPreset.bucketResoSteps);
    message.success('已应用角色 LoRA 推荐参数');
  };

  const applyStyleLoraPreset = () => {
    setResolution(styleLoraPreset.resolution);
    setRepeats(styleLoraPreset.repeats);
    setTrainBatchSize(styleLoraPreset.trainBatchSize);
    setNetworkDim(styleLoraPreset.networkDim);
    setNetworkAlpha(styleLoraPreset.networkAlpha);
    setLearningRate(styleLoraPreset.learningRate);
    setEpochs(styleLoraPreset.epochs);
    setSaveEvery(styleLoraPreset.saveEvery);
    setMaxSteps(styleLoraPreset.maxSteps);
    setOptimizerType(styleLoraPreset.optimizerType);
    setLrScheduler(styleLoraPreset.lrScheduler);
    setMixedPrecision(styleLoraPreset.mixedPrecision);
    setGradientAccumulation(styleLoraPreset.gradientAccumulation);
    setWarmupSteps(styleLoraPreset.warmupSteps);
    setDiscreteFlowShift(styleLoraPreset.discreteFlowShift);
    setGradientCheckpointing(styleLoraPreset.gradientCheckpointing);
    setCacheLatents(styleLoraPreset.cacheLatents);
    setCacheLatentsToDisk(styleLoraPreset.cacheLatentsToDisk);
    setShuffleCaption(styleLoraPreset.shuffleCaption);
    setKeepTokens(styleLoraPreset.keepTokens);
    setBucketMinReso(styleLoraPreset.bucketMinReso);
    setBucketMaxReso(styleLoraPreset.bucketMaxReso);
    setBucketResoSteps(styleLoraPreset.bucketResoSteps);
    message.success('已应用画风 LoRA 推荐参数');
  };

  // ---- 2026-10-11 训练面板分层：常驻区只留会变的参数，其余收进"高级参数"。 ----
  const presetKind = presetNameFor({ networkDim, networkAlpha, learningRate, repeats, epochs });
  const lrTier =
    learningRate === 0.0001 ? 'character' : learningRate === 0.00005 ? 'style' : 'custom';
  const datasetImageCount = info?.image_count ?? 0;
  const stepsPerEpoch =
    datasetImageCount > 0
      ? Math.ceil((datasetImageCount * repeats) / Math.max(1, trainBatchSize))
      : 0;
  const estimatedSteps = maxSteps > 0 ? maxSteps : stepsPerEpoch * epochs;
  const estimatedMinutes = Math.round((estimatedSteps * 3.8) / 60);
  const advancedDiffs = [
    resolution !== trainConfig.default_resolution ? '分辨率' : '',
    trainBatchSize !== trainConfig.default_batch_size ? 'Batch' : '',
    saveEvery !== trainConfig.default_save_every ? '保存间隔' : '',
    maxSteps !== trainConfig.default_max_steps ? '最大步数' : '',
    optimizerType !== 'AdamW8bit' ? '优化器' : '',
    lrScheduler !== 'cosine' ? '调度器' : '',
    mixedPrecision !== 'bf16' ? '混合精度' : '',
    gradientAccumulation !== 1 ? '梯度累积' : '',
    warmupSteps !== 200 ? 'Warmup' : '',
    discreteFlowShift !== 1 ? 'Flow Shift' : '',
    keepTokens !== 1 ? 'Keep Tokens' : '',
    bucketMinReso !== 512 || bucketMaxReso !== 1536 || bucketResoSteps !== 64 ? 'Bucket' : '',
    !gradientCheckpointing ? '梯度检查点已关' : '',
    !cacheLatents ? 'Latents 缓存已关' : '',
    shuffleCaption ? '打乱标签已开' : '',
    !saveState ? '未保存训练状态' : '',
  ].filter(Boolean);
  const advancedLabel = advancedDiffs.length
    ? `高级参数（默认折叠 · 已偏离默认 ${advancedDiffs.length} 项：${advancedDiffs.slice(0, 4).join('、')}${advancedDiffs.length > 4 ? ' 等' : ''}）`
    : '高级参数（默认折叠 · 当前均为推荐值）';

  const describePresetChanges = (preset: typeof characterLoraPreset) => {
    const changes: string[] = [];
    if (preset.networkDim !== networkDim) changes.push(`dim ${networkDim}→${preset.networkDim}`);
    if (preset.networkAlpha !== networkAlpha) changes.push(`alpha ${networkAlpha}→${preset.networkAlpha}`);
    if (preset.learningRate !== learningRate) {
      changes.push(`学习率 ${formatPlainDecimal(learningRate)}→${formatPlainDecimal(preset.learningRate)}`);
    }
    if (preset.repeats !== repeats) changes.push(`repeats ${repeats}→${preset.repeats}`);
    if (preset.epochs !== epochs) changes.push(`轮数 ${epochs}→${preset.epochs}`);
    if (preset.shuffleCaption !== shuffleCaption) {
      changes.push(`打乱标签 ${shuffleCaption ? '开' : '关'}→${preset.shuffleCaption ? '开' : '关'}`);
    }
    if (preset.warmupSteps !== warmupSteps) changes.push(`Warmup ${warmupSteps}→${preset.warmupSteps}`);
    if (preset.resolution !== resolution) changes.push(`分辨率 ${resolution}→${preset.resolution}`);
    return changes;
  };

  const applyPreset = (kind: 'character' | 'style' | 'custom') => {
    if (kind === 'custom') return;
    const preset = kind === 'character' ? characterLoraPreset : styleLoraPreset;
    const label = kind === 'character' ? '角色' : '画风';
    const changes = describePresetChanges(preset);
    if (kind === 'character') applyCharacterLoraPreset();
    else applyStyleLoraPreset();
    message.info(
      changes.length
        ? `已应用${label}配方，改动：${changes.join('、')}`
        : `已应用${label}配方（参数本来就一致）`,
    );
  };

  const applyLrTier = (tier: string) => {
    if (tier === 'character') setLearningRate(0.0001);
    else if (tier === 'style') setLearningRate(0.00005);
  };

  const runStartTraining = async (manualConfirmed: boolean, overwriteOutput: boolean) => {
    setTrainStarting(true);
    try {
      const { data } = await api.post<{ job_id: string; status: string }>('/train/start', {
        dit,
        output_name: outputName.trim(),
        resolution,
        repeats,
        batch_size: trainBatchSize,
        network_dim: networkDim,
        network_alpha: networkAlpha,
        learning_rate: learningRate,
        epochs,
        save_every: saveEvery,
        max_steps: maxSteps,
        auto_convert: autoConvert,
        optimizer_type: optimizerType,
        lr_scheduler: lrScheduler,
        mixed_precision: mixedPrecision,
        gradient_accumulation: gradientAccumulation,
        warmup_steps: warmupSteps,
        discrete_flow_shift: discreteFlowShift,
        gradient_checkpointing: gradientCheckpointing,
        cache_latents: cacheLatents,
        cache_latents_to_disk: cacheLatentsToDisk,
        save_state: saveState,
        shuffle_caption: shuffleCaption,
        keep_tokens: keepTokens,
        bucket_min_reso: bucketMinReso,
        bucket_max_reso: bucketMaxReso,
        bucket_reso_steps: bucketResoSteps,
        manual_confirmed: manualConfirmed,
        overwrite_output: overwriteOutput,
      });
      overwriteOutputRef.current = false;
      setTrainJobId(data.job_id);
      setTrainJob({ job_id: data.job_id, output_name: outputName.trim(), status: 'running', log: '', error: null, converting: false });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      if (detail && detail.includes('AI_IMPORT_REVIEW_REQUIRED')) {
        setReviewConfirmOpen(true);
        message.warning('数据集包含 AI 绘画产物，请确认图片质量后继续');
      } else if (detail && detail.includes('OUTPUT_NAME_CONFLICT')) {
        setNameConflictOpen(true);
      } else {
        message.error(detail || '训练启动失败');
      }
    } finally {
      setTrainStarting(false);
    }
  };

  const handleStartTraining = async () => {
    if (!dit) {
      message.error('请选择底模');
      return;
    }
    if (!outputName.trim()) {
      message.error('请填写 LoRA 名称');
      return;
    }
    if (!overwriteOutputRef.current && nameConflicts.length > 0) {
      setNameConflictOpen(true);
      return;
    }
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    await runStartTraining(false, overwriteOutputRef.current);
  };

  const handleStartTrainingConfirmed = async () => {
    setReviewConfirmOpen(false);
    await runStartTraining(true, overwriteOutputRef.current);
  };

  const handleUseSuggestedName = () => {
    if (!suggestedName) return;
    setOutputName(suggestedName);
    setNameConflictOpen(false);
    message.success(`LoRA 名称已改为 ${suggestedName}，请确认参数后重新开始训练`);
  };

  const handleOverwriteOutputConfirmed = async () => {
    setNameConflictOpen(false);
    overwriteOutputRef.current = true;
    await runStartTraining(false, true);
  };

  const handleStartReview = async () => {
    try {
      const { data } = await api.post<{ job_id: string; status: string }>('/train/dataset/review', {});
      setReviewJobId(data.job_id);
      setReviewJob(null);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '审查启动失败');
    }
  };

  const handleExclude = async (filename: string) => {
    try {
      await api.post('/train/dataset/exclude', { filename });
      message.success(`已移出 ${filename}`);
      loadDataset();
      if (reviewJob) {
        setReviewJob({ ...reviewJob, results: reviewJob.results.filter((item) => item.filename !== filename) });
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '移出失败');
    }
  };

  const handleExcludeMany = async (filenames: string[]) => {
    if (filenames.length === 0) return;
    try {
      const { data } = await api.post<{ moved: string[]; skipped: string[] }>('/train/dataset/exclude-many', { filenames });
      message.success(`已移出 ${data.moved.length} 张${data.skipped.length ? `，跳过 ${data.skipped.length} 张` : ''}`);
      if (reviewJob) {
        const removed = new Set(filenames);
        setReviewJob({ ...reviewJob, results: reviewJob.results.filter((item) => !removed.has(item.filename)) });
      }
      setSelectedReviewFiles([]);
      loadDataset();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '批量移出失败');
    }
  };

  const handleDeleteReview = async (filename: string) => {
    try {
      await api.post('/train/dataset/delete', { filename });
      message.success(`已删除 ${filename}`);
      if (reviewJob) {
        setReviewJob({ ...reviewJob, results: reviewJob.results.filter((item) => item.filename !== filename) });
      }
      setSelectedReviewFiles((prev) => prev.filter((item) => item !== filename));
      loadDataset();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '删除失败');
    }
  };

  const handleSignatureScan = async () => {
    setSignatureLoading(true);
    try {
      const { data } = await api.get<{ items: { filename: string; caption_name: string; matched: string[] }[] }>(
        '/train/dataset/signature-scan',
      );
      setSignatureItems(data.items || []);
      setSignatureOpen(true);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '签名扫描失败');
    } finally {
      setSignatureLoading(false);
    }
  };

  const handleStartMerge = async () => {
    if (!mergeSourceA || !mergeSourceB) {
      message.warning('请选择两个源 LoRA');
      return;
    }
    if (!mergeOutputName.trim()) {
      message.warning('请填写输出名称');
      return;
    }
    setMergeJob({ job_id: '', status: 'running', output_file: null, error: null });
    try {
      const { data } = await api.post<MergeJob>('/train/merge-lora', {
        source_a: mergeSourceA,
        source_b: mergeSourceB,
        ratio_a: mergeRatioA,
        ratio_b: mergeRatioB,
        output_name: mergeOutputName.trim(),
        overwrite: mergeOverwrite,
      });
      setMergeJob({ ...data, status: 'running' });
      const poll = async (jobId: string) => {
        while (true) {
          await new Promise((resolve) => setTimeout(resolve, 1500));
          const res = await api.get<MergeJob>(`/train/merge/${jobId}`);
          setMergeJob(res.data);
          if (res.data.status !== 'running') {
            if (res.data.status === 'done') {
              drawStore.lorasVersion += 1;
              loadLoras();
            }
            break;
          }
        }
      };
      void poll(data.job_id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '合并启动失败');
      setMergeJob(null);
    }
  };

  const handleStopTraining = async () => {
    if (!trainJobId) return;
    try {
      await api.post('/train/training/stop', { job_id: trainJobId });
    } catch {
      message.error('停止失败');
    }
  };

  const handleResumeTraining = async () => {
    if (!trainJobId || resuming) return;
    setResuming(true);
    try {
      const { data } = await api.post<{ job_id: string; status: string; resume_state: string }>(
        `/train/training/${trainJobId}/resume`,
      );
      setTrainJobId(data.job_id);
      setTrainJob({
        job_id: data.job_id,
        output_name: trainJob?.output_name,
        status: 'running',
        log: '',
        error: null,
        converting: false,
        stalled: false,
        resume_available: false,
      });
      message.success('已从最近检查点续训；旧进程已停止');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '续训失败');
    } finally {
      setResuming(false);
    }
  };

  const handleCopy = async (name: string) => {
    setCopying(name);
    try {
      const { data } = await api.post<{ ok: boolean; filename: string }>('/train/copy-lora', { filename: name });
      drawStore.lorasVersion += 1;
      message.success(`已复制 ${data.filename}`);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '复制失败');
    } finally {
      setCopying('');
    }
  };

  const handleConvert = async (name: string) => {
    setCopying(name);
    try {
      const { data } = await api.post<{ ok: boolean; filename: string }>('/train/convert-lora', { filename: name });
      message.success(`已转换：${data.filename}`);
      setHighlightName(data.filename);
      loadOutputs();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '转换失败');
    } finally {
      setCopying('');
    }
  };

  const handleDeleteOutput = async (name: string) => {
    try {
      await api.delete(`/train/outputs/${encodeURIComponent(name)}`);
      message.success(`已删除 ${name}`);
      loadOutputs();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '删除失败');
    }
  };

  const handleDeleteLora = async (name: string) => {
    try {
      await api.delete(`/loras/${encodeURIComponent(name)}`);
      drawStore.lorasVersion += 1;
      message.success(`已删除 ${name}`);
      loadLoras();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '删除失败');
    }
  };

  const handleToggleProtect = async (item: LoraItem) => {
    try {
      await api.post(`/loras/${encodeURIComponent(item.name)}/${item.protected ? 'unprotect' : 'protect'}`);
      loadLoras();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '操作失败');
    }
  };

  const openCompare = () => {
    setCompareJob((current) => current ?? loadCompareLast());
    setComparePreviewIndex(0);
    setCompareOpen(true);
  };

  const toggleOutputFavorite = (name: string) => {
    setOutputFavorites((current) => toggleFavoriteName(current, name));
  };

  const toggleCompareLora = (name: string, checked: boolean) => {
    setCompareLoras((current) =>
      checked
        ? current.includes(name)
          ? current
          : [...current, name]
        : current.filter((item) => item !== name),
    );
  };

  const loadRecentCompare = (combo: string[]) => {
    const available = new Set(drawingLoras.map((item) => item.name));
    const next = combo.filter((name) => available.has(name));
    if (next.length === 0) {
      message.warning('这组最近搭配里的 LoRA 当前不可用');
      return;
    }
    setCompareLoras(next);
  };

  const handleStartCompare = async () => {
    if (!comparePrompt.trim()) {
      message.warning('请填写测试提示词');
      return;
    }
    if (compareLoras.length === 0) {
      message.warning('请选择要对比的 LoRA');
      return;
    }
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    setRecentCompareCombos((current) => addRecentCompareCombo(current, compareLoras));
    setCompareStarting(true);
    setComparePreviewIndex(0);
    setCompareJob({ job_id: '', status: 'running', total: compareLoras.length, done: 0, results: [] });
    try {
      const { data } = await api.post<CompareJob>('/train/compare-generate', {
        prompt: comparePrompt,
        negative_prompt: compareNegative,
        width: compareWidth,
        height: compareHeight,
        steps: compareSteps,
        cfg: compareCfg,
        seed: compareSeed ? Number(compareSeed) : undefined,
        loras: compareLoras,
        combo_loras: compareComboLoras,
        combo_strengths: compareComboStrengths,
        skip_turbo_duplicate: skipTurboDuplicate,
      });
    setCompareJob({ ...data, status: 'running', total: compareLoras.length, done: 0, results: [] });
    clearCompareLast();
    saveCompareTask(data.job_id);
      const poll = async (jobId: string) => {
        while (true) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
          const res = await api.get<CompareJob>(`/train/compare/${jobId}`);
          setCompareJob(res.data);
          if (res.data.status !== 'running') {
            saveCompareLast(res.data);
            clearCompareTask();
            break;
          }
        }
      };
      void poll(data.job_id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '对比出图启动失败');
      setCompareJob(null);
    } finally {
      setCompareStarting(false);
    }
  };

  const handleStopCompare = async () => {
    if (!compareJob?.job_id) return;
    try {
      await api.post(`/train/compare/${compareJob.job_id}/stop`);
    } catch {
      message.error('停止失败');
    }
  };

  const captionRunning = job?.status === 'running';
  const captionPercent = job && job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
  const trainRunning = trainJob?.status === 'running';
  const busy = copying !== '';
  const renderOutputRow = (item: TrainingOutput) => {
    const favorite = outputFavorites.includes(item.name);
    return (
      <div
        key={item.name}
        className={`train-output-row${highlightName === item.name ? ' active' : ''}`}
        ref={(element) => {
          highlightRef.current[item.name] = element;
        }}
      >
        <div className="train-output-name">
          <Tooltip title={favorite ? '取消收藏' : '收藏此产物'}>
            <Button
              type="text"
              size="small"
              className={`train-output-favorite${favorite ? ' is-favorite' : ''}`}
              aria-label={`${favorite ? '取消收藏' : '收藏'} ${item.name}`}
              icon={favorite ? <StarFilled /> : <StarOutlined />}
              onClick={() => toggleOutputFavorite(item.name)}
            />
          </Tooltip>
          <Tag color={item.name.endsWith('_comfy.safetensors') ? 'green' : 'orange'}>
            {item.name.endsWith('_comfy.safetensors') ? '可直接复制' : '未转换'}
          </Tag>
          <span>
            {item.name}（{item.size_mb}MB）
          </span>
        </div>
        <Space className="train-output-actions">
          {!item.name.endsWith('_comfy.safetensors') ? (
            <Button
              size="small"
              loading={copying === item.name}
              disabled={busy && copying !== item.name}
              onClick={() => void handleConvert(item.name)}
            >
              转换格式
            </Button>
          ) : null}
          <Button
            size="small"
            type="primary"
            loading={copying === item.name}
            disabled={busy && copying !== item.name}
            onClick={() => void handleCopy(item.name)}
          >
            复制到 LoRA 目录
          </Button>
          <Popconfirm title={`确认删除 ${item.name}？`} onConfirm={() => void handleDeleteOutput(item.name)}>
            <Button size="small" danger disabled={busy && copying !== item.name}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      </div>
    );
  };

  const reviewColumns: ColumnsType<DatasetReviewResult> = [
    {
      title: '缩略图',
      dataIndex: 'filename',
      key: 'thumb',
      width: 72,
      render: (filename: string) => (
        <Image
          src={`/api/train/dataset/image/${encodeURIComponent(filename)}`}
          width={48}
          height={48}
          style={{ objectFit: 'cover', borderRadius: 4 }}
        />
      ),
    },
    { title: '文件名', dataIndex: 'filename', key: 'filename', ellipsis: true },
    {
      title: 'AI 判断问题',
      dataIndex: 'issues',
      key: 'issues',
      render: (issues: string[]) => (issues && issues.length > 0 ? issues.join('；') : '无明显问题'),
    },
    {
      title: '状态',
      dataIndex: 'ok',
      key: 'ok',
      width: 100,
      render: (ok: boolean) => <Tag color={ok ? 'green' : 'red'}>{ok ? '通过' : '明显崩坏'}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_, record) => (
        <Space>
          <Popconfirm title={`确认将 ${record.filename} 移出数据集？`} onConfirm={() => void handleExclude(record.filename)}>
            <Button size="small">移出</Button>
          </Popconfirm>
          <Popconfirm
            title={`确认永久删除 ${record.filename}？`}
            description="会同时删除同名 .txt 标签，不可恢复。"
            onConfirm={() => void handleDeleteReview(record.filename)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const signatureColumns: ColumnsType<{ filename: string; caption_name: string; matched: string[] }> = [
    {
      title: '缩略图',
      dataIndex: 'filename',
      key: 'thumb',
      width: 72,
      render: (filename: string) => (
        <Image
          src={`/api/train/dataset/image/${encodeURIComponent(filename)}`}
          width={48}
          height={48}
          style={{ objectFit: 'cover', borderRadius: 4 }}
        />
      ),
    },
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      ellipsis: true,
      render: (value: string) => <Tooltip title={value}>{value}</Tooltip>,
    },
    {
      title: '标签文件',
      dataIndex: 'caption_name',
      key: 'caption_name',
      ellipsis: true,
      render: (value: string) => <Tooltip title={value}>{value}</Tooltip>,
    },
    {
      title: '命中关键词',
      dataIndex: 'matched',
      key: 'matched',
      render: (matched: string[]) => (
        <Space size={4} wrap>
          {matched.map((keyword) => (
            <Tag key={keyword} color="orange">
              {keyword}
            </Tag>
          ))}
        </Space>
      ),
    },
  ];

  return (
    <div className="train-layout">
      <div className="panel-box train-box">
        <div className="train-stats">
          <Tag>图片 {info?.image_count ?? 0}</Tag>
          <Tag color="green">已有标签 {info?.caption_count ?? 0}</Tag>
          <Tag color={info && info.missing_count > 0 ? 'orange' : 'default'}>缺标签 {info?.missing_count ?? 0}</Tag>
          <Button icon={<FolderOpenOutlined />} onClick={handleOpen}>
            打开本地数据集
          </Button>
          <Button icon={<ExperimentOutlined />} loading={checkLoading} onClick={() => void handleCheck()}>
            数据集体检
          </Button>
          <Button icon={<ExperimentOutlined />} loading={reviewJob?.status === 'running'} onClick={() => void handleStartReview()}>
            AI 审查
          </Button>
          <Tooltip title="批量替换所有标签文件中的指定标签；可先预览命中文件，执行前会自动备份原标签文件。">
            <Button icon={<EditOutlined />} onClick={() => { setTagFrom(''); setTagTo(''); setTagPreview(null); setTagEditOpen(true); }}>
              批量编辑标签
            </Button>
          </Tooltip>
          <Tooltip title="扫描数据集中可能包含签名、水印、文字 Logo 的图片标签。">
            <Button icon={<SearchOutlined />} loading={signatureLoading} onClick={() => void handleSignatureScan()}>
              签名扫描
            </Button>
          </Tooltip>
        </div>
        {reviewJob && reviewJob.results.length > 0 ? (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Space wrap>
              <Segmented
                value={reviewFilter}
                options={[
                  { label: '全部', value: 'all' },
                  { label: '只看问题图', value: 'broken' },
                ]}
                onChange={(value) => setReviewFilter(value as 'all' | 'broken')}
              />
              <Tag color="red">问题图 {reviewJob.results.filter((item) => !item.ok).length} 张</Tag>
              <Button
                size="small"
                onClick={() =>
                  setSelectedReviewFiles(
                    (reviewJob.results || []).filter((item) => !item.ok).map((item) => item.filename),
                  )
                }
              >
                全选问题图
              </Button>
              <Popconfirm
                title={`确认将选中的 ${selectedReviewFiles.length} 张图片移出数据集？`}
                onConfirm={() => void handleExcludeMany(selectedReviewFiles)}
              >
                <Button size="small" type="primary" disabled={selectedReviewFiles.length === 0}>
                  批量移出
                </Button>
              </Popconfirm>
              <Tag>已选 {selectedReviewFiles.length} 张</Tag>
            </Space>
            <Table
              rowKey="filename"
              size="small"
              columns={reviewColumns}
              dataSource={reviewFilter === 'broken' ? reviewJob.results.filter((item) => !item.ok) : reviewJob.results}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              rowSelection={{
                selectedRowKeys: selectedReviewFiles,
                onChange: (keys) => setSelectedReviewFiles(keys.map(String)),
              }}
            />
          </div>
        ) : reviewJob?.status === 'running' ? (
          <div className="train-status-text" style={{ marginTop: 8 }}>
            审查中 {reviewJob.done}/{reviewJob.total}…
          </div>
        ) : null}

        <div className="train-actions">
          <Tooltip title="打标模型：WD14 标签标准、速度快；qwen2.5vl 可输出英文标签或中文描述。">
            <Segmented
              value={mode}
              options={[
                { label: 'WD14（默认）', value: 'wd14' },
                { label: 'qwen2.5vl', value: 'qwen' },
              ]}
              onChange={(value) => setMode(value as 'wd14' | 'qwen')}
            />
          </Tooltip>
          {mode === 'wd14' ? (
            <Space wrap>
              <span>
                阈值{' '}
                <Tooltip title="置信度阈值：只有置信度高于该值的标签才会写入 .txt。调低会得到更多标签但准确率下降，调高则标签更少但更精准。">
                  <InfoCircleOutlined style={{ color: '#6b7280' }} />
                </Tooltip>
              </span>
              <InputNumber
                min={trainConfig.caption_threshold_min}
                max={trainConfig.caption_threshold_max}
                step={trainConfig.caption_threshold_step}
                value={threshold}
                onChange={(value) => setThreshold(value ?? trainConfig.default_caption_threshold)}
              />
              <span>
                Batch{' '}
                <Tooltip title="每次同时送入模型的图片数量：显存充足时可调大加快打标，显存不足或报 OOM 时调小。">
                  <InfoCircleOutlined style={{ color: '#6b7280' }} />
                </Tooltip>
              </span>
              <InputNumber
                min={trainConfig.caption_batch_min}
                max={trainConfig.caption_batch_max}
                value={captionBatchSize}
                onChange={(value) => setCaptionBatchSize(value ?? trainConfig.default_caption_batch_size)}
              />
              <Tooltip title="把 long_hair 转为 long hair，更符合 Danbooru 标签习惯。">
                <Checkbox checked={removeUnderscore} onChange={(e) => setRemoveUnderscore(e.target.checked)}>
                  移除下划线
                </Checkbox>
              </Tooltip>
            </Space>
          ) : (
            <Tooltip title="选择 qwen2.5vl 打标输出：英文 Danbooru 标签或中文自然语言描述。">
              <Radio.Group value={language} onChange={(e) => setLanguage(e.target.value)} optionType="button">
                <Radio.Button value="tags">英文标签</Radio.Button>
                <Radio.Button value="description">中文描述</Radio.Button>
              </Radio.Group>
            </Tooltip>
          )}
          <Tooltip title="已存在同名 .txt 标签文件时不覆盖。">
            <Checkbox checked={skipExisting} onChange={(e) => setSkipExisting(e.target.checked)}>
              跳过已有标签
            </Checkbox>
          </Tooltip>
          <Button type="primary" icon={<PlayCircleOutlined />} loading={starting} disabled={captionRunning} onClick={() => void handleStartCaption()}>
            开始打标
          </Button>
          <Button danger icon={<StopOutlined />} disabled={!captionRunning} onClick={() => void handleStopCaption()}>
            停止
          </Button>
        </div>

        {job ? (
          <div className="train-progress">
            <Progress
              percent={captionPercent}
              status={captionRunning ? 'active' : job.status === 'error' ? 'exception' : job.status === 'stopped' ? 'normal' : 'success'}
            />
            <div className="train-status-text">
              {job.last_file ||
                (captionRunning ? '处理中...' : job.status === 'done' ? '已完成' : job.status === 'error' ? `失败：${job.error || ''}` : '已停止')}
            </div>
          </div>
        ) : null}

        {job?.log ? <pre className="train-log">{job.log}</pre> : null}
      </div>

      <div className="panel-box train-box">
        <div className="train-section-title">训练配置</div>
        <div className="train-config">
          <div className="train-field">
            <span className="setting-label">
              底模{' '}
              <Tooltip title="训练仅支持 net. 前缀格式：chosenIrisesMix_v20Anima_net 是转换版（可训练），原版 chosenIrisesMix_v20Anima 只能出图；miaomiaoHarem_anima16 也可直接训练。建议选择你出图常用的模型。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <Select
              style={{ width: '100%' }}
              value={dit}
              options={models.map((item) => ({ label: `${item.name} (${item.size_mb}MB)`, value: item.name }))}
              onChange={setDit}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">
              LoRA 名称{' '}
              <Tooltip title="训练产物的文件名，建议使用英文小写和下划线，例如 my_character_lora。会保存到 output 目录；与已有产物同名会在训练结束时覆盖它们。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <Input value={outputName} onChange={(e) => setOutputName(e.target.value)} placeholder="my_lora" />
            {nameConflicts.length > 0 ? (
              <div className="train-name-warning">
                <span>
                  输出目录已有同名产物 {nameConflicts.length} 个，继续训练会覆盖：
                  {nameConflicts.slice(0, 2).join('、')}
                  {nameConflicts.length > 2 ? ' 等' : ''}
                </span>
                {suggestedName ? (
                  <Button size="small" onClick={() => setOutputName(suggestedName)}>
                    改用 {suggestedName}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="train-field">
            <span className="setting-label">配方</span>
            <Select
              style={{ width: '100%' }}
              value={presetKind}
              disabled={trainRunning}
              onChange={(value) => applyPreset(value as 'character' | 'style' | 'custom')}
              options={[
                { label: '角色 LoRA（你惯用的参数）', value: 'character' },
                { label: '画风 LoRA（打乱标签、轮数更多）', value: 'style' },
                { label: '自定义（已手动调整）', value: 'custom' },
              ]}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">LoRA 档位（dim / alpha）</span>
            <Select
              style={{ width: '100%' }}
              value={networkDim}
              options={DIM_OPTIONS}
              onChange={(value) => {
                setNetworkDim(value);
                setNetworkAlpha(Math.round(value / 2));
              }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">学习率档位</span>
            <Segmented
              value={lrTier}
              onChange={(value) => applyLrTier(String(value))}
              options={[
                { label: '角色 0.0001', value: 'character' },
                { label: '画风 0.00005', value: 'style' },
                { label: '自定义', value: 'custom' },
              ]}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">训练轮数</span>
            <InputNumber
              min={trainConfig.epochs_min}
              max={trainConfig.epochs_max}
              value={epochs}
              onChange={(value) => setEpochs(value ?? trainConfig.default_epochs)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">重复次数</span>
            <InputNumber
              min={trainConfig.repeats_min}
              max={trainConfig.repeats_max}
              value={repeats}
              onChange={(value) => setRepeats(value ?? trainConfig.default_repeats)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">本次训练</span>
            <span className="train-status-text">
              图片 {datasetImageCount} 张 · 每轮约 {stepsPerEpoch} 步 · 合计约 {estimatedSteps} 步（估算 {estimatedMinutes} 分钟）
            </span>
          </div>
        </div>
        <Collapse ghost className="train-advanced" defaultActiveKey={[]}>
          <Collapse.Panel header={advancedLabel} key="advanced">
            <div className="train-config">
          <div className="train-field">
            <Tooltip title="训练完成后自动把产物转换为 ComfyUI 可直接加载的 _comfy 格式。">
              <span className="setting-label">自动转换</span>
            </Tooltip>
            <Checkbox checked={autoConvert} onChange={(e) => setAutoConvert(e.target.checked)}>
              训练完成后自动转换格式
            </Checkbox>
          </div>
          <div className="train-field">
            <span className="setting-label">
              分辨率{' '}
              <Tooltip title="训练图片的目标分辨率。推荐 1024；显存紧张时可降至 768 或 896。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <InputNumber
              min={trainConfig.resolution_min}
              max={trainConfig.resolution_max}
              step={trainConfig.resolution_step}
              value={resolution}
              onChange={(value) => setResolution(value ?? trainConfig.default_resolution)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">
              Batch{' '}
              <Tooltip title="训练 batch size。4060 Ti 16GB 建议 1；显存充足且开启缓存后可试 2。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <InputNumber
              min={trainConfig.batch_size_min}
              max={trainConfig.batch_size_max}
              value={trainBatchSize}
              onChange={(value) => setTrainBatchSize(value ?? trainConfig.default_batch_size)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">
              保存间隔{' '}
              <Tooltip title="每 N 轮保存一次检查点。推荐 1，方便中途回退到更好的轮次。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <InputNumber
              min={trainConfig.save_every_min}
              max={trainConfig.save_every_max}
              value={saveEvery}
              onChange={(value) => setSaveEvery(value ?? trainConfig.default_save_every)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">
              最大步数（0 不限）{' '}
              <Tooltip title="训练步数上限。推荐保持 0（不限，按轮数训练）；只有想精确控制步数时才设置具体值。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <InputNumber
              min={trainConfig.max_steps_min}
              max={trainConfig.max_steps_max}
              value={maxSteps}
              onChange={(value) => setMaxSteps(value ?? trainConfig.default_max_steps)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">优化器</span>
            <Select value={optimizerType} options={optimizerOptions} onChange={setOptimizerType} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">学习率调度器</span>
            <Select value={lrScheduler} options={lrSchedulerOptions} onChange={setLrScheduler} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">混合精度</span>
            <Select value={mixedPrecision} options={precisionOptions} onChange={setMixedPrecision} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">梯度累积</span>
            <InputNumber min={1} max={64} value={gradientAccumulation} onChange={(value) => setGradientAccumulation(value ?? 1)} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">Warmup Steps</span>
            <InputNumber min={0} max={100000} value={warmupSteps} onChange={(value) => setWarmupSteps(value ?? 0)} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">Discrete Flow Shift</span>
            <InputNumber min={0.1} max={10} step={0.1} value={discreteFlowShift} formatter={(value) => formatPlainDecimal(value, 4)} parser={parsePlainDecimal} onChange={(value) => setDiscreteFlowShift(Number(value ?? 1))} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">Keep Tokens</span>
            <InputNumber min={0} max={100} value={keepTokens} onChange={(value) => setKeepTokens(value ?? 1)} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">Bucket 最小分辨率</span>
            <InputNumber min={256} max={4096} step={64} value={bucketMinReso} onChange={(value) => setBucketMinReso(value ?? 512)} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">Bucket 最大分辨率</span>
            <InputNumber min={256} max={4096} step={64} value={bucketMaxReso} onChange={(value) => setBucketMaxReso(value ?? 1536)} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">Bucket 步长</span>
            <InputNumber min={8} max={256} step={8} value={bucketResoSteps} onChange={(value) => setBucketResoSteps(value ?? 64)} style={{ width: '100%' }} />
          </div>
          <div className="train-field">
            <span className="setting-label">训练选项</span>
            <Space wrap>
              <Checkbox checked={shuffleCaption} onChange={(e) => setShuffleCaption(e.target.checked)}>Shuffle Caption</Checkbox>
              <Checkbox checked={gradientCheckpointing} onChange={(e) => setGradientCheckpointing(e.target.checked)}>梯度检查点</Checkbox>
              <Checkbox checked={cacheLatents} onChange={(e) => { setCacheLatents(e.target.checked); if (!e.target.checked) setCacheLatentsToDisk(false); }}>缓存 Latents</Checkbox>
              <Checkbox checked={saveState} onChange={(e) => setSaveState(e.target.checked)}>保存训练状态（可凭 *-state 精确续训）</Checkbox>
              <Checkbox checked={cacheLatentsToDisk} disabled={!cacheLatents} onChange={(e) => setCacheLatentsToDisk(e.target.checked)}>缓存到磁盘</Checkbox>
            </Space>
          </div>
            </div>
          </Collapse.Panel>
        </Collapse>
        <div className="train-actions">
          <Button icon={<ExperimentOutlined />} disabled={trainRunning} onClick={applyCharacterLoraPreset}>
            应用角色 LoRA 推荐参数
          </Button>
          <Tooltip title="降秩、降低学习率、增加重复和轮次，并打乱内容标签，减少画风与角色内容绑定。">
            <Button icon={<ExperimentOutlined />} disabled={trainRunning} onClick={applyStyleLoraPreset}>
              应用画风 LoRA 推荐参数
            </Button>
          </Tooltip>
          <Button type="primary" icon={<PlayCircleOutlined />} loading={trainStarting} disabled={trainRunning} onClick={() => void handleStartTraining()}>
            开始训练
          </Button>
          <Button danger icon={<StopOutlined />} disabled={!trainRunning} onClick={() => void handleStopTraining()}>
            停止训练
          </Button>
          {trainJob ? (
            <Tag color={trainRunning ? 'processing' : trainJob.status === 'error' ? 'red' : trainJob.status === 'done' ? 'green' : 'default'}>
              {trainRunning ? '训练中' : trainJob.status === 'done' ? '已完成' : trainJob.status === 'error' ? '失败' : '已停止'}
            </Tag>
          ) : null}
          {trainJob?.resume_available && (trainJob.stalled || trainJob.status === 'error' || trainJob.status === 'stopped') ? (
            <Button size="small" danger loading={resuming} onClick={() => void handleResumeTraining()}>
              从最近检查点续训
            </Button>
          ) : null}
          {trainJob?.duration_seconds ? <span className="train-status-text">耗时 {formatDuration(trainJob.duration_seconds)}</span> : null}
          {trainJob?.steps_done != null ? (
            <span className="train-status-text">
              步数 {trainJob.steps_done}/{trainJob.steps_total}
            </span>
          ) : null}
        </div>
        {trainJob?.loss_history && trainJob.loss_history.length > 1 ? (
          <div className="train-loss">
            <div className="train-stats">
              <Tag>当前 Loss {trainJob.latest_loss?.toFixed(4)}</Tag>
              <Tag color="green">最低 Loss {trainJob.min_loss?.toFixed(4)} @ 步 {trainJob.best_step}</Tag>
              {trainRunning && typeof trainJob.log_age_seconds === 'number' ? (
                <Tooltip title="日志文件最后一次写入的时间。正常情况下每约 4 秒会有一行进度；超过 5 分钟没有新写入通常表示训练进程卡死，可以直接点右侧按钮从最近检查点续训。">
                  <Tag color={trainJob.stalled || trainJob.log_age_seconds > 300 ? 'red' : 'green'}>
                    {trainJob.stalled || trainJob.log_age_seconds > 300
                      ? `可能已卡死：${Math.round(trainJob.log_age_seconds / 60)} 分钟没有新进度`
                      : `进度正常（${Math.round(trainJob.log_age_seconds)} 秒前更新）`}
                  </Tag>
                </Tooltip>
              ) : null}
            </div>
            <Line data={trainJob.loss_history} xField="step" yField="loss" height={220} point={{ size: 2 }} />
          </div>
        ) : null}
        {trainJob?.error ? <div className="train-status-text">失败：{trainJob.error}</div> : null}
        {trainJob?.converting ? (
          <div className="train-status-text">
            <Tag color="blue">自动转换格式中…</Tag>
          </div>
        ) : null}
        {trainJob?.convert_error ? <div className="train-status-text">自动转换失败：{trainJob.convert_error}</div> : null}
        {trainJob?.log ? <pre className="train-log">{trainJob.log}</pre> : null}
      </div>

      <div className="panel-box train-box">
        <div className="train-stats">
          <Tag>训练产物</Tag>
          <Segmented
            value={outputFilter}
            options={[
              { label: '全部', value: 'all' },
              { label: '转换前', value: 'raw' },
              { label: '转换后', value: 'comfy' },
            ]}
            onChange={(value) => {
              setOutputFilter(value as TrainingOutputKind);
              setOutputPage(1);
              setExpandedOutputFamilies([]);
            }}
          />
          <Input
            allowClear
            className="train-output-search"
            prefix={<SearchOutlined />}
            placeholder="搜索产物或名称族"
            aria-label="搜索训练产物"
            value={outputSearch}
            onChange={(event) => {
              setOutputSearch(event.target.value);
              setOutputPage(1);
              setExpandedOutputFamilies([]);
            }}
          />
          <Button size="small" onClick={loadOutputs}>
            刷新
          </Button>
          <Button size="small" onClick={openCompare}>
            一键对比出图
          </Button>
        </div>
        {outputs.length === 0 ? (
          <div className="train-status-text">暂无训练产物</div>
        ) : outputGroups.length === 0 ? (
          <div className="train-status-text">没有符合搜索和筛选条件的产物</div>
        ) : (
          <>
            <div className="train-output-summary">
              <span>
                {outputGroups.length} 个名称族 · {filteredOutputFileCount} 个匹配文件
              </span>
              {outputFavorites.length > 0 ? <Tag color="gold">已收藏 {outputFavorites.length}</Tag> : null}
            </div>
            <Collapse
              ghost
              className="train-output-family-collapse"
              activeKey={expandedOutputFamilies}
              onChange={(keys) =>
                setExpandedOutputFamilies(Array.isArray(keys) ? keys : [keys])
              }
              items={visibleOutputGroups.map((group) => ({
                key: group.key,
                label: (
                  <div className="train-output-family-title">
                    <strong>{group.label}</strong>
                    <Space size={4} wrap>
                      <Tag>{group.items.length} 个文件</Tag>
                      {group.favorite ? <Tag color="gold">收藏</Tag> : null}
                    </Space>
                  </div>
                ),
                children: (
                  <div className="train-outputs">
                    {group.items.map(renderOutputRow)}
                  </div>
                ),
              }))}
            />
            {outputPageCount > 1 ? (
              <div className="train-output-pagination">
                <Pagination
                  size="small"
                  current={currentOutputPage}
                  pageSize={TRAIN_OUTPUT_PAGE_SIZE}
                  total={outputGroups.length}
                  showSizeChanger={false}
                  showTotal={(total) => `每页最多 ${TRAIN_OUTPUT_PAGE_SIZE} 个名称族，共 ${total} 个`}
                  onChange={(page) => {
                    setOutputPage(page);
                    setExpandedOutputFamilies([]);
                  }}
                />
              </div>
            ) : null}
          </>
        )}
      </div>

      <div className="panel-box train-box">
        <div className="train-section-title">LoRA 合并</div>
        <div className="train-config">
          <div className="train-field">
            <Tooltip title="第一个源 LoRA（如 anima-turbo-lora-v0.2）。">
              <span className="setting-label">源 A</span>
            </Tooltip>
            <Select
              style={{ width: '100%' }}
              value={mergeSourceA || undefined}
              options={drawingLoras.map((item) => ({ label: item.name, value: item.name }))}
              onChange={setMergeSourceA}
            />
          </div>
          <div className="train-field">
            <Tooltip title="第二个源 LoRA（如风格/角色 LoRA）。">
              <span className="setting-label">源 B</span>
            </Tooltip>
            <Select
              style={{ width: '100%' }}
              value={mergeSourceB || undefined}
              options={drawingLoras.map((item) => ({ label: item.name, value: item.name }))}
              onChange={setMergeSourceB}
            />
          </div>
          <div className="train-field">
            <Tooltip title="源 A 的有效强度比例，默认 1.0。">
              <span className="setting-label">比例 A</span>
            </Tooltip>
            <InputNumber
              min={trainConfig.merge_ratio_min}
              max={trainConfig.merge_ratio_max}
              step={trainConfig.merge_ratio_step}
              value={mergeRatioA}
              onChange={(value) => setMergeRatioA(value ?? trainConfig.merge_ratio_default)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <Tooltip title="源 B 的有效强度比例，默认 1.0。">
              <span className="setting-label">比例 B</span>
            </Tooltip>
            <InputNumber
              min={trainConfig.merge_ratio_min}
              max={trainConfig.merge_ratio_max}
              step={trainConfig.merge_ratio_step}
              value={mergeRatioB}
              onChange={(value) => setMergeRatioB(value ?? trainConfig.merge_ratio_default)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <Tooltip title="合并产物文件名，自动补 .safetensors，写入 ComfyUI LoRA 目录。">
              <span className="setting-label">输出名称</span>
            </Tooltip>
            <Input value={mergeOutputName} onChange={(e) => setMergeOutputName(e.target.value)} placeholder="merged_lora" />
          </div>
          <div className="train-field">
            <Tooltip title="输出文件已存在时是否允许覆盖。">
              <span className="setting-label">覆盖</span>
            </Tooltip>
            <Checkbox checked={mergeOverwrite} onChange={(e) => setMergeOverwrite(e.target.checked)}>
              允许覆盖同名文件
            </Checkbox>
          </div>
        </div>
        <div className="train-actions" style={{ marginTop: 8 }}>
          <Button type="primary" icon={<PlayCircleOutlined />} loading={mergeJob?.status === 'running'} onClick={() => void handleStartMerge()}>
            一键合并
          </Button>
          {mergeJob?.status === 'running' ? <Tag color="blue">合并中…</Tag> : null}
          {mergeJob?.status === 'done' && mergeJob.output_file ? <Tag color="green">已生成 {mergeJob.output_file}</Tag> : null}
          {mergeJob?.status === 'error' ? <Tag color="red">失败：{mergeJob.error}</Tag> : null}
        </div>
      </div>

      <div className="panel-box train-box">
        <div className="train-stats">
          <Tag>LoRA 目录</Tag>
          <Button size="small" icon={<ReloadOutlined />} loading={lorasLoading} onClick={loadLoras}>
            刷新
          </Button>
        </div>
        {lorasList.length === 0 ? (
          <div className="train-status-text">暂无 LoRA 文件</div>
        ) : (
          <div className="train-outputs">
            {lorasList.map((item) => (
              <div key={item.name} className="train-output-row">
                <div className="train-output-name">
                  {item.protected ? <Tag color="blue">已保护</Tag> : null}
                  <Tag color={item.usage_count && item.usage_count >= 50 ? 'orange' : 'default'}>
                    使用 {item.usage_count ?? 0} 次
                  </Tag>
                  {item.compatible === false ? (
                    <Tag color="purple" title={item.incompatible_reason || '视频 LoRA'}>
                      视频 LoRA
                    </Tag>
                  ) : null}
                  <span>
                    {item.name}（{item.size_mb}MB）
                  </span>
                </div>
                <Space className="train-output-actions">
                  <Button size="small" onClick={() => void handleToggleProtect(item)}>
                    {item.protected ? '取消保护' : '保护'}
                  </Button>
                  <Popconfirm
                    title={`确认删除 ${item.name}？${item.usage_count ? `（已使用 ${item.usage_count} 次）` : ''}`}
                    onConfirm={() => void handleDeleteLora(item.name)}
                  >
                    <Button size="small" danger disabled={item.protected}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              </div>
            ))}
          </div>
        )}
      </div>

      <Modal
        title="一键对比出图"
        open={compareOpen}
        onCancel={() => setCompareOpen(false)}
        footer={null}
        width={860}
      >
        <div className="train-config">
          <div className="train-field setting-wide">
            <span className="setting-label">测试提示词</span>
            <Input.TextArea rows={3} value={comparePrompt} onChange={(e) => setComparePrompt(e.target.value)} />
          </div>
          <div className="train-field setting-wide">
            <span className="setting-label">负面提示词</span>
            <Input.TextArea rows={2} value={compareNegative} onChange={(e) => setCompareNegative(e.target.value)} />
          </div>
          <div className="train-field">
            <span className="setting-label">宽</span>
            <InputNumber
              min={compareConfig.width_min}
              max={compareConfig.width_max}
              value={compareWidth}
              onChange={(value) => setCompareWidth(value ?? compareConfig.default_width)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">高</span>
            <InputNumber
              min={compareConfig.height_min}
              max={compareConfig.height_max}
              value={compareHeight}
              onChange={(value) => setCompareHeight(value ?? compareConfig.default_height)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">步数</span>
            <InputNumber
              min={compareConfig.steps_min}
              max={compareConfig.steps_max}
              value={compareSteps}
              onChange={(value) => setCompareSteps(value ?? compareConfig.default_steps)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">CFG</span>
            <InputNumber
              min={compareConfig.cfg_min}
              max={compareConfig.cfg_max}
              step={compareConfig.cfg_step}
              value={compareCfg}
              onChange={(value) => setCompareCfg(value ?? compareConfig.default_cfg)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="train-field">
            <span className="setting-label">Seed</span>
            <Input value={compareSeed} onChange={(e) => setCompareSeed(e.target.value)} placeholder="留空随机" />
          </div>
        </div>
        <div className="train-compare-heading">
          <div className="train-compare-heading-title">
            <span className="setting-label">选择对比 LoRA</span>
            <Tag color="blue">
              已选 {compareLoras.length}
            </Tag>
          </div>
          <Space size={6} wrap>
            <Input
              allowClear
              className="train-compare-search"
              prefix={<SearchOutlined />}
              placeholder="搜索名称或族"
              aria-label="搜索对比 LoRA"
              value={compareSearch}
              onChange={(event) => setCompareSearch(event.target.value)}
            />
            <Button
              size="small"
              disabled={compareLoras.length === 0 && compareComboLoras.length === 0}
              onClick={() => {
                setCompareLoras([]);
                setCompareComboLoras([]);
                setCompareComboStrengths({});
              }}
            >
              清空选择
            </Button>
          </Space>
        </div>
        {compareLoras.length > 0 ? (
          <div className="train-compare-selected" aria-label="已选对比 LoRA">
            {compareLoras.map((name) => (
              <Tag
                key={`selected-${name}`}
                color="blue"
                closable
                onClose={(event) => {
                  event.preventDefault();
                  toggleCompareLora(name, false);
                }}
              >
                {name}
              </Tag>
            ))}
          </div>
        ) : null}
        {recentCompareCombos.length > 0 ? (
          <div className="train-compare-recent">
            <span className="setting-label">最近组合</span>
            {recentCompareCombos.map((combo, index) => (
              <Tooltip key={`recent-${index}-${combo.join('|')}`} title={combo.join(' + ')}>
                <Button size="small" onClick={() => loadRecentCompare(combo)}>
                  组合 {index + 1} · {combo.length} 个
                </Button>
              </Tooltip>
            ))}
          </div>
        ) : null}
        {compareGroups.length === 0 ? (
          <div className="train-status-text">没有符合条件的 LoRA</div>
        ) : (
          <Collapse
            ghost
            className="train-compare-groups"
            activeKey={effectiveCompareFamilies}
            onChange={(keys) =>
              setExpandedCompareFamilies(Array.isArray(keys) ? keys : [keys])
            }
            items={compareGroups.map((group) => {
              const selectedInGroup = group.items.filter((item) =>
                compareLoras.includes(item.name),
              ).length;
              return {
                key: group.key,
                label: (
                  <div className="train-output-family-title">
                    <strong>{group.label}</strong>
                    <Space size={4} wrap>
                      <Tag>{group.items.length} 个</Tag>
                      {selectedInGroup > 0 ? <Tag color="blue">已选 {selectedInGroup}</Tag> : null}
                    </Space>
                  </div>
                ),
                children: (
                  <div className="train-compare-options">
                    {group.items.map((item) => (
                      <Checkbox
                        key={item.name}
                        aria-label={`对比 ${item.name}`}
                        checked={compareLoras.includes(item.name)}
                        onChange={(event) => toggleCompareLora(item.name, event.target.checked)}
                      >
                        <span className="train-compare-option-label">{item.name}</span>
                      </Checkbox>
                    ))}
                  </div>
                ),
              };
            })}
          />
        )}
        <div className="setting-label" style={{ marginTop: 10 }}>
          固定搭配 LoRA（每个对比结果额外叠加，不占对比产物数量）
        </div>
        <Select
          mode="multiple"
          allowClear
          showSearch
          optionFilterProp="label"
          className="train-compare-combo-select"
          placeholder="搜索并选择固定搭配 LoRA"
          maxTagCount="responsive"
          value={compareComboLoras}
          options={drawingLoras.map((item) => ({ label: item.name, value: item.name }))}
          onChange={(next) => {
            setCompareComboLoras(next);
            setCompareComboStrengths((current) => {
              const updated = { ...current };
              for (const name of next) {
                updated[name] ||= {
                  model: drawConfig.default_lora_strength_model,
                  clip: drawConfig.default_lora_strength_clip,
                };
              }
              return updated;
            });
          }}
        />
        {compareComboLoras.map((name) => (
          <div key={`strength-${name}`} className="train-output-row" style={{ marginTop: 6 }}>
            <span className="train-output-name" style={{ minWidth: 0 }}>
              {name}
            </span>
            <Space className="train-output-actions">
              <span>模型</span>
              <InputNumber
                min={drawConfig.lora_strength_min}
                max={drawConfig.lora_strength_max}
                step={drawConfig.lora_strength_step}
                value={
                  compareComboStrengths[name]?.model ?? drawConfig.default_lora_strength_model
                }
                onChange={(value) =>
                  setCompareComboStrengths({
                    ...compareComboStrengths,
                    [name]: {
                      model: value ?? drawConfig.default_lora_strength_model,
                      clip:
                        compareComboStrengths[name]?.clip ??
                        drawConfig.default_lora_strength_clip,
                    },
                  })
                }
              />
              <span>CLIP</span>
              <InputNumber
                min={drawConfig.lora_strength_min}
                max={drawConfig.lora_strength_max}
                step={drawConfig.lora_strength_step}
                value={
                  compareComboStrengths[name]?.clip ?? drawConfig.default_lora_strength_clip
                }
                onChange={(value) =>
                  setCompareComboStrengths({
                    ...compareComboStrengths,
                    [name]: {
                      model:
                        compareComboStrengths[name]?.model ??
                        drawConfig.default_lora_strength_model,
                      clip: value ?? drawConfig.default_lora_strength_clip,
                    },
                  })
                }
              />
            </Space>
          </div>
        ))}
        <Checkbox checked={skipTurboDuplicate} onChange={(e) => setSkipTurboDuplicate(e.target.checked)} style={{ marginTop: 6 }}>
          自动跳过含 turbo 的重复搭配
        </Checkbox>
        <div className="train-actions" style={{ marginTop: 8 }}>
          <Button type="primary" loading={compareStarting || compareJob?.status === 'running'} onClick={() => void handleStartCompare()}>
            开始对比
          </Button>
          {compareJob?.status === 'running' ? (
            <Button danger onClick={() => void handleStopCompare()}>
              停止
            </Button>
          ) : null}
          {compareJob && compareJob.status !== 'running' && compareJob.results.length > 0 ? (
            <Popconfirm
              title="确认清空上次对比结果？"
              onConfirm={() => {
                clearCompareLast();
                setCompareJob(null);
                setComparePreviewIndex(0);
              }}
            >
              <Button danger>清空结果</Button>
            </Popconfirm>
          ) : null}
          {compareJob ? (
            <Tag color={compareJob.status === 'running' ? 'blue' : compareJob.status === 'done' ? 'green' : 'red'}>
              进度 {compareJob.done}/{compareJob.total} · 用时 {compareElapsed}s
            </Tag>
          ) : null}
        </div>
        {compareJob && compareJob.results && compareJob.results.length > 0 ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
              <Button icon={<LeftOutlined />} disabled={comparePreviewIndex <= 0} onClick={() => setComparePreviewIndex((value) => Math.max(0, value - 1))} />
              <div style={{ flex: 1, minWidth: 0, background: '#fafafa', borderRadius: 8, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {compareJob.results[comparePreviewIndex]?.image_url ? (
                  <Image src={compareJob.results[comparePreviewIndex].image_url} style={{ maxWidth: '100%', maxHeight: 320, objectFit: 'contain' }} />
                ) : (
                  <div className="preview-empty">暂无预览</div>
                )}
                {compareJob.results[comparePreviewIndex] ? <CompareEllipsis text={compareJob.results[comparePreviewIndex].name} /> : null}
                {compareJob.results[comparePreviewIndex]?.combo && compareJob.results[comparePreviewIndex].combo.length > 0 ? (
                  <CompareEllipsis text={`搭配：${compareJob.results[comparePreviewIndex].combo.join(' + ')}`} color="#2563eb" />
                ) : null}
                {compareJob.results[comparePreviewIndex]?.seed ? <CompareEllipsis text={`seed ${compareJob.results[comparePreviewIndex].seed}`} /> : null}
              </div>
              <Button
                icon={<RightOutlined />}
                disabled={comparePreviewIndex >= compareJob.results.length - 1}
                onClick={() => setComparePreviewIndex((value) => Math.min(compareJob.results.length - 1, value + 1))}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10, marginTop: 10 }}>
              {compareJob.results.map((item, index) => (
                <div
                  key={`${item.name}-${index}`}
                  className="group-card compare-result-card"
                  style={{ display: 'flex', flexDirection: 'column', gap: 4, borderColor: index === comparePreviewIndex ? '#2563eb' : undefined }}
                >
                  <CompareEllipsis text={item.name} />
                  {item.combo && item.combo.length > 0 ? <CompareEllipsis text={`搭配：${item.combo.join(' + ')}`} color="#2563eb" /> : null}
                  {item.error ? (
                    <CompareEllipsis text={item.error} color="#dc2626" />
                  ) : item.image_url ? (
                    <div style={{ cursor: 'pointer' }} onClick={() => setComparePreviewIndex(index)}>
                      <Image src={item.image_url} width="100%" style={{ borderRadius: 6 }} preview={false} />
                    </div>
                  ) : null}
                  {item.seed ? <CompareEllipsis text={`seed ${item.seed}`} /> : null}
                </div>
              ))}
            </div>
          </>
        ) : null}
      </Modal>

      <Modal
        title="人工审核确认"
        open={reviewConfirmOpen}
        onOk={() => void handleStartTrainingConfirmed()}
        onCancel={() => setReviewConfirmOpen(false)}
        okText="已确认图片质量，开始训练"
      >
        <div className="prompt-set-detail">
          数据集包含从 AI 绘画导入的图片。请先确认这些图片无明显崩坏，再开始训练。
        </div>
      </Modal>

      <Modal
        title="LoRA 名称与已有产物重复"
        open={nameConflictOpen}
        onCancel={() => setNameConflictOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setNameConflictOpen(false)}>
            取消
          </Button>,
          suggestedName ? (
            <Button key="rename" type="primary" onClick={handleUseSuggestedName}>
              改用 {suggestedName}
            </Button>
          ) : null,
          <Button key="overwrite" danger onClick={() => void handleOverwriteOutputConfirmed()}>
            仍然覆盖并开始
          </Button>,
        ]}
      >
        <div className="prompt-set-detail">
          该名称在输出目录已有同名产物，训练结束时会覆盖它们，且覆盖后无法还原。
          {nameConflicts.length > 0 ? (
            <div className="train-name-warning-list">{nameConflicts.join('、')}</div>
          ) : null}
        </div>
      </Modal>

      <Modal
        title="训练数据集体检"
        open={checkOpen}
        onCancel={() => setCheckOpen(false)}
        footer={<Button onClick={() => setCheckOpen(false)}>关闭</Button>}
        width={720}
      >
        {checkData ? (
          <div className="prompt-set-detail">
            <div>
              <Tag>图片 {checkData.image_count}</Tag>
              <Tag color={checkData.missing_txt > 0 ? 'orange' : 'green'}>缺标签 {checkData.missing_txt}</Tag>
              <Tag>竖版 {checkData.portrait}</Tag>
              <Tag>横版 {checkData.landscape}</Tag>
              <Tag>方形 {checkData.square}</Tag>
            </div>
            {checkData.low_res.length > 0 ? (
              <div>
                <b>低清图（短边 &lt; 768）：</b>
                {checkData.low_res.map((item) => `${item.name} (${item.width}x${item.height})`).join('；')}
              </div>
            ) : null}
            {checkData.suspicious.length > 0 ? (
              <div>
                <b>可疑文件（psd/wip/progress）：</b>
                {checkData.suspicious.join('；')}
              </div>
            ) : null}
            {checkData.duplicates.length > 0 ? (
              <div>
                <b>重复组：</b>
                {checkData.duplicates.map((group) => group.join(' / ')).join('；')}
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        title="签名扫描结果"
        open={signatureOpen}
        onCancel={() => setSignatureOpen(false)}
        footer={<Button onClick={() => setSignatureOpen(false)}>关闭</Button>}
        width={760}
      >
        <Tag color={signatureItems.length > 0 ? 'orange' : 'green'}>命中 {signatureItems.length} 个文件</Tag>
        {signatureItems.length > 0 ? (
          <Table
            rowKey="filename"
            size="small"
            columns={signatureColumns}
            dataSource={signatureItems}
            pagination={{ pageSize: 10, showSizeChanger: false }}
          />
        ) : (
          <div className="preview-empty" style={{ marginTop: 8 }}>
            未发现疑似签名、水印或文字 Logo 的标签
          </div>
        )}
      </Modal>

      <Modal
        title="批量编辑数据集标签"
        open={tagEditOpen}
        onCancel={() => { setTagEditOpen(false); setTagPreview(null); setTagFrom(''); setTagTo(''); }}
        footer={[
          <Button key="preview" loading={tagPreviewing} onClick={() => void handleTagPreview()}>
            预览
          </Button>,
          <Popconfirm
            key="apply"
            title="确认执行替换？"
            description="执行前会自动备份原标签文件。"
            onConfirm={() => void handleTagApply()}
          >
            <Button
              type="primary"
              danger={!tagTo.trim()}
              loading={tagApplying}
              disabled={!tagPreview || tagPreview.dry_run !== true || tagPreview.affected_files === 0}
            >
              执行替换
            </Button>
          </Popconfirm>,
        ]}
        width={720}
      >
        <div className="train-config" style={{ gridTemplateColumns: '1fr' }}>
          <div className="train-field">
            <span className="setting-label">
              原标签{' '}
              <Tooltip title="要替换的标签，例如 white lace。会按逗号逐项精确匹配。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <Input
              value={tagFrom}
              onChange={(e) => { setTagFrom(e.target.value); setTagPreview(null); }}
              placeholder="例如 white lace"
              allowClear
            />
          </div>
          <div className="train-field">
            <span className="setting-label">
              替换为{' '}
              <Tooltip title="替换后的标签；留空表示删除该标签。">
                <InfoCircleOutlined style={{ color: '#6b7280' }} />
              </Tooltip>
            </span>
            <Input
              value={tagTo}
              onChange={(e) => { setTagTo(e.target.value); setTagPreview(null); }}
              placeholder="例如 black lace；留空则删除"
              allowClear
            />
          </div>
        </div>
        {tagPreview ? (
          <div className="prompt-set-detail" style={{ marginTop: 12 }}>
            <div>
              <Tag color={tagPreview.affected_files > 0 ? 'orange' : 'green'}>
                命中文件 {tagPreview.affected_files}/{tagPreview.total_files}
              </Tag>
              <Tag>替换处数 {tagPreview.affected_tags}</Tag>
              {tagPreview.backup_dir ? <Tag color="blue">备份 {tagPreview.backup_dir}</Tag> : null}
            </div>
            {tagPreview.files.length > 0 ? (
              <div className="train-outputs" style={{ marginTop: 8 }}>
                {tagPreview.files.slice(0, 50).map((item) => (
                  <div key={item.name} className="train-output-row">
                    <div className="train-output-name">
                      <CompareEllipsis text={`${item.name}（${item.count} 处）`} />
                    </div>
                  </div>
                ))}
                {tagPreview.files.length > 50 ? (
                  <div className="train-status-text">还有 {tagPreview.files.length - 50} 个文件未展示</div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
