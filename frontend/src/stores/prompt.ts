// 提示词 Agent 状态
import useStore from 'resso';
import { api, type PromptAgentResult } from '../api';
import { busyBlockMessage, showBusyWarning } from './busy';
import { createDrawGroup, drawStore, runDraw } from './draw';
import { uiStore } from './ui';

interface PromptState {
  mode: 'image' | 'text';
  reverseMode: 'hybrid' | 'wd14' | 'vlm';
  reverseThreshold: number;
  imageBase64: string | null;
  imageName: string;
  text: string;
  result: PromptAgentResult | null;
  status: string;
  autoDraw: boolean;
  [key: string]: unknown;
}

// 反推模式与 WD14 阈值：与打标面板同源（0.1~0.9，默认 0.35），刷新后仍保留上次选择。
// 注意：必须在 store 创建之前声明——store 初始化会立即调用 loadReverseState()，
// 若常量声明在其后，读取会命中 TDZ 并被 catch 吞掉，导致刷新后永远退回默认档（2026-10-11 修复）。
const REVERSE_STATE_KEY = 'rider-studio:prompt-reverse-v1';

function clampThreshold(value: unknown): number {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return 0.35;
  return Math.min(0.9, Math.max(0.1, num));
}

export function loadReverseState(): { reverseMode: 'hybrid' | 'wd14' | 'vlm'; reverseThreshold: number } {
  try {
    const raw = localStorage.getItem(REVERSE_STATE_KEY);
    if (!raw) return { reverseMode: 'hybrid', reverseThreshold: 0.35 };
    const parsed = JSON.parse(raw) as { mode?: string; threshold?: number };
    const mode = parsed.mode === 'wd14' || parsed.mode === 'vlm' ? parsed.mode : 'hybrid';
    return { reverseMode: mode, reverseThreshold: clampThreshold(parsed.threshold) };
  } catch {
    return { reverseMode: 'hybrid', reverseThreshold: 0.35 };
  }
}

export function setReverseOptions(mode: 'hybrid' | 'wd14' | 'vlm', threshold: number): void {
  promptStore.reverseMode = mode;
  promptStore.reverseThreshold = clampThreshold(threshold);
  try {
    localStorage.setItem(
      REVERSE_STATE_KEY,
      JSON.stringify({ mode, threshold: clampThreshold(threshold) }),
    );
  } catch {
    // 隐私模式下静默失败
  }
}

export const promptStore = useStore<PromptState>({
  mode: 'image',
  reverseMode: loadReverseState().reverseMode,
  reverseThreshold: loadReverseState().reverseThreshold,
  imageBase64: null,
  imageName: '',
  text: '',
  result: null,
  status: '',
  autoDraw: false,
});

function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
  return detail || (error instanceof Error ? error.message : fallback);
}

// 图片反推提示词
export async function fromImage(): Promise<void> {
  if (!promptStore.imageBase64) {
    promptStore.status = '请先选择图片';
    return;
  }
  // wd14 只跑本地 CPU 分类器（毫秒级、不占显存），不需要等待其他任务空闲。
  if (promptStore.reverseMode !== 'wd14') {
    const block = await busyBlockMessage();
    if (block) {
      promptStore.status = block;
      showBusyWarning(block);
      return;
    }
  }
  promptStore.status = '正在识别图片...';
  promptStore.result = null;
  try {
    const { data } = await api.post<PromptAgentResult>('/prompt/from-image', {
      image_base64: promptStore.imageBase64,
      filename: promptStore.imageName || 'image.png',
      mode: promptStore.reverseMode,
      threshold: promptStore.reverseThreshold,
    });
    promptStore.result = data;
    promptStore.status = '识别完成';
  } catch (e) {
    promptStore.status = `识别失败：${apiErrorMessage(e, '请稍后重试')}`;
  }
}

// 自然语言生成提示词
export async function fromText(): Promise<void> {
  const text = promptStore.text.trim();
  if (!text) {
    promptStore.status = '请先输入描述';
    return;
  }
  const block = await busyBlockMessage();
  if (block) {
    promptStore.status = block;
    showBusyWarning(block);
    return;
  }
  promptStore.status = '正在生成提示词...';
  promptStore.result = null;
  try {
    const { data } = await api.post<PromptAgentResult>('/prompt/from-text', { text });
    promptStore.result = data;
    promptStore.status = '生成完成';
  } catch (e) {
    promptStore.status = `生成失败：${apiErrorMessage(e, '请稍后重试')}`;
  }
}

// 发送到绘画区，可选自动开始生成
export function sendToDraw(): void {
  const prompt = promptStore.result?.prompt;
  if (!prompt) {
    promptStore.status = '请先生成提示词';
    return;
  }
  if (drawStore.groups.length === 0) {
    drawStore.groups = [createDrawGroup('', 'group-1', 'legacy')];
  }
  drawStore.groups = [{ ...drawStore.groups[0], prompt }];
  uiStore.activeTab = 'draw';
  if (promptStore.autoDraw) {
    void runDraw();
  }
}
