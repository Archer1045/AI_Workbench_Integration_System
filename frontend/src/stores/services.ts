// Ollama / ComfyUI 服务状态
import useStore from 'resso';
import { api, type ServiceStatus } from '../api';

interface ServicesState {
  ollama: boolean;
  comfyui: boolean;
  loading: boolean;
  [key: string]: unknown;
}

export const servicesStore = useStore<ServicesState>({
  ollama: false,
  comfyui: false,
  loading: false,
});

// 刷新服务状态
export async function refreshServices(): Promise<void> {
  try {
    const { data } = await api.get<ServiceStatus>('/services');
    servicesStore.ollama = data.ollama;
    servicesStore.comfyui = data.comfyui;
  } catch (e) {
    // 后端未就绪时保持原状态
  }
}

// 启动或停止指定服务
export async function toggleService(name: 'ollama' | 'comfyui', start: boolean): Promise<void> {
  servicesStore.loading = true;
  try {
    await api.post(`/services/${start ? 'start' : 'stop'}`, { name });
  } finally {
    servicesStore.loading = false;
    await refreshServices();
  }
}
