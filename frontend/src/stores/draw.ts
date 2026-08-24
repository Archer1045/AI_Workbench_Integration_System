// AI 绘画状态：多组提示词批量生成
import useStore from 'resso';
import { api, type BatchJob, type DrawGroupInput, type DrawResult } from '../api';

export interface DrawGroup {
  id: string;
  prompt: string;
  count: number;
}

interface DrawState {
  model: string;
  groups: DrawGroup[];
  negativePrompt: string;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  loras: string[];
  generating: boolean;
  status: string;
  batchId: string;
  total: number;
  done: number;
  results: DrawResult[];
  [key: string]: unknown;
}

const defaultPrompt =
  'uncensored, masterpiece, score 7, highres, absurdres, best quality, very aesthetic, anime coloring, 1girl, solo, long hair, blue eyes, school uniform, sailor collar, white shirt, pleated skirt, looking at viewer, smile, upper body, simple background, cherry blossoms';

export const drawStore = useStore<DrawState>({
  model: 'chosenMixAnima_v10.safetensors',
  groups: [{ id: 'group-1', prompt: defaultPrompt, count: 1 }],
  negativePrompt:
    'worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, lowres, signature, mosaic_censored, bar_censor, text_censor, censored, censor, censor_bar, blur_censor, pixelated, mosaic, censorship',
  width: 1080,
  height: 1920,
  steps: 18,
  cfg: 1,
  loras: [],
  generating: false,
  status: '',
  batchId: '',
  total: 0,
  done: 0,
  results: [],
});

function nextGroupId(): string {
  return `group-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

export function addGroup(): void {
  drawStore.groups = [...drawStore.groups, { id: nextGroupId(), prompt: '', count: 1 }];
}

export function removeGroup(id: string): void {
  if (drawStore.groups.length <= 1) return;
  drawStore.groups = drawStore.groups.filter((group) => group.id !== id);
}

export function updateGroupPrompt(id: string, prompt: string): void {
  drawStore.groups = drawStore.groups.map((group) => (group.id === id ? { ...group, prompt } : group));
}

export function updateGroupCount(id: string, count: number): void {
  drawStore.groups = drawStore.groups.map((group) => (group.id === id ? { ...group, count } : group));
}

// 提交批量绘画任务并轮询进度
export async function runDraw(): Promise<void> {
  if (drawStore.generating) return;
  const groups: DrawGroupInput[] = drawStore.groups
    .filter((group) => group.prompt.trim())
    .map((group) => ({ prompt: group.prompt.trim(), count: Math.min(Math.max(1, group.count), 10) }));
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
  try {
    const { data } = await api.post<{ batch_id: string; total: number; status: string }>('/draw/batch', {
      model: drawStore.model,
      negative_prompt: drawStore.negativePrompt,
      width: drawStore.width,
      height: drawStore.height,
      steps: drawStore.steps,
      cfg: drawStore.cfg,
      loras: drawStore.loras,
      groups,
    });
    drawStore.batchId = data.batch_id;
    drawStore.total = data.total;
    // 轮询任务进度，直到完成或失败
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const jobRes = await api.get<BatchJob>(`/draw/batch/${data.batch_id}`);
      const job = jobRes.data;
      drawStore.done = job.done;
      drawStore.results = job.results || [];
      drawStore.status =
        job.status === 'running'
          ? `正在生成 ${job.done}/${job.total} 张`
          : job.status === 'done'
            ? '生成完成'
            : `生成失败：${job.error || ''}`;
      if (job.status === 'done' || job.status === 'error') break;
    }
  } catch (e) {
    drawStore.status = `生成失败：${(e as Error).message}`;
  } finally {
    drawStore.generating = false;
  }
}
