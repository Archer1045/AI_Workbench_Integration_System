// AI 绘画状态：多组提示词批量生成
import { message, Modal } from 'antd';
import useStore from 'resso';
import {
  api,
  type BatchJob,
  type DrawGroupInput,
  type DrawResult,
  type PromptBodyProfile,
  type PromptBodyBuild,
  type PromptDocumentMode,
  type PromptHeightFrame,
  type PromptDocumentResolveResult,
  type PromptDocumentV1,
  type PromptValidation,
} from '../api';
import { busyBlockMessage, showBusyWarning } from './busy';
import { getRuntimeConfig } from './runtimeConfig';
import { uiStore } from './ui';
import {
  createBodyProfile,
  createEmptyStructuredDocument,
  createLegacyDocument,
  createStructuredDocumentFromLegacy,
  isBodyProfileEmpty,
  isPromptDocumentEmpty,
  normalizeBodyProfile,
  normalizePromptDocument,
} from '../promptDocument';

export interface DrawGroup {
  id: string;
  prompt: string;
  prompt_document: PromptDocumentV1 | null;
  mode: PromptDocumentMode;
  body_profile: PromptBodyProfile;
  count: number;
  enabled?: boolean;
}

export interface DrawPersistState {
  model: string;
  groups: DrawGroup[];
  negativePrompt: string;
  width: number;
  height: number;
  steps: number | null;
  cfg: number;
  loras: string[];
  loraStrengthModel: number;
  loraStrengthClip: number;
  loraStrengths: Record<string, { model: number; clip: number }>;
}

export const DRAW_STATE_KEY = 'rider-studio:draw-state-v2';
export const LEGACY_DRAW_STATE_KEY = 'rider-studio:draw-state-v1';
const DRAW_TASK_KEY = 'rider-studio:draw-task-v1';
const DRAW_LAST_KEY = 'rider-studio:draw-last-v1';
const DRAW_STATE_VERSION = 2;
function drawConfig() {
  return getRuntimeConfig().draw;
}

export const MAX_GROUP_COUNT = drawConfig().max_group_count;
export const MAX_TOTAL_COUNT = drawConfig().max_total_count;

interface DrawState {
  model: string;
  groups: DrawGroup[];
  negativePrompt: string;
  width: number;
  height: number;
  steps: number | null;
  cfg: number;
  loras: string[];
  loraStrengthModel: number;
  loraStrengthClip: number;
  loraStrengths: Record<string, { model: number; clip: number }>;
  lorasVersion: number;
  generating: boolean;
  status: string;
  batchId: string;
  total: number;
  done: number;
  results: DrawResult[];
  restoreVersion: number;
  [key: string]: unknown;
}

interface DrawLastSnapshot {
  v: 1;
  kind: 'batch' | 'preview';
  batchId?: string;
  result?: DrawResult;
}

const defaultPrompt = drawConfig().default_prompt;

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

function parseLorasJson(value: string): string[] {
  const text = value.trim();
  if (!text || text === '[]') return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return text
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }
}

function promptTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function withGlobalNegative(
  document: PromptDocumentV1,
  negativePrompt: string,
): PromptDocumentV1 {
  const next = normalizePromptDocument(document);
  const existing = new Set(next.negative.custom.tags.map((tag) => tag.toLowerCase()));
  for (const tag of promptTags(negativePrompt)) {
    if (!existing.has(tag.toLowerCase())) {
      next.negative.custom.tags.push(tag);
      existing.add(tag.toLowerCase());
    }
  }
  return next;
}

function documentForGroupRequest(
  group: DrawGroup,
  negativePrompt: string,
): PromptDocumentV1 | null {
  if (group.mode === 'structured') {
    return withGlobalNegative(
      group.prompt_document || createEmptyStructuredDocument(),
      negativePrompt,
    );
  }
  if (isBodyProfileEmpty(group.body_profile)) return null;
  return withGlobalNegative(
    createStructuredDocumentFromLegacy(group.prompt, negativePrompt, group.body_profile),
    negativePrompt,
  );
}

export function loadDrawState(): DrawPersistState | null {
  try {
    const config = drawConfig();
    let raw = localStorage.getItem(DRAW_STATE_KEY);
    let sourceVersion = DRAW_STATE_VERSION;
    if (!raw) {
      raw = localStorage.getItem(LEGACY_DRAW_STATE_KEY);
      sourceVersion = 1;
    }
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DrawPersistState> & { v?: number };
    if (!parsed || parsed.v !== sourceVersion) return null;
    const groups = Array.isArray(parsed.groups)
      ? parsed.groups.filter(
          (group): group is DrawGroup => {
            const candidate = group as Partial<DrawGroup>;
            return (
              !!candidate &&
              typeof candidate.id === 'string' &&
              typeof candidate.prompt === 'string' &&
              typeof candidate.count === 'number'
            );
          },
        )
      : [];
    if (groups.length === 0) return null;
    const rawStrengths = parsed.loraStrengths as Record<string, { model?: unknown; clip?: unknown }> | undefined;
    const loraStrengths: Record<string, { model: number; clip: number }> = {};
    if (rawStrengths) {
      for (const [name, value] of Object.entries(rawStrengths)) {
        if (value && typeof value.model === 'number' && typeof value.clip === 'number') {
          loraStrengths[name] = {
            model: clampNumber(
              value.model,
              config.lora_strength_min,
              config.lora_strength_max,
              config.default_lora_strength_model,
            ),
            clip: clampNumber(
              value.clip,
              config.lora_strength_min,
              config.lora_strength_max,
              config.default_lora_strength_clip,
            ),
          };
        }
      }
    }
    return {
      model: typeof parsed.model === 'string' && parsed.model ? parsed.model : config.default_model,
      groups: groups.map((group) => {
        const mode: PromptDocumentMode = sourceVersion === 1 ? 'legacy' : group.mode === 'structured' ? 'structured' : 'legacy';
        const document =
          sourceVersion === 1
            ? createLegacyDocument(group.prompt, typeof parsed.negativePrompt === 'string' ? parsed.negativePrompt : '')
            : group.prompt_document
              ? normalizePromptDocument(group.prompt_document)
              : mode === 'structured'
                ? createEmptyStructuredDocument()
                : createLegacyDocument(group.prompt);
        return {
          ...group,
          mode,
          body_profile: normalizeBodyProfile(group.body_profile),
          prompt_document: document,
          count: clampNumber(
            group.count,
            config.group_count_min,
            config.max_group_count,
            config.group_count_min,
          ),
        };
      }),
      negativePrompt:
        typeof parsed.negativePrompt === 'string'
          ? parsed.negativePrompt
          : config.default_negative_prompt,
      width: clampNumber(parsed.width, config.width_min, config.width_max, config.default_width),
      height: clampNumber(parsed.height, config.height_min, config.height_max, config.default_height),
      steps:
        parsed.steps == null
          ? null
          : clampNumber(parsed.steps, config.steps_min, config.steps_max, config.default_steps),
      cfg: clampNumber(parsed.cfg, config.cfg_min, config.cfg_max, config.default_cfg),
      loras: Array.isArray(parsed.loras) ? parsed.loras.filter((item): item is string => typeof item === 'string') : [],
      loraStrengthModel: clampNumber(
        parsed.loraStrengthModel,
        config.lora_strength_min,
        config.lora_strength_max,
        config.default_lora_strength_model,
      ),
      loraStrengthClip: clampNumber(
        parsed.loraStrengthClip,
        config.lora_strength_min,
        config.lora_strength_max,
        config.default_lora_strength_clip,
      ),
      loraStrengths,
    };
  } catch {
    return null;
  }
}

export function saveDrawState(state: DrawPersistState): void {
  try {
    localStorage.setItem(DRAW_STATE_KEY, JSON.stringify({ v: DRAW_STATE_VERSION, ...state }));
  } catch {
    // 隐私模式或存储满时静默失败
  }
}

function saveDrawTask(batchId: string): void {
  try {
    localStorage.setItem(DRAW_TASK_KEY, JSON.stringify({ batchId }));
  } catch {
    // 忽略存储失败
  }
}

function clearDrawTask(): void {
  try {
    localStorage.removeItem(DRAW_TASK_KEY);
  } catch {
    // 忽略存储失败
  }
}

function loadDrawTask(): string {
  try {
    const raw = localStorage.getItem(DRAW_TASK_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { batchId?: string };
      if (parsed?.batchId) return parsed.batchId;
    }
  } catch {
    // 忽略解析失败
  }
  return '';
}

function saveDrawLast(snapshot: DrawLastSnapshot): void {
  try {
    localStorage.setItem(DRAW_LAST_KEY, JSON.stringify(snapshot));
  } catch {
    // 忽略存储失败
  }
}

function loadDrawLast(): DrawLastSnapshot | null {
  try {
    const raw = localStorage.getItem(DRAW_LAST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DrawLastSnapshot>;
    if (parsed?.v !== 1) return null;
    if (parsed.kind === 'batch' && typeof parsed.batchId === 'string' && parsed.batchId) {
      return { v: 1, kind: 'batch', batchId: parsed.batchId };
    }
    if (parsed.kind === 'preview' && parsed.result?.image_url) {
      return { v: 1, kind: 'preview', result: parsed.result };
    }
    return null;
  } catch {
    return null;
  }
}

function clearDrawLast(): void {
  try {
    localStorage.removeItem(DRAW_LAST_KEY);
  } catch {
    // 忽略存储失败
  }
}

const saved = loadDrawState();
const drawDefaults = drawConfig();

export const drawStore = useStore<DrawState>({
  model: saved?.model ?? drawDefaults.default_model,
  groups: saved?.groups ?? [createDrawGroup(defaultPrompt, 'group-1', 'legacy')],
  negativePrompt: saved?.negativePrompt ?? drawDefaults.default_negative_prompt,
  width: saved?.width ?? drawDefaults.default_width,
  height: saved?.height ?? drawDefaults.default_height,
  steps: saved ? saved.steps ?? null : drawDefaults.default_steps,
  cfg: saved?.cfg ?? drawDefaults.default_cfg,
  loras: saved?.loras ?? [],
  loraStrengthModel: saved?.loraStrengthModel ?? drawDefaults.default_lora_strength_model,
  loraStrengthClip: saved?.loraStrengthClip ?? drawDefaults.default_lora_strength_clip,
  loraStrengths: saved?.loraStrengths ?? {},
  lorasVersion: 0,
  generating: false,
  status: '',
  batchId: '',
  total: 0,
  done: 0,
  results: [],
  restoreVersion: 0,
});

function nextGroupId(): string {
  return `group-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

export function createDrawGroup(
  prompt = '',
  id = nextGroupId(),
  mode: PromptDocumentMode = 'structured',
): DrawGroup {
  return {
    id,
    prompt,
    mode,
    body_profile: createBodyProfile(),
    prompt_document:
      mode === 'legacy' ? createLegacyDocument(prompt) : createEmptyStructuredDocument(),
    count: drawConfig().group_count_min,
    enabled: true,
  };
}

export function createNewPromptGroup(): DrawGroup {
  return createDrawGroup('', nextGroupId(), 'legacy');
}

export function addGroup(): DrawGroup {
  const group = createNewPromptGroup();
  drawStore.groups = [...drawStore.groups, group];
  return group;
}

export function removeGroup(id: string): void {
  if (drawStore.groups.length <= 1) return;
  drawStore.groups = drawStore.groups.filter((group) => group.id !== id);
}

export function moveGroupTo(sourceId: string, targetId: string): void {
  if (sourceId === targetId) return;
  const next = [...drawStore.groups];
  const sourceIndex = next.findIndex((group) => group.id === sourceId);
  const targetIndex = next.findIndex((group) => group.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0) return;
  const [moved] = next.splice(sourceIndex, 1);
  next.splice(targetIndex, 0, moved);
  drawStore.groups = next;
}

export function duplicateGroup(id: string): DrawGroup | null {
  const source = drawStore.groups.find((group) => group.id === id);
  if (!source) return null;
  const copy: DrawGroup = {
    ...source,
    id: nextGroupId(),
    prompt_document: source.prompt_document
      ? normalizePromptDocument(source.prompt_document)
      : null,
  };
  const index = drawStore.groups.findIndex((group) => group.id === id);
  const next = [...drawStore.groups];
  next.splice(index + 1, 0, copy);
  drawStore.groups = next;
  return copy;
}

export function updateGroupPrompt(id: string, prompt: string): void {
  drawStore.groups = drawStore.groups.map((group) => {
    if (group.id !== id) return group;
    if (group.mode === 'legacy') {
      return {
        ...group,
        prompt,
        prompt_document: createLegacyDocument(prompt, drawStore.negativePrompt),
      };
    }
    return {
      ...group,
      prompt,
      prompt_document: normalizePromptDocument({
        ...(group.prompt_document || createEmptyStructuredDocument()),
        custom: {
          ...(group.prompt_document?.custom || { global_tags: [], user_notes: '' }),
          global_tags: promptTags(prompt),
        },
      }),
    };
  });
}

export function updateLegacyBodyProfile(
  id: string,
  field: keyof PromptBodyProfile,
  value: PromptHeightFrame | PromptBodyBuild,
): void {
  drawStore.groups = drawStore.groups.map((group) =>
    group.id === id && group.mode === 'legacy'
      ? {
          ...group,
          body_profile: createBodyProfile({
            ...group.body_profile,
            [field]: value,
          }),
        }
      : group,
  );
}

export function updateGroupDocument(id: string, document: PromptDocumentV1): void {
  const normalized = normalizePromptDocument(document);
  drawStore.groups = drawStore.groups.map((group) =>
    group.id === id ? { ...group, prompt_document: normalized, mode: normalized.mode } : group,
  );
}

export function setGroupMode(id: string, mode: PromptDocumentMode): void {
  drawStore.groups = drawStore.groups.map((group) => {
    if (group.id !== id || group.mode === mode) return group;
    if (mode === 'legacy') {
      const firstCharacter =
        group.prompt_document?.characters.find((character) => character.enabled !== false) ||
        group.prompt_document?.characters[0];
      return {
        ...group,
        mode,
        body_profile: normalizeBodyProfile(firstCharacter || group.body_profile),
        prompt_document: createLegacyDocument(group.prompt, drawStore.negativePrompt),
      };
    }
    const document = createStructuredDocumentFromLegacy(
      group.prompt,
      drawStore.negativePrompt,
      group.body_profile,
    );
    return { ...group, mode, prompt_document: document };
  });
}

export function groupHasPrompt(group: DrawGroup): boolean {
  return group.mode === 'legacy'
    ? Boolean(group.prompt.trim())
    : !isPromptDocumentEmpty(group.prompt_document);
}

export function updateGroupCount(id: string, count: number): void {
  const config = drawConfig();
  const clamped = Math.min(
    Math.max(config.group_count_min, Math.round(count || config.group_count_min)),
    config.max_group_count,
  );
  const totalAfter = drawStore.groups.reduce(
    (sum, group) =>
      sum +
      (group.id === id
        ? clamped
        : Math.min(Math.max(config.group_count_min, group.count), config.max_group_count)),
    0,
  );
  if (totalAfter > config.max_total_count) {
    message.warning(`总张数最多 ${config.max_total_count} 张，请先减少其他组张数`);
    return;
  }
  drawStore.groups = drawStore.groups.map((group) => (group.id === id ? { ...group, count: clamped } : group));
}

export function updateGroupEnabled(id: string, enabled: boolean): void {
  drawStore.groups = drawStore.groups.map((group) =>
    group.id === id ? { ...group, enabled } : group,
  );
}

async function validatePrompts(): Promise<boolean> {
  const issues: string[] = [];
  let hardBlocked = false;
  for (const group of drawStore.groups) {
    if (group.enabled === false) continue;
    if (!groupHasPrompt(group)) continue;
    try {
      const document = documentForGroupRequest(group, drawStore.negativePrompt);
      if (document) {
        const { data } = await api.post<PromptDocumentResolveResult>(
          '/prompt-agent/resolve-prompt-document',
          { document },
        );
        for (const issue of [...data.errors, ...data.warnings]) issues.push(issue);
        if (data.blocked) hardBlocked = true;
        if (group.mode === 'structured' && data.prompt) {
          drawStore.groups = drawStore.groups.map((item) =>
            item.id === group.id ? { ...item, prompt: data.prompt } : item,
          );
        }
        continue;
      }
      const prompt = group.prompt.trim();
      const { data } = await api.post<PromptValidation>('/prompt/validate', {
        prompt,
        negative_prompt: drawStore.negativePrompt,
      });
      for (const issue of [...data.errors, ...data.warnings]) issues.push(issue.message);
    } catch {
      // 校验接口失败不阻止生成
    }
  }
  if (issues.length > 0) {
    Modal.warning({
      title: hardBlocked ? '内容限制阻止生成' : '提示词校验提醒',
      content: issues.map((item, index) => `${index + 1}. ${item}`).join('\n'),
    });
  }
  return !hardBlocked;
}

async function pollBatch(batchId: string): Promise<void> {
  drawStore.batchId = batchId;
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const jobRes = await api.get<BatchJob>(`/draw/batch/${batchId}`);
    const job = jobRes.data;
    drawStore.total = job.total;
    drawStore.done = job.done;
    drawStore.results = job.results || [];
    drawStore.status =
      job.status === 'running'
        ? `正在生成 ${job.done}/${job.total} 张`
        : job.status === 'done'
          ? '生成完成'
          : job.status === 'stopped'
            ? '已停止'
            : job.status === 'interrupted'
              ? '上次任务被中断'
              : `生成失败：${job.error || ''}`;
    if (job.status === 'done' || job.status === 'error' || job.status === 'stopped' || job.status === 'interrupted') break;
  }
  saveDrawLast({ v: 1, kind: 'batch', batchId });
}

// 提交批量绘画任务并轮询进度
export async function runDraw(): Promise<void> {
  if (drawStore.generating) return;
  const config = drawConfig();
  if (
    drawStore.steps == null ||
    Number.isNaN(drawStore.steps) ||
    drawStore.steps < config.steps_min ||
    drawStore.steps > config.steps_max
  ) {
    message.warning(`请填写步数（${config.steps_min}-${config.steps_max}）`);
    return;
  }
  const proposedTotal = drawStore.groups.reduce(
    (sum, group) => sum + (group.enabled === false ? 0 : group.count),
    0,
  );
  if (proposedTotal > config.max_total_count) {
    message.warning(`总张数最多 ${config.max_total_count} 张，请先减少各组张数`);
    return;
  }
  const block = await busyBlockMessage();
  if (block) {
    showBusyWarning(block);
    return;
  }
  if (!(await validatePrompts())) return;
  const groups: DrawGroupInput[] = drawStore.groups
    .filter((group) => group.enabled !== false && groupHasPrompt(group))
    .map((group) => ({
      prompt: group.prompt.trim(),
      prompt_document: documentForGroupRequest(group, drawStore.negativePrompt),
      count: Math.min(
        Math.max(config.group_count_min, group.count),
        config.max_group_count,
      ),
    }));
  if (groups.length === 0) {
    drawStore.status = '请至少填写一组提示词';
    return;
  }
  drawStore.generating = true;
  drawStore.status = '正在提交任务...';
  drawStore.results = [];
  drawStore.batchId = '';
  drawStore.done = 0;
  drawStore.total = groups.reduce((sum, group) => sum + group.count, 0);
  clearDrawLast();
  try {
    const { data } = await api.post<{ batch_id: string; total: number; status: string }>('/draw/batch', {
      model: drawStore.model,
      negative_prompt: drawStore.negativePrompt,
      width: drawStore.width,
      height: drawStore.height,
      steps: drawStore.steps,
      cfg: drawStore.cfg,
      loras: drawStore.loras,
      lora_strength_model: drawStore.loraStrengthModel,
      lora_strength_clip: drawStore.loraStrengthClip,
      lora_strengths: drawStore.loraStrengths,
      groups,
    });
    drawStore.batchId = data.batch_id;
    drawStore.total = data.total;
    saveDrawTask(data.batch_id);
    await pollBatch(data.batch_id);
  } catch (e) {
    drawStore.status = `生成失败：${(e as Error).message}`;
  } finally {
    drawStore.generating = false;
    clearDrawTask();
  }
}

// 用相同或随机 seed 重新生成当前第一组提示词
export async function regenerateCurrent(seed?: number): Promise<void> {
  const group = drawStore.groups.find(groupHasPrompt);
  if (!group) {
    drawStore.status = '请至少填写一组提示词';
    return;
  }
  const config = drawConfig();
  if (
    drawStore.steps == null ||
    Number.isNaN(drawStore.steps) ||
    drawStore.steps < config.steps_min ||
    drawStore.steps > config.steps_max
  ) {
    message.warning(`请填写步数（${config.steps_min}-${config.steps_max}）`);
    return;
  }
  const block = await busyBlockMessage();
  if (block) {
    showBusyWarning(block);
    return;
  }
  if (!(await validatePrompts())) return;
  drawStore.generating = true;
  drawStore.status = seed ? '正在以相同 seed 重新生成...' : '正在重新生成...';
  drawStore.results = [];
  drawStore.done = 0;
  drawStore.total = 1;
  drawStore.batchId = '';
  clearDrawLast();
  try {
    const { data } = await api.post<{ batch_id: string; total: number; status: string }>('/draw/batch', {
      model: drawStore.model,
      negative_prompt: drawStore.negativePrompt,
      width: drawStore.width,
      height: drawStore.height,
      steps: drawStore.steps,
      cfg: drawStore.cfg,
      loras: drawStore.loras,
      lora_strength_model: drawStore.loraStrengthModel,
      lora_strength_clip: drawStore.loraStrengthClip,
      lora_strengths: drawStore.loraStrengths,
      seed: seed ?? undefined,
      groups: [
        {
          prompt: group.prompt.trim(),
          prompt_document: documentForGroupRequest(group, drawStore.negativePrompt),
          count: 1,
        },
      ],
    });
    drawStore.batchId = data.batch_id;
    drawStore.total = data.total;
    saveDrawTask(data.batch_id);
    await pollBatch(data.batch_id);
  } catch (e) {
    drawStore.status = `生成失败：${(e as Error).message}`;
  } finally {
    drawStore.generating = false;
    clearDrawTask();
  }
}

export function restoreDrawRecord(record: {
  prompt?: string;
  negative_prompt?: string;
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  model?: string;
  image_url?: string;
  seed?: number | null;
  loras_json?: string | string[] | null;
  prompt_document_json?: string;
}): void {
  if (drawStore.groups.length === 0) {
    drawStore.groups = [createDrawGroup('', 'group-1', 'legacy')];
  }
  let document = createLegacyDocument(record.prompt || '', record.negative_prompt || '');
  if (record.prompt_document_json) {
    try {
      const parsed = JSON.parse(record.prompt_document_json) as PromptDocumentV1;
      if (parsed && typeof parsed === 'object') document = normalizePromptDocument(parsed);
    } catch {
      // 无效快照回退为旧文本文档
    }
  }
  drawStore.groups = [
    {
      ...drawStore.groups[0],
      prompt: record.prompt || document.raw_override.prompt || '',
      prompt_document: document,
      mode: document.mode,
      body_profile: normalizeBodyProfile(
        document.characters[0] || drawStore.groups[0].body_profile,
      ),
    },
  ];
  drawStore.negativePrompt = record.negative_prompt || '';
  if (record.width) drawStore.width = record.width;
  if (record.height) drawStore.height = record.height;
  if (record.steps) drawStore.steps = record.steps;
  if (record.cfg) drawStore.cfg = record.cfg;
  if (record.model) drawStore.model = record.model;
  if (record.loras_json != null) {
    const raw = record.loras_json;
    const parsed: string[] = Array.isArray(raw) ? raw : parseLorasJson(raw);
    if (Array.isArray(parsed)) {
      drawStore.loras = parsed.filter((name): name is string => typeof name === 'string' && Boolean(name));
    }
  }
  drawStore.results = record.image_url ? [{ image_url: record.image_url, seed: record.seed ?? undefined }] : [];
  drawStore.status = record.image_url ? '已恢复历史记录预览' : '已恢复历史记录配置';
  drawStore.restoreVersion += 1;
  if (record.image_url) {
    saveDrawLast({ v: 1, kind: 'preview', result: { image_url: record.image_url, seed: record.seed ?? undefined } });
  } else {
    clearDrawLast();
  }
  uiStore.activeTab = 'draw';
}

// 页面刷新后恢复未完成的绘画任务
export async function resumeDrawTask(): Promise<boolean> {
  const batchId = loadDrawTask();
  if (!batchId || drawStore.generating) return false;
  drawStore.generating = true;
  drawStore.status = '正在恢复历史任务...';
  try {
    await pollBatch(batchId);
    return true;
  } catch (e) {
    drawStore.status = `任务恢复失败：${(e as Error).message}`;
    return false;
  } finally {
    drawStore.generating = false;
    clearDrawTask();
  }
}

// 刷新后恢复上一次完成的结果（批量任务由后端 batch_jobs 回捞，历史预览用快照）
export async function restoreDrawLast(): Promise<void> {
  const snapshot = loadDrawLast();
  if (!snapshot) return;
  if (snapshot.kind === 'preview' && snapshot.result?.image_url) {
    drawStore.results = [snapshot.result];
    drawStore.status = '已恢复上次预览结果';
    return;
  }
  if (snapshot.kind !== 'batch' || !snapshot.batchId) return;
  try {
    const { data } = await api.get<BatchJob>(`/draw/batch/${snapshot.batchId}`);
    if (!data || !Array.isArray(data.results)) {
      clearDrawLast();
      return;
    }
    drawStore.total = data.total || 0;
    drawStore.done = data.done || 0;
    drawStore.results = data.results || [];
    drawStore.status = data.status === 'done' ? '已恢复上次生成结果' : `上次结果：${data.status || '未完成'}`;
    if (data.status === 'running') {
      // 运行中的任务交给 resumeDrawTask 轮询，这里只回填已完成快照
      clearDrawLast();
    }
  } catch {
    clearDrawLast();
  }
}

// 清空当前结果与上次结果快照（仅新任务开始或用户主动清空时调用）
export function clearDrawResult(): void {
  clearDrawLast();
  drawStore.results = [];
  drawStore.status = '';
  drawStore.batchId = '';
  drawStore.done = 0;
  drawStore.total = 0;
}

// 停止当前批量绘画任务
export async function stopDraw(): Promise<void> {
  if (!drawStore.batchId || !drawStore.generating) return;
  drawStore.status = '正在停止...';
  try {
    await api.post(`/draw/batch/${drawStore.batchId}/stop`);
  } catch (e) {
    drawStore.status = `停止失败：${(e as Error).message}`;
  }
}
