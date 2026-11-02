// API 客户端与前后端交互的通用类型
import axios from 'axios';

// 后端统一走 /api，Vite 开发服务器代理到 127.0.0.1:8500
export const api = axios.create({
  baseURL: '/api',
  timeout: 600000,
});

const runtimeApi = axios.create({
  baseURL: '/api',
  timeout: 3000,
});

export type SizeTuple = [number, number];
export type VideoSizeTuple = SizeTuple;

export interface RuntimeConfig {
  backend: {
    host: string;
    port: number;
    api_base: string;
  };
  services: {
    ollama: { base_url: string };
    comfyui: { base_url: string };
  };
  draw: {
    default_model: string;
    default_prompt: string;
    default_negative_prompt: string;
    default_width: number;
    default_height: number;
    default_steps: number;
    default_cfg: number;
    default_lora_strength_model: number;
    default_lora_strength_clip: number;
    group_count_min: number;
    max_group_count: number;
    max_total_count: number;
    width_min: number;
    width_max: number;
    height_min: number;
    height_max: number;
    steps_min: number;
    steps_max: number;
    cfg_min: number;
    cfg_max: number;
    cfg_step: number;
    lora_strength_min: number;
    lora_strength_max: number;
    lora_strength_step: number;
    allowed_sizes: SizeTuple[];
  };
  video: {
    default_frames: number;
    default_fps: number;
    default_width: number;
    default_height: number;
    default_steps: number;
    default_cfg: number;
    default_denoise: number;
    default_lora_strength: number;
    seed_min: number;
    timeout_seconds: number;
    long_video_max_segments: number;
    long_video_max_total_frames: number;
    keyframe_max_bytes: number;
    script_max_length: number;
    steps_min: number;
    steps_max: number;
    cfg_min: number;
    cfg_max: number;
    cfg_step: number;
    denoise_min: number;
    denoise_max: number;
    denoise_step: number;
    lora_strength_min: number;
    lora_strength_max: number;
    lora_strength_step: number;
    allowed_frames: number[];
    allowed_sizes: VideoSizeTuple[];
  };
  train: {
    default_caption_threshold: number;
    default_caption_batch_size: number;
    default_skip_existing: boolean;
    default_remove_underscore: boolean;
    default_auto_convert: boolean;
    default_resolution: number;
    default_repeats: number;
    default_batch_size: number;
    default_network_dim: number;
    default_network_alpha: number;
    default_learning_rate: number;
    default_epochs: number;
    default_save_every: number;
    default_max_steps: number;
    caption_threshold_min: number;
    caption_threshold_max: number;
    caption_threshold_step: number;
    caption_batch_min: number;
    caption_batch_max: number;
    resolution_min: number;
    resolution_max: number;
    resolution_step: number;
    repeats_min: number;
    repeats_max: number;
    batch_size_min: number;
    batch_size_max: number;
    network_dim_min: number;
    network_dim_max: number;
    network_alpha_min: number;
    network_alpha_max: number;
    learning_rate_min: number;
    learning_rate_max: number;
    learning_rate_step: number;
    epochs_min: number;
    epochs_max: number;
    save_every_min: number;
    save_every_max: number;
    max_steps_min: number;
    max_steps_max: number;
    merge_ratio_default: number;
    merge_ratio_min: number;
    merge_ratio_max: number;
    merge_ratio_step: number;
  };
  compare: {
    default_width: number;
    default_height: number;
    default_steps: number;
    default_cfg: number;
    width_min: number;
    width_max: number;
    height_min: number;
    height_max: number;
    steps_min: number;
    steps_max: number;
    cfg_min: number;
    cfg_max: number;
    cfg_step: number;
  };
  preset_composition: {
    max_items: number;
  };
  preset_assets: {
    root: string;
    template_version: string;
    upload_max_bytes: number;
    upload_max_pixels: number;
    candidate_min: number;
    candidate_max: number;
    candidate_default: number;
    batch_max_items: number;
    cpu_concurrency: number;
    ai_concurrency: number;
    preview_format: string;
    preview_quality: number;
    targets: Record<PresetAssetKind, PresetAssetTarget>;
    defaults: PresetAssetSettings;
  };
  image_tools: {
    max_bytes: number;
    max_pixels: number;
    max_concurrency: number;
    roughness_ratio_max: number;
    min_roughness_drop: number;
    comic_max_bytes: number;
    comic_max_pixels: number;
    comic_max_boxes: number;
    storyboard_max_bytes: number;
    storyboard_max_pixels: number;
    storyboard_crop_margin_max: number;
  };
  settings: {
    health_interval_default: number;
    health_interval_min: number;
    health_interval_max: number;
    max_failures_default: number;
    max_failures_min: number;
    max_failures_max: number;
    auto_shutdown_delay_default: number;
    auto_shutdown_delay_min: number;
    auto_shutdown_delay_max: number;
    data_retention_default: number;
    data_retention_min: number;
    data_retention_max: number;
  };
  query: {
    page_min: number;
    records_page_default: number;
    records_page_size_default: number;
    records_page_size_max: number;
    prompt_stats_top_default: number;
    prompt_stats_top_max: number;
    image_library_page_default: number;
    image_library_page_size_default: number;
    image_library_page_size_max: number;
    prompt_set_page_default: number;
    prompt_set_page_size_default: number;
    prompt_set_page_size_max: number;
    video_keyframes_limit_default: number;
    video_keyframes_limit_max: number;
    video_scripts_limit_default: number;
    video_scripts_limit_max: number;
    video_library_limit_default: number;
    video_library_limit_max: number;
    train_history_limit_default: number;
    train_history_limit_max: number;
    system_tasks_limit_default: number;
    system_tasks_limit_max: number;
  };
  backup: {
    keep_count: number;
  };
}

export async function fetchRuntimeConfig(): Promise<RuntimeConfig> {
  const { data } = await runtimeApi.get<RuntimeConfig>('/runtime-config');
  return data;
}

export async function fetchPresetTypes(): Promise<PresetTypeCatalog> {
  const { data } = await api.get<PresetTypeCatalog>('/preset-types');
  return data;
}

export type PresetAssetKind =
  | 'pose'
  | 'clothing'
  | 'scene'
  | 'body'
  | 'expansion'
  | 'toy'
  | 'character'
  | 'outfit';
export type PresetAssetSeedStrategy = 'fixed' | 'random' | 'derive';
export type PresetAssetCropMode = 'cover' | 'contain';
export type PresetAssetCandidateStatus =
  | 'queued'
  | 'preparing'
  | 'running'
  | 'cancel_requested'
  | 'ready'
  | 'cancelled'
  | 'interrupted'
  | 'failed';
export type PresetAssetTaskStatus =
  | 'queued'
  | 'preparing'
  | 'running'
  | 'cancel_requested'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'interrupted';
export type PresetAssetLoraStrengths = Record<
  string,
  {
    model?: number;
    clip?: number;
  }
>;

export interface PresetAssetTarget {
  generation_size: SizeTuple;
  output_size: SizeTuple;
  format: string;
  quality: number;
}

export interface PresetAssetSettings {
  version: number;
  model: string;
  loras: string[];
  lora_strengths: PresetAssetLoraStrengths;
  lora_strength_model: number;
  lora_strength_clip: number;
  steps: number;
  cfg: number;
  seed_strategy: PresetAssetSeedStrategy;
  seed: number | null;
  crop_mode: PresetAssetCropMode;
  focus_x: number;
  focus_y: number;
  zoom: number;
  candidate_count: number;
  style_positive: string;
  style_negative: string;
  user_positive: string;
  user_negative: string;
}

export interface PresetAssetSettingsPayload {
  defaults: PresetAssetSettings;
  targets: Record<PresetAssetKind, PresetAssetTarget>;
  limits: {
    candidate_min: number;
    candidate_max: number;
    batch_max_items: number;
    upload_max_bytes: number;
    upload_max_pixels: number;
    width_min: number;
    width_max: number;
    height_min: number;
    height_max: number;
    steps_min: number;
    steps_max: number;
    cfg_min: number;
    cfg_max: number;
    cfg_step: number;
    seed_min: number;
    seed_max: number;
    focus_min: number;
    focus_max: number;
    focus_step: number;
    zoom_min: number;
    zoom_max: number;
    zoom_step: number;
    lora_strength_min: number;
    lora_strength_max: number;
    lora_strength_step: number;
  };
  template_version: string;
}

export interface PresetAssetSource {
  id: number;
  preset_type: PresetAssetKind;
  preset_id: string;
  revision: number;
  source_kind: string;
  mime_type: string;
  width: number;
  height: number;
  sha256: string;
  active: boolean;
  created_at: string;
  url: string;
}

export interface PresetAssetCandidate {
  id: number;
  job_id?: string | null;
  preset_type: PresetAssetKind;
  preset_id: string;
  generation_mode: 'ai' | 'crop' | string;
  status: string;
  prompt_positive?: string;
  prompt_negative?: string;
  template_version?: string;
  model?: string;
  loras?: string[];
  seed?: number | null;
  generation_width?: number;
  generation_height?: number;
  output_width?: number;
  output_height?: number;
  crop?: Record<string, unknown>;
  params?: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at: string;
  original_url?: string | null;
  preview_url?: string | null;
  thumbnail_url?: string | null;
}

export interface PresetAssetVersion {
  id: number;
  preset_type: PresetAssetKind;
  preset_id: string;
  version: number;
  candidate_id?: number | null;
  mime_type: string;
  width: number;
  height: number;
  sha256: string;
  active: boolean;
  created_at: string;
  url: string;
}

export interface PresetAssetSummary {
  preset_type: PresetAssetKind;
  preset_id: string;
  label: string;
  category: string;
  category_group: string;
  subcategory: string;
  rating: string;
  restricted: boolean;
  image: string | null;
  has_image: boolean;
  active_version: PresetAssetVersion | null;
  source: PresetAssetSource | null;
  ready_count: number;
  running_count: number;
  failed_count: number;
  candidate_count: number;
  candidate_status_counts?: Partial<
    Record<PresetAssetCandidateStatus, number>
  >;
  task_status_counts?: Partial<Record<PresetAssetTaskStatus, number>>;
  task_status_updated_at?: string | null;
  updated_at?: string;
}

export interface PresetAssetCatalogItem extends PresetAssetSummary {
  order: number;
  kind_label: string;
}

export interface PresetAssetCatalogKind {
  kind: PresetAssetKind;
  label: string;
  order: number;
  items: PresetAssetCatalogItem[];
}

export interface PresetAssetCatalog {
  items: PresetAssetCatalogKind[];
}

export type PresetAssetCatalogSort = 'default' | 'name' | 'updated_at';

export interface PresetAssetCatalogFacet {
  value: string;
  label: string;
  count: number;
  order?: number;
}

export interface ImageToolReport {
  algorithm: string;
  operation: 'decode' | 'encode';
  source_format: string;
  width: number;
  height: number;
  mode: string;
  pixel_count: number;
  roughness_before: number;
  roughness_after: number;
  roughness_ratio: number;
  accepted: boolean;
  forced: boolean;
  input_sha256: string;
  output_sha256: string;
}

export interface ImageToolResult {
  blob: Blob;
  report: ImageToolReport;
}

export interface ComicDialogue {
  index: number;
  text: string;
  length: number;
  bubble_size: string;
}

export interface ComicScriptResult {
  cleaned_prompt: string;
  dialogues: ComicDialogue[];
  dialogue_count: number;
  warning: string;
}

export interface ComicFontOption {
  id: string;
  label: string;
  source: string;
}

export interface ComicCapabilities {
  fonts: ComicFontOption[];
  default_font: string;
  opencv: boolean;
  auto_bubble_requires: string;
}

export interface ComicTextBox {
  text: string;
  x: number;
  y: number;
  max_width: number;
  max_height: number;
  font_size: number;
  alignment: 'left' | 'center' | 'right';
  text_color: string;
  outline_width: number;
  outline_color: string;
}

export interface ComicTextRenderReport {
  width: number;
  height: number;
  font_id: string;
  box_count: number;
  boxes: Array<ComicTextBox & {
    index: number;
    font_size: number;
    lines: string[];
    line_count: number;
    fits: boolean;
  }>;
}

export interface ComicTextRenderResult {
  blob: Blob;
  report: ComicTextRenderReport;
}

export interface ComicBubble {
  x: number;
  y: number;
  width: number;
  height: number;
  area: number;
  center_x: number;
  center_y: number;
}

export interface ComicBubbleDetection {
  width: number;
  height: number;
  count: number;
  bubbles: ComicBubble[];
}

export interface StoryboardCell {
  order: number;
  row: number;
  column: number;
  x: number;
  y: number;
  width: number;
  height: number;
  file: string;
}

export interface StoryboardSliceReport {
  version: number;
  source_name: string;
  source_sha256: string;
  source_width: number;
  source_height: number;
  grid: 4 | 6 | 9;
  rows: number;
  columns: number;
  crop_margin: number;
  cell_count: number;
  cells: StoryboardCell[];
}

export interface StoryboardSliceResult {
  blob: Blob;
  report: StoryboardSliceReport;
}

export interface VideoMergeFileInfo {
  name: string;
  duration: number;
  bytes: number;
  video: {
    codec: string;
    width: number;
    height: number;
    fps: number;
  };
  audio: {
    codec: string;
    sample_rate: number;
    layout: string;
  } | null;
}

export interface VideoMergePreflight {
  compatible: boolean;
  issues: string[];
  output_format: string;
  files: VideoMergeFileInfo[];
  total_duration: number;
}

export interface MergedVideoResult {
  filename: string;
  url: string;
  format: string;
  bytes: number;
  total_duration: number;
  files: VideoMergeFileInfo[];
}

function decodeHeaderJson<T>(value: string | undefined): T {
  if (!value) throw new Error('服务未返回图片处理报告');
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes)) as T;
}

export async function deobfuscateImage(
  file: File,
  options: { force?: boolean } = {},
): Promise<ImageToolResult> {
  const form = new FormData();
  form.append('file', file, file.name);
  const response = await api.post<Blob>('/image-tools/deobfuscate', form, {
    params: { force: Boolean(options.force) },
    responseType: 'blob',
    timeout: 120000,
  });
  return {
    blob: response.data,
    report: decodeHeaderJson<ImageToolReport>(response.headers['x-image-tool-report']),
  };
}

export async function getComicCapabilities(): Promise<ComicCapabilities> {
  const response = await api.get<ComicCapabilities>('/image-tools/comic/capabilities');
  return response.data;
}

export async function parseComicScript(payload: {
  raw_prompt: string;
  base_bubble_description: string;
}): Promise<ComicScriptResult> {
  const response = await api.post<ComicScriptResult>('/image-tools/comic/parse', payload);
  return response.data;
}

export async function renderComicText(
  file: File,
  boxes: ComicTextBox[],
  fontId: string,
): Promise<ComicTextRenderResult> {
  const form = new FormData();
  form.append('file', file, file.name);
  const response = await api.post<Blob>('/image-tools/comic/render', form, {
    params: {
      boxes_json: JSON.stringify(boxes),
      font_id: fontId,
    },
    responseType: 'blob',
    timeout: 120000,
  });
  return {
    blob: response.data,
    report: decodeHeaderJson<ComicTextRenderReport>(
      response.headers['x-image-tool-report'],
    ),
  };
}

export async function detectComicBubbles(
  file: File,
  options: { whiteThreshold?: number; minArea?: number; invert?: boolean } = {},
): Promise<ComicBubbleDetection> {
  const form = new FormData();
  form.append('file', file, file.name);
  const response = await api.post<ComicBubbleDetection>(
    '/image-tools/comic/detect-bubbles',
    form,
    {
      params: {
        white_threshold: options.whiteThreshold ?? 220,
        min_area: options.minArea ?? 5000,
        invert: Boolean(options.invert),
      },
      timeout: 120000,
    },
  );
  return response.data;
}

export async function sliceStoryboard(
  file: File,
  grid: 4 | 6 | 9,
  cropMargin: number,
): Promise<StoryboardSliceResult> {
  const form = new FormData();
  form.append('file', file, file.name);
  const response = await api.post<Blob>('/storyboard/slice', form, {
    params: {
      grid,
      crop_margin: cropMargin,
    },
    responseType: 'blob',
    timeout: 120000,
  });
  return {
    blob: response.data,
    report: decodeHeaderJson<StoryboardSliceReport>(
      response.headers['x-image-tool-report'],
    ),
  };
}

function videoMergeForm(files: File[]): FormData {
  const form = new FormData();
  files.forEach((file) => form.append('files', file, file.name));
  return form;
}

export async function preflightVideoMerge(
  files: File[],
): Promise<VideoMergePreflight> {
  const response = await api.post<VideoMergePreflight>(
    '/storyboard/merge/preflight',
    videoMergeForm(files),
    { timeout: 180000 },
  );
  return response.data;
}

export async function mergeVideoSegments(
  files: File[],
): Promise<MergedVideoResult> {
  const response = await api.post<MergedVideoResult>(
    '/storyboard/merge',
    videoMergeForm(files),
    { timeout: 3_600_000 },
  );
  return response.data;
}

export interface LongVideoStartPayload {
  keyframe_name: string;
  prompts: string[];
  negative_prompt: string;
  frames: number;
  fps: number;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  denoise: number;
  lora_strength: number;
  seed?: number;
  use_lora?: boolean;
}

export async function startLongVideo(
  payload: LongVideoStartPayload,
): Promise<{
  job_id: string;
  record_id: number;
  status: string;
  segments: number;
  total_frames: number;
}> {
  const response = await api.post('/video/long/jobs', payload, {
    timeout: 120000,
  });
  return response.data;
}

export async function getLongVideoStatus(
  jobId: string,
): Promise<LongVideoStatus> {
  const response = await api.get<LongVideoStatus>(
    `/video/long/jobs/${jobId}`,
  );
  return response.data;
}

export async function stopLongVideo(jobId: string): Promise<void> {
  await api.post(`/video/long/jobs/${jobId}/stop`);
}

export async function resumeLongVideo(
  jobId: string,
  fromSegment?: number,
): Promise<{ job_id: string; status: string; from_segment: number }> {
  const response = await api.post<{
    job_id: string;
    status: string;
    from_segment: number;
  }>(`/video/long/jobs/${jobId}/resume`, {
    from_segment: fromSegment,
  });
  return response.data;
}

export interface PresetAssetCatalogFacets {
  kinds: PresetAssetCatalogFacet[];
  category_groups: PresetAssetCatalogFacet[];
  subcategories: PresetAssetCatalogFacet[];
  task_statuses: PresetAssetCatalogFacet[];
}

export interface PresetAssetCatalogQuery {
  kind: PresetAssetKind;
  keyword?: string;
  resource?: string;
  rating?: string;
  category_group?: string;
  subcategory?: string;
  candidate_status?: PresetAssetCandidateStatus;
  task_status?: PresetAssetTaskStatus;
  page?: number;
  page_size?: number;
  sort?: PresetAssetCatalogSort;
}

export interface PresetAssetCatalogQueryResponse extends PresetAssetCatalog {
  total: number;
  page: number;
  page_size: number;
  sort: PresetAssetCatalogSort;
  facets: PresetAssetCatalogFacets;
}

export interface PresetAssetDetail {
  preset: Record<string, unknown>;
  summary: PresetAssetSummary;
  sources: PresetAssetSource[];
  candidates: PresetAssetCandidate[];
  versions: PresetAssetVersion[];
}

export interface PresetAssetJobItem {
  job_id: string;
  item_index: number;
  preset_type: PresetAssetKind;
  preset_id: string;
  preset_label?: string;
  candidate_id?: number | null;
  status: string;
  params: Record<string, unknown>;
  error?: string | null;
  attempt_count?: number;
  next_retry_at?: string | null;
  retry_backoff_seconds?: number;
  last_error_code?: string | null;
  retryable?: boolean;
  candidate_count?: number;
  ready_count?: number;
  adopted_count?: number;
  active_count?: number;
  failed_count?: number;
  cancelled_count?: number;
  active_version?: PresetAssetVersion | null;
  candidate_summary_reliable?: boolean;
  candidate_summary_source?: 'job_item' | 'legacy_preset_fallback';
  user_action?:
    | 'retry'
    | 'wait_and_retry'
    | 'start_service'
    | 'free_gpu'
    | 'fix_parameters'
    | 'review_preset'
    | 'none'
    | null;
  created_at: string;
  updated_at: string;
}

export interface PresetAssetJob {
  job_id: string;
  kind: 'preset_asset';
  status: string;
  total: number;
  done: number;
  current: string;
  error?: string | null;
  stop_requested: boolean;
  created_at: string;
  updated_at?: string;
  finished_at?: string | null;
  items: PresetAssetJobItem[];
  candidates: PresetAssetCandidate[];
}

export interface PresetAssetJobList {
  items: PresetAssetJob[];
}

export interface PresetAssetJobCreateItem {
  preset_type: PresetAssetKind;
  preset_id: string;
  mode?: 'ai' | 'crop';
  params?: Partial<PresetAssetSettings>;
  source_id?: number | null;
  crop?: PresetAssetCropInput;
}

export interface PresetAssetCropInput {
  mode: PresetAssetCropMode;
  focus_x: number;
  focus_y: number;
  zoom: number;
}

export async function fetchPresetAssetSettings(): Promise<PresetAssetSettingsPayload> {
  const { data } = await api.get<PresetAssetSettingsPayload>('/preset-assets/settings');
  return data;
}

export async function savePresetAssetSettings(
  defaults: PresetAssetSettings,
): Promise<PresetAssetSettingsPayload> {
  const { data } = await api.put<PresetAssetSettingsPayload>('/preset-assets/settings', {
    defaults,
  });
  return data;
}

export async function fetchPresetAssetCatalog(): Promise<PresetAssetCatalog> {
  const { data } = await api.get<PresetAssetCatalog>('/preset-assets/catalog');
  return data;
}

export async function fetchPresetAssetCatalogQuery(
  query: PresetAssetCatalogQuery,
): Promise<PresetAssetCatalogQueryResponse> {
  const { data } = await api.get<PresetAssetCatalogQueryResponse>(
    '/preset-assets/catalog/query',
    {
      params: {
        kind: query.kind,
        keyword: query.keyword || '',
        resource: query.resource || 'all',
        rating: query.rating || '',
        category_group: query.category_group || '',
        subcategory: query.subcategory || '',
        candidate_status: query.candidate_status || '',
        task_status: query.task_status || '',
        page: query.page || 1,
        page_size: query.page_size || 40,
        sort: query.sort || 'default',
      },
    },
  );
  return data;
}

export async function fetchPresetAssetDetail(
  presetType: PresetAssetKind,
  presetId: string,
): Promise<PresetAssetDetail> {
  const { data } = await api.get<PresetAssetDetail>(
    `/preset-assets/presets/${presetType}/${encodeURIComponent(presetId)}`,
  );
  return data;
}

export async function fetchPresetAssetHistory(
  presetType: PresetAssetKind,
  presetId: string,
): Promise<{ versions: PresetAssetVersion[]; audit: Record<string, unknown>[] }> {
  const { data } = await api.get<{
    versions: PresetAssetVersion[];
    audit: Record<string, unknown>[];
  }>(`/preset-assets/presets/${presetType}/${encodeURIComponent(presetId)}/history`);
  return data;
}

export async function importPresetAssetSource(
  presetType: PresetAssetKind,
  presetId: string,
  dataUrl: string,
  mimeType?: string,
): Promise<PresetAssetSource> {
  const { data } = await api.post<PresetAssetSource>(
    `/preset-assets/presets/${presetType}/${encodeURIComponent(presetId)}/sources/import`,
    { data: dataUrl, mime_type: mimeType },
  );
  return data;
}

export async function createPresetAssetCropCandidate(
  presetType: PresetAssetKind,
  presetId: string,
  payload: {
    source_id?: number | null;
    crop: PresetAssetCropInput;
    params?: Record<string, unknown>;
  },
): Promise<PresetAssetCandidate> {
  const { data } = await api.post<PresetAssetCandidate>(
    `/preset-assets/presets/${presetType}/${encodeURIComponent(presetId)}/candidates/crop`,
    payload,
  );
  return data;
}

export async function createPresetAssetAiCandidates(
  presetType: PresetAssetKind,
  presetId: string,
  params: Partial<PresetAssetSettings>,
  idempotencyKey?: string,
): Promise<PresetAssetJob> {
  const { data } = await api.post<PresetAssetJob>(
    `/preset-assets/presets/${presetType}/${encodeURIComponent(presetId)}/candidates/ai`,
    { params },
    idempotencyKey
      ? { headers: { 'Idempotency-Key': idempotencyKey } }
      : undefined,
  );
  return data;
}

export async function fetchPresetAssetJob(jobId: string): Promise<PresetAssetJob> {
  const { data } = await api.get<PresetAssetJob>(
    `/preset-assets/jobs/${encodeURIComponent(jobId)}`,
  );
  return data;
}

export async function fetchPresetAssetJobs(
  params?: { status?: string; limit?: number },
): Promise<PresetAssetJobList> {
  const { data } = await api.get<PresetAssetJobList>('/preset-assets/jobs', {
    params,
  });
  return data;
}

export async function createPresetAssetJobs(
  items: PresetAssetJobCreateItem[],
  idempotencyKey?: string,
): Promise<PresetAssetJob> {
  const { data } = await api.post<PresetAssetJob>(
    '/preset-assets/jobs',
    { items },
    idempotencyKey
      ? { headers: { 'Idempotency-Key': idempotencyKey } }
      : undefined,
  );
  return data;
}

export async function cancelPresetAssetJob(jobId: string): Promise<PresetAssetJob> {
  const { data } = await api.post<PresetAssetJob>(
    `/preset-assets/jobs/${encodeURIComponent(jobId)}/cancel`,
  );
  return data;
}

export async function retryPresetAssetJob(jobId: string): Promise<PresetAssetJob> {
  const { data } = await api.post<PresetAssetJob>(
    `/preset-assets/jobs/${encodeURIComponent(jobId)}/retry-failed`,
  );
  return data;
}

export async function retryPresetAssetJobItem(
  jobId: string,
  itemIndex: number,
): Promise<PresetAssetJob> {
  const { data } = await api.post<PresetAssetJob>(
    `/preset-assets/jobs/${encodeURIComponent(jobId)}/items/${itemIndex}/retry`,
  );
  return data;
}

export async function adoptPresetAssetCandidate(
  candidateId: number,
  expectedRevision?: number | null,
): Promise<{ ok: boolean; version: PresetAssetVersion; image: string | null }> {
  const { data } = await api.post<{
    ok: boolean;
    version: PresetAssetVersion;
    image: string | null;
  }>(`/preset-assets/candidates/${candidateId}/adopt`, {
    expected_revision: expectedRevision ?? null,
  });
  return data;
}

export async function discardPresetAssetCandidate(candidateId: number): Promise<void> {
  await api.post(`/preset-assets/candidates/${candidateId}/discard`);
}

export async function clearPresetAssetCandidates(
  presetType: PresetAssetKind,
  presetId: string,
): Promise<{ ok: boolean; cleared_count: number }> {
  const { data } = await api.post<{ ok: boolean; cleared_count: number }>(
    `/preset-assets/presets/${presetType}/${encodeURIComponent(presetId)}/candidates/clear`,
  );
  return data;
}

export async function rollbackPresetAssetVersion(
  presetType: PresetAssetKind,
  presetId: string,
  version: number,
  expectedRevision?: number | null,
): Promise<{ ok: boolean; version: PresetAssetVersion; image: string | null }> {
  const { data } = await api.post<{
    ok: boolean;
    version: PresetAssetVersion;
    image: string | null;
  }>(
    `/preset-assets/presets/${presetType}/${encodeURIComponent(presetId)}/rollback/${version}`,
    { expected_revision: expectedRevision ?? null },
  );
  return data;
}

export interface ServiceStatus {
  ollama: boolean;
  comfyui: boolean;
}

export interface ServiceSupervision {
  auto_start: boolean;
  auto_restart: boolean;
  interval_seconds: number;
  max_failures: number;
  consecutive: Record<string, number>;
  restarting: Record<string, boolean>;
}

export interface AutoShutdownSettings {
  enabled: boolean;
  delay_seconds: number;
  phase: string;
  remaining_seconds?: number | null;
  task_type?: string | null;
  task_label?: string;
  finished_at?: string | null;
  shutdown_at?: string | null;
  last_error?: string | null;
}

export interface GpuActiveModel {
  name: string;
  size_mb: number;
}

export interface GpuInfo {
  util: number;
  memory_used_mb: number;
  memory_total_mb: number;
  temperature_c: number;
  power_w: number;
  cpu_percent: number;
  ram_used_mb: number;
  ram_total_mb: number;
  disk_free_gb: number;
  disk_total_gb: number;
  process_memory_mb: number;
  active_models: GpuActiveModel[];
}

export interface BackupItem {
  name: string;
  size_mb: number;
  created_at: string;
}

export interface DrawResult {
  record_id?: number;
  prompt_id?: string;
  image_url: string;
  comfy_url?: string;
  saved_path?: string;
  seed?: number;
  elapsed?: number;
  group_index?: number;
  image_index?: number;
  review?: {
    ok?: boolean;
    character_count?: number;
    expected_count?: number | null;
    multiple_same?: boolean;
    reason?: string;
    message?: string;
    pose_ok?: boolean | null;
    action_ok?: boolean | null;
    composition_ok?: boolean | null;
    wrong_reason?: string;
    count_consensus?: boolean | null;
    count_models?: {
      detail?: string;
      counter?: string;
    };
    counter_character_count?: number | null;
    crop_counts?: Record<string, number | null>;
    crop_sum?: number | null;
    review_status?: string;
    skipped?: boolean;
    error?: string;
  };
  guard?: {
    expected_count?: number;
    attempts?: number;
    retries?: number;
    passed?: boolean | null;
    strengthened?: boolean;
    reason?: string;
    pose_ok?: boolean | null;
    action_ok?: boolean | null;
    composition_ok?: boolean | null;
    count_consensus?: boolean | null;
    counter_character_count?: number | null;
    crop_counts?: Record<string, number | null>;
    crop_sum?: number | null;
    review_status?: string;
    retry_error?: string;
  };
}

export type PromptDocumentMode = 'structured' | 'legacy';

export interface PromptPresetRef {
  preset_id: string;
  version?: number;
  scope?: PresetScope;
}

export interface PromptBlock {
  id?: string;
  kind?: string;
  tags: string[];
  preset_refs: PromptPresetRef[];
  preset_snapshot?: Record<string, unknown> | unknown[];
  locked?: boolean;
  enabled?: boolean;
  source?: string;
  order?: number;
  gaze?: string[];
  face_details?: string[];
  intensity?: number;
  clothing_state?: string[];
  footwear?: PromptBlock;
  framing?: string[];
  angle?: string[];
  focus?: string[];
  time?: string[];
  weather?: string[];
  foreground?: string[];
  background?: string[];
  palette?: string[];
  mood?: string[];
}

export type PromptHeightFrame =
  | 'none'
  | 'petite_adult'
  | 'standard_height'
  | 'tall';

export type PromptBodyBuild =
  | 'none'
  | 'standard'
  | 'slim'
  | 'athletic'
  | 'curvy'
  | 'plump';

export interface PromptBodyProfile {
  height_frame: PromptHeightFrame;
  body_build: PromptBodyBuild;
}

export interface PromptCharacter {
  id: string;
  role_id: string;
  display_name: string;
  gender: string;
  height_frame: PromptHeightFrame;
  body_build: PromptBodyBuild;
  order: number;
  enabled: boolean;
  appearance: PromptBlock;
  clothing: PromptBlock;
  body_modifications: PromptBlock;
  pose_or_action: PromptBlock;
  expression: PromptBlock;
  state: PromptBlock;
  negative: PromptBlock;
}

export interface PromptDocumentV1 {
  version?: number;
  mode: PromptDocumentMode;
  global: Record<'quality' | 'style' | 'scene' | 'camera' | 'lighting' | 'constraints', PromptBlock>;
  characters: PromptCharacter[];
  props: {
    global: PromptBlock;
    characters: Record<string, PromptBlock>;
  };
  interaction: {
    pose_preset?: PromptPresetRef;
    action_tags: string[];
    contact_tags: string[];
    relationship_tags: string[];
    composition_constraints: string[];
  };
  custom: {
    global_tags: string[];
    user_notes: string;
  };
  negative: Record<'quality' | 'anatomy' | 'composition' | 'scene' | 'style' | 'content' | 'custom', PromptBlock>;
  raw_override: {
    prompt: string;
    negative_prompt: string;
  };
}

export interface PromptDocumentResolveResult {
  prompt: string;
  negative_prompt: string;
  rating: string;
  warnings: string[];
  errors: string[];
  blocked: boolean;
  used_ids: string[];
  roles: { id: string; role_id: string; display_name: string; order: number }[];
  resolved_document: PromptDocumentV1;
  template_version: string;
}

export interface DrawGroupInput {
  prompt: string;
  count: number;
  prompt_document?: PromptDocumentV1 | null;
}

export interface CharacterAppearancePreset {
  id: number;
  preset_id: string;
  label?: string;
  translation?: string;
  name: string;
  work: string;
  category: string;
  appearance_tags: string[];
  clothing_tags: string[];
  expression_tags: string[];
  outfit_id: string;
  outfit_name?: string;
  outfit_set_id: string;
  outfit_set_version: number;
  outfit_set_name?: string;
  outfit_set_content_hash?: string;
  outfit_set_prompt?: string;
  outfit_set_rating?: string;
  outfit_set_items?: StoredOutfitItem[];
  outfit_set_missing?: boolean;
  outfit_set_restricted?: boolean;
  note: string;
  source: 'builtin' | 'user' | 'llm_draft' | 'legacy_cache' | string;
  version: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  has_thumbnail?: boolean;
  thumbnail_url?: string | null;
  thumbnail_stale?: boolean;
  thumbnail_version?: number | null;
  current_preset_version?: number;
}

export interface CharacterAppearancePresetList {
  items: CharacterAppearancePreset[];
  total: number;
  categories: string[];
  sources: string[];
  works: string[];
}

export interface CharacterAppearancePresetApplyResult {
  preset_ref: { preset_id: string; version: number };
  snapshot: {
    name: string;
    category: string;
    appearance_tags: string[];
    clothing_tags: string[];
    expression_tags: string[];
    outfit_id: string;
    outfit_name?: string;
    outfit_set_id: string;
    outfit_set_version: number;
    outfit_set_name?: string;
    outfit_set_content_hash?: string;
    note: string;
  };
  appearance: string[];
  clothing: string[];
  expression: string[];
  default_outfit_id: string;
  default_outfit_name?: string;
  default_outfit_set: AppliedOutfitSet | null;
}

export interface BatchJob {
  batch_id: string;
  status: string;
  total: number;
  done: number;
  current_group: number;
  results: DrawResult[];
  error?: string | null;
  created_at?: string;
  finished_at?: string | null;
  elapsed_seconds?: number;
  server_now?: string;
  duration_seconds?: number;
  steps_done?: number;
  steps_total?: number;
  log_updated_at?: string;
  log_age_seconds?: number;
  save_state?: boolean;
  loss_history?: { step: number; loss: number }[];
  latest_loss?: number;
  min_loss?: number;
  best_step?: number;
}

export interface LoraItem {
  name: string;
  size_mb: number;
  modified_at?: string;
  usage_count?: number;
  protected?: boolean;
  purpose?: 'drawing' | 'video' | 'unknown';
  compatible?: boolean;
  incompatible_reason?: string | null;
}

export interface GenerationCanvasPreset {
  id: string;
  label: string;
  width: number;
  height: number;
}

export interface GenerationProfile {
  id: string;
  label: string;
  latent_node: string;
  channels: number;
  height_divisor: number;
  width_divisor: number;
  resolution_step: number;
  min_size: number;
  max_size: number;
  batch_max: number;
  downscale_ratio: number;
  workflow_supported: boolean;
  workflow_support_reason: string;
  canvas_presets: GenerationCanvasPreset[];
}

export interface ModelItem {
  name: string;
  size_mb: number;
  generation_profile: string;
  generation_profile_label: string;
  workflow_supported: boolean;
  workflow_support_reason: string;
  spec: GenerationProfile;
}

export interface PresetTaxonomyFields {
  category_group?: string;
  subcategory?: string;
  sort_order?: number;
  asset_intent?: string[];
}

export interface PresetKindMetadata {
  kind: string;
  label: string;
  order: number;
  catalog_key: string;
  api_path: string;
  image_directory: string;
  image_extension: string;
  taxonomy_key: string;
  composition_field: string;
  scope_capable: boolean;
  max_per_scope: number | null;
  selection_type: 'single' | 'multiple';
  supports_colors: boolean;
  supports_thumbnail: boolean;
  composition_enabled?: boolean;
}

export interface PresetTypeCatalog {
  items: PresetKindMetadata[];
  composition: {
    max_items: number;
  };
}

export interface ClothingPreset extends PresetTaxonomyFields {
  schema_version?: number;
  id: string;
  category: string;
  label: string;
  translation: string;
  tags: string[];
  image?: string | null;
  draw_prompt?: string | null;
  gender: string;
  part: string;
  nsfw: boolean;
  rating: string;
  intensity?: string;
  source?: string;
  materials?: string[];
  layer_state?: string;
  color_slots?: string[];
  accessories?: string[];
  compatibility?: string[];
  has_image?: boolean;
  aliases?: string[];
  tag_count?: number;
  footwear_type?: string;
  legwear_type?: string;
  opacity?: string;
  pattern?: string;
  top?: string;
}

export type OutfitSlot =
  | 'headwear'
  | 'underwear'
  | 'top'
  | 'bottom'
  | 'outerwear'
  | 'full_body'
  | 'legwear'
  | 'footwear'
  | 'accessory';

export interface OutfitItemDraft {
  clothing_id: string;
  slot?: OutfitSlot;
  colors?: Partial<Record<PresetColorSlot, string>>;
  layer_state?: string;
  order?: number;
  enabled?: boolean;
  covers?: OutfitSlot[];
}

export interface OutfitItemSnapshot {
  id: string;
  label: string;
  translation: string;
  category: string;
  part: string;
  tags: string[];
  draw_prompt: string;
  rating: string;
  source: string;
  schema_version: number;
  layer_state: string;
  materials: string[];
  accessories: string[];
}

export interface StoredOutfitItem extends OutfitItemDraft {
  clothing_id: string;
  slot: OutfitSlot;
  colors: Partial<Record<PresetColorSlot, string>>;
  layer_state: string;
  order: number;
  enabled: boolean;
  covers: OutfitSlot[];
  clothing_version: number;
  snapshot: OutfitItemSnapshot;
}

export interface OutfitSetDefinition {
  schema_version?: number;
  name: string;
  description?: string;
  category?: string;
  gender_scope?: string;
  character_scope?: string[];
  rating?: string;
  content_hash?: string;
  prompt?: string;
  occupied_slots?: string[];
  warnings?: string[];
  items: Array<OutfitItemDraft | StoredOutfitItem>;
}

export interface AppliedOutfitSet extends OutfitSetDefinition {
  preset_id: string;
  version: number;
  content_hash: string;
}

export interface OutfitSetPreset {
  id: string;
  row_id: number;
  preset_id: string;
  label?: string;
  translation?: string;
  name: string;
  description: string;
  category: string;
  gender_scope: string;
  character_scope: string[];
  source: 'builtin' | 'user' | string;
  version: number;
  enabled: boolean;
  rating: string;
  nsfw?: boolean;
  has_image?: boolean;
  image?: string | null;
  content_hash: string;
  prompt: string;
  items: StoredOutfitItem[];
  created_at: string;
  updated_at: string;
}

export interface OutfitSetCatalog {
  items: OutfitSetPreset[];
  total: number;
  categories: string[];
  slots: Array<{ value: OutfitSlot; label: string }>;
  max_items: number;
  restricted: boolean;
  schema_version: number;
}

export interface OutfitSetVersionCatalog {
  items: OutfitSetPreset[];
  total: number;
}

export interface ScenePreset extends PresetTaxonomyFields {
  schema_version?: number;
  id: string;
  category: string;
  label: string;
  translation: string;
  tags: string[];
  rating: string;
  intensity: string;
  source?: string;
  people: string;
  orientation: string;
  role_slots: string[];
  body_separation: boolean;
  contact_points: string[];
  setting: string;
  equipment: string[];
  camera: string;
  lighting: string;
  conflicts: string[];
  draw_prompt: string;
  people_policy?: 'occupied' | 'empty';
  empty_scene_prompt?: string | null;
  occupied_scene_prompt?: string | null;
  has_image: boolean;
  image: string | null;
}

export interface ExpressionPreset {
  schema_version?: number;
  id: string;
  category: string;
  label: string;
  translation: string;
  tags: string[];
  expression_tags?: string[];
  gaze?: string[];
  face_details?: string[];
  intensity: string;
  intensity_value?: number;
  character_scope: string[];
  rating: string;
  nsfw?: boolean;
  source?: string;
  aliases?: string[];
}

export interface WaterPreset {
  schema_version?: number;
  id: string;
  category: string;
  label: string;
  translation: string;
  tags: string[];
  water_level: string;
  target: '角色' | '环境';
  intensity: string;
  rating: string;
  nsfw?: boolean;
  source?: string;
}

export interface BodyModificationPreset extends PresetTaxonomyFields {
  schema_version?: number;
  id: string;
  category: string;
  label: string;
  translation: string;
  tags: string[];
  rating: string;
  intensity: string;
  source?: string;
  modification_type: string;
  location: string;
  conflicts: string[];
  draw_prompt: string;
  has_image: boolean;
  image: string | null;
}

export interface PoseCatalogItem extends PresetTaxonomyFields {
  id: string;
  category: string;
  label: string;
  translation?: string;
  tags: string[];
  draw_prompt?: string;
  rating?: string;
  people?: string;
  people_count?: number;
  people_prompt?: string;
  core_tags?: string[];
  core_prompt?: string;
  full_prompt?: string;
  accuracy_status?: 'verified' | 'needs_rework' | 'deprecated';
  accuracy_notes?: string | null;
  accuracy_audit_version?: number;
  orientation?: string;
  role_slots?: string[];
  body_separation?: boolean;
  compatibility?: string[];
  image?: string | null;
}

export interface PresetCatalog {
  restricted: boolean;
  poses: PoseCatalogItem[];
  clothing: ClothingPreset[];
  scenes: ScenePreset[];
  expressions?: ExpressionPreset[];
  water?: WaterPreset[];
  body_modifications: BodyModificationPreset[];
  expansions?: ExpansionPreset[];
  toys?: ToyPreset[];
}

export interface ExpansionPreset extends PresetTaxonomyFields {
  id: string;
  category: string;
  state: string;
  label: string;
  translation?: string;
  tags: string[];
  draw_prompt?: string;
  rating?: string;
  intensity?: string;
  visual_only?: boolean;
  execution_allowed?: boolean;
  visual_material?: {
    id: string;
    label: string;
    appearance_reference?: string;
    visual_prompt?: string;
  } | null;
  image?: string | null;
}

export interface ToyPreset extends PresetTaxonomyFields {
  id: string;
  category: string;
  label: string;
  translation?: string;
  tags: string[];
  draw_prompt?: string;
  rating?: string;
  intensity?: string;
  form_factor?: string;
  material_appearance?: string;
  visual_only?: boolean;
  image?: string | null;
}

export type PresetScope = 'all' | 'girlA' | 'girlB' | 'boyA' | 'boyB';
export type PresetColorSlot = 'primary' | 'secondary' | 'accent';

export interface PresetSelection {
  id: string;
  scope: PresetScope;
  colors?: Partial<Record<PresetColorSlot, string>>;
}

export interface PresetComposition {
  pose_id?: string | null;
  scene_id?: string | null;
  clothing: PresetSelection[];
  body_modifications: PresetSelection[];
  expansions?: PresetSelection[];
  toys?: PresetSelection[];
}

export interface PresetCompositionResult {
  prompt: string;
  rating: string;
  warnings: string[];
  blocked: boolean;
  used_ids: string[];
  roles: string[];
  items: {
    pose_id: string | null;
    scene_id: string | null;
    clothing: PresetSelection[];
    body_modifications: PresetSelection[];
    expansions?: PresetSelection[];
    toys?: PresetSelection[];
  };
}

export interface TagTranslation {
  tag: string;
  translation: string;
}

export interface RecordsResult {
  total: number;
  page: number;
  page_size: number;
  items: Record<string, unknown>[];
}

export interface PromptAgentResult {
  description?: string;
  prompt?: string;
  prompt_translation?: string;
  source_text?: string;
  filename?: string;
  analysis?: {
    mode?: 'vlm' | 'wd14' | 'hybrid';
    model_label?: string;
    rating?: string;
    vlm_model?: string;
    wd14_error?: string;
    wd14?: {
      tags?: string[];
      general_tags?: string[];
      character_tags?: string[];
      rating?: string;
      threshold?: number;
      model?: string;
    };
  };
}

export interface PromptGroup {
  label: string;
  items: string[];
}

export interface PromptValidationIssue {
  type: 'error' | 'warning' | 'suggestion';
  message: string;
  action?: 'dedupe' | 'remove-tag';
  tags?: string[];
}

export interface PromptValidation {
  errors: PromptValidationIssue[];
  warnings: PromptValidationIssue[];
  suggestions: PromptValidationIssue[];
}

export interface DatasetItem {
  name: string;
  has_caption: boolean;
  caption_name: string;
}

export interface DatasetInfo {
  image_count: number;
  caption_count: number;
  missing_count: number;
  items: DatasetItem[];
}

export interface DatasetTagReplaceFile {
  name: string;
  count: number;
}

export interface DatasetTagReplaceResult {
  ok: boolean;
  dry_run: boolean;
  total_files: number;
  affected_files: number;
  affected_tags: number;
  files: DatasetTagReplaceFile[];
  backup_dir?: string | null;
}

export interface CaptionJob {
  job_id: string;
  mode: 'wd14' | 'qwen';
  status: 'running' | 'done' | 'error' | 'stopped';
  total: number;
  done: number;
  last_file: string;
  log: string;
  error: string | null;
  created_at?: string;
  finished_at?: string | null;
}

export interface TrainingJob {
  job_id: string;
  output_name?: string;
  status: 'running' | 'done' | 'error' | 'stopped';
  log: string;
  error?: string | null;
  converting?: boolean;
  convert_error?: string | null;
  created_at?: string;
  finished_at?: string | null;
  duration_seconds?: number;
  steps_done?: number;
  steps_total?: number;
  log_updated_at?: string;
  log_age_seconds?: number;
  stalled?: boolean;
  stall_reason?: string;
  resume_available?: boolean;
  resume_state?: string;
  save_state?: boolean;
  loss_history?: { step: number; loss: number }[];
  latest_loss?: number;
  min_loss?: number;
  best_step?: number;
  dit?: string;
  resolution?: number;
  repeats?: number;
  batch_size?: number;
  network_dim?: number;
  network_alpha?: number;
  learning_rate?: number;
  epochs?: number;
  save_every?: number;
  max_steps?: number;
}

export interface TrainingOutput {
  name: string;
  size_mb: number;
  modified_at?: string;
}

export interface DatasetReviewResult {
  filename: string;
  ok: boolean;
  issues: string[];
}

export interface DatasetReviewJob {
  job_id: string;
  status: 'running' | 'done' | 'error';
  total: number;
  done: number;
  results: DatasetReviewResult[];
  error?: string | null;
  created_at?: string;
  finished_at?: string | null;
}

export interface MergeJob {
  job_id: string;
  status: 'running' | 'done' | 'error';
  output_file?: string | null;
  error?: string | null;
  created_at?: string;
  finished_at?: string | null;
}

export interface CompareResult {
  name: string;
  combo?: string[];
  image_url?: string | null;
  saved_path?: string | null;
  seed?: number;
  error?: string | null;
}

export interface CompareJob {
  job_id: string;
  status: 'running' | 'done' | 'error' | 'stopped';
  total: number;
  done: number;
  results: CompareResult[];
  error?: string | null;
  stop_requested?: boolean;
  created_at?: string;
  finished_at?: string | null;
}

export interface PromptSet {
  id: number;
  name: string;
  type: string;
  content: string;
  translation: string;
  description: string;
  tags: string;
  use_count: number;
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
  composition_json?: string;
  prompt_document_json?: string;
}

export interface PromptSetList {
  total: number;
  page: number;
  page_size: number;
  items: PromptSet[];
}

export interface DatasetCheck {
  image_count: number;
  missing_txt: number;
  portrait: number;
  landscape: number;
  square: number;
  low_res: { name: string; width: number; height: number }[];
  duplicates: string[][];
  suspicious: string[];
  items: { name: string; width: number; height: number; size_mb: number }[];
}

export interface DrawImageRecord {
  id: number;
  started_at: string;
  finished_at?: string | null;
  prompt?: string | null;
  negative_prompt?: string | null;
  model?: string | null;
  width?: number | null;
  height?: number | null;
  image_url?: string | null;
  image_path?: string | null;
  seed?: number | null;
  status?: string | null;
  prompt_document_json?: string;
  loras_json?: string | null;
  lora_anima_turbo?: number | null;
  lora_high_contrast?: number | null;
  edit_mode?: string | null;
  source_record_id?: number | null;
  mask_image_path?: string | null;
  masked_prompt?: string | null;
  inpaint_denoise?: number | null;
  edit_params_json?: string | null;
}

export interface ImageLibrary {
  total: number;
  page: number;
  page_size: number;
  items: DrawImageRecord[];
}

export type ExternalGalleryKind = 'pose' | 'costume';

export interface ExternalGalleryBinding {
  label: string;
  directory: string;
  accepted: boolean;
  accepted_at: string;
  configured: boolean;
  available: boolean;
  source_available: boolean;
  binding_id: string;
  source_id?: number | null;
  import_mode: 'managed' | 'reference';
  status: string;
  item_count: number;
  last_synced_at?: string | null;
  warning: string;
  error: string;
}

export interface ExternalGallerySettings {
  pose: ExternalGalleryBinding;
  costume: ExternalGalleryBinding;
}

export interface ExternalGalleryItem {
  id: string;
  asset_id?: number;
  name: string;
  category: string;
  system: string;
  angle: string;
  group: string;
  tags: string[];
  path: string;
  thumb: string;
  search: string;
  image_url: string;
  thumbnail_url: string;
  favorite?: boolean;
  last_used_at?: string | null;
  use_count?: number;
  managed?: boolean;
  pose_preset_id?: string;
  pose_preset_label?: string;
  pose_preset_category?: string;
}

export interface ExternalGalleryCatalogue {
  kind: ExternalGalleryKind;
  mode: 'manifest' | 'folder' | 'database';
  manifest: string;
  warning: string;
  count: number;
  items: ExternalGalleryItem[];
  facets: {
    system: string[];
    category: string[];
    angle: string[];
    tag: string[];
  };
}

export interface InpaintSource {
  source_id: string;
  width: number;
  height: number;
  working_width: number;
  working_height: number;
  preview_url: string;
}

export interface InpaintResult {
  record_id: number;
  image_url: string;
  seed: number;
  denoise: number;
  width: number;
  height: number;
  source_id?: string;
  elapsed_ms?: number;
}

export interface InpaintJob {
  job_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';
  progress: { completed: number; total: number };
  source_id?: string;
  width?: number;
  height?: number;
  results: InpaintResult[];
  error?: { code: string; message: string } | null;
  created_at?: string;
  finished_at?: string | null;
}

export interface RecordsStats {
  status_counts: Record<string, number>;
  model_counts: Record<string, number>;
  size_counts: Record<string, number>;
  lora_counts?: Record<string, number>;
  combo_counts?: Record<string, number>;
  total?: number;
  success_count?: number;
  error_count?: number;
  avg_duration?: number;
  daily: { date: string; count: number; avg_duration: number }[];
}

export interface DashboardV3Coverage {
  total: number;
  formal_count: number;
  versioned_count: number;
  candidate_only_count: number;
  missing_count: number;
  formal_percent: number;
  with_candidates_percent: number;
}

export interface DashboardV3PresetAssets extends DashboardV3Coverage {
  candidate_count: number;
  candidate_status_counts: Record<string, number>;
  ready_count: number;
  running_count: number;
  failed_count: number;
  adopted_count: number;
  rolled_back_count: number;
  discarded_count: number;
  template_versions: Record<string, number>;
  template_missing_count: number;
  preset_version_counts: Record<string, number>;
  version_missing_count: number;
  by_kind: (DashboardV3Coverage & { kind: string; label: string })[];
}

export interface DashboardV3Data {
  range: { date_from: string; date_to: string };
  overview: {
    draw: Pick<RecordsStats, 'total' | 'success_count' | 'error_count' | 'avg_duration'>;
    train: { count: number; status: Record<string, number>; current?: TrainingJob | null };
    preset_assets: Pick<
      DashboardV3PresetAssets,
      'total' | 'formal_count' | 'candidate_only_count' | 'missing_count' | 'ready_count' | 'running_count' | 'failed_count'
    >;
    system: Record<string, unknown>;
  };
  draw: RecordsStats & { batch_count: number; batch_error_rate: number };
  train: {
    count: number;
    status: Record<string, number>;
    error_rate: number;
    avg_duration: number;
    output_count: number;
    recent_errors: string[];
    current?: TrainingJob | null;
    latest?: TrainingJob | null;
    daily: { date: string; count: number }[];
  };
  preset_assets: DashboardV3PresetAssets;
  system: {
    gpu: GpuInfo;
    busy: boolean;
    running_tasks: { type: string; label: string; job_id?: string }[];
    jobs: {
      count: number;
      status: Record<string, number>;
      error_rate: number;
      recent_errors: string[];
      daily: { date: string; count: number }[];
    };
  };
  secondary: {
    prompt_agent: number;
    recruitment_agent: number;
    video: number;
    companion: Record<string, unknown>;
  };
}

export interface VideoScriptPayload {
  story: string;
  action: string;
  scene: string;
  camera: string;
  character: string;
  mood: string;
  prompt: string;
  negative_prompt: string;
}

export interface VideoScriptItem {
  id: number;
  source_input: string;
  script: VideoScriptPayload;
  model: string;
  content_limited: boolean;
  created_at: string;
}

export interface VideoRecord {
  id: number;
  job_id: string;
  script_id?: number | null;
  keyframe_name?: string | null;
  keyframe_url?: string | null;
  video_name?: string | null;
  video_url?: string | null;
  prompt: string;
  negative_prompt?: string;
  model: string;
  loras?: string[];
  seed?: number | null;
  width: number;
  height: number;
  frames: number;
  fps: number;
  status: string;
  error?: string | null;
  duration_seconds?: number | null;
  created_at: string;
  finished_at?: string | null;
}

export interface VideoTask {
  job_id: string;
  status: string;
  current?: string;
  total?: number;
  done?: number;
  error?: string | null;
}

export interface VideoJobStatus {
  record: VideoRecord | null;
  task: VideoTask | null;
}

export interface LongVideoSegment {
  index: number;
  prompt: string;
  seed: number;
  status: 'pending' | 'running' | 'ready' | 'failed';
  attempts: number;
  video_name: string;
  error: string;
}

export interface LongVideoState {
  version: number;
  job_id: string;
  status: 'running' | 'error' | 'stopped' | 'interrupted' | 'done';
  created_at: string;
  updated_at: string;
  error: string;
  params: Record<string, unknown>;
  segments: LongVideoSegment[];
  final_video_name: string;
  final_url: string;
}

export interface LongVideoStatus {
  state: LongVideoState;
  task: VideoTask | null;
  record: VideoRecord | null;
}

export interface CompanionPersona {
  id: number;
  name: string;
  source: string;
  relationship: string;
  gender: string;
  personality: string;
  tone: string;
  appearance?: string;
  catchphrases: string;
  avatar?: string;
  config_json?: Record<string, unknown>;
}

export interface CompanionSession {
  id: number;
  persona_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface CompanionMessage {
  id: number;
  session_id: number;
  persona_id: number;
  role: string;
  content: string;
  emotion?: string;
  image_url?: string;
  image_description?: string;
  created_at: string;
}

export interface CompanionMemory {
  id: number;
  persona_id: number;
  content: string;
  importance: number;
  created_at: string;
}

export interface CompanionSettings {
  content_restriction: string;
  medical_disabled: string;
  dependency_reminder: string;
  minor_protection: string;
  online_search_enabled: string;
  model_provider: string;
  cloud_base_url: string;
  cloud_api_key: string;
  cloud_model: string;
}
