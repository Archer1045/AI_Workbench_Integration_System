// API 客户端与前后端交互的通用类型
import axios from 'axios';

// 后端统一走 /api，Vite 开发服务器代理到 127.0.0.1:8500
export const api = axios.create({
  baseURL: '/api',
  timeout: 600000,
});

export interface ServiceStatus {
  ollama: boolean;
  comfyui: boolean;
}

export interface DrawResult {
  prompt_id?: string;
  image_url: string;
  comfy_url?: string;
  saved_path?: string;
  seed?: number;
  elapsed?: number;
  group_index?: number;
  image_index?: number;
}

export interface DrawGroupInput {
  prompt: string;
  count: number;
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
}

export interface LoraItem {
  name: string;
  size_mb: number;
}

export interface ModelItem {
  name: string;
  size_mb: number;
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
  source_text?: string;
  filename?: string;
}
