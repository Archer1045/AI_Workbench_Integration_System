// 提示词 Agent 状态
import useStore from 'resso';
import { api, type PromptAgentResult } from '../api';
import { drawStore, runDraw } from './draw';
import { uiStore } from './ui';

interface PromptState {
  mode: 'image' | 'text';
  imageBase64: string | null;
  imageName: string;
  text: string;
  result: PromptAgentResult | null;
  status: string;
  autoDraw: boolean;
  [key: string]: unknown;
}

export const promptStore = useStore<PromptState>({
  mode: 'image',
  imageBase64: null,
  imageName: '',
  text: '',
  result: null,
  status: '',
  autoDraw: false,
});

// 图片反推提示词
export async function fromImage(): Promise<void> {
  if (!promptStore.imageBase64) {
    promptStore.status = '请先选择图片';
    return;
  }
  promptStore.status = '正在识别图片...';
  promptStore.result = null;
  try {
    const { data } = await api.post<PromptAgentResult>('/prompt/from-image', {
      image_base64: promptStore.imageBase64,
      filename: promptStore.imageName || 'image.png',
    });
    promptStore.result = data;
    promptStore.status = '识别完成';
  } catch (e) {
    promptStore.status = `识别失败：${(e as Error).message}`;
  }
}

// 自然语言生成提示词
export async function fromText(): Promise<void> {
  const text = promptStore.text.trim();
  if (!text) {
    promptStore.status = '请先输入描述';
    return;
  }
  promptStore.status = '正在生成提示词...';
  promptStore.result = null;
  try {
    const { data } = await api.post<PromptAgentResult>('/prompt/from-text', { text });
    promptStore.result = data;
    promptStore.status = '生成完成';
  } catch (e) {
    promptStore.status = `生成失败：${(e as Error).message}`;
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
    drawStore.groups = [{ id: 'group-1', prompt: '', count: 1 }];
  }
  drawStore.groups = [{ ...drawStore.groups[0], prompt }];
  uiStore.activeTab = 'draw';
  if (promptStore.autoDraw) {
    void runDraw();
  }
}
