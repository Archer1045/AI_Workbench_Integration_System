// Ollama / ComfyUI 服务状态
import useStore from 'resso';
import { api, type ServiceStatus } from '../api';

type ServiceName = 'ollama' | 'comfyui';

interface ServicesState {
  ollama: boolean;
  comfyui: boolean;
  loading: Record<ServiceName, boolean>;
  [key: string]: unknown;
}

export const servicesStore = useStore<ServicesState>({
  ollama: false,
  comfyui: false,
  loading: { ollama: false, comfyui: false },
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
export async function toggleService(name: ServiceName, start: boolean): Promise<void> {
  servicesStore.loading = { ...servicesStore.loading, [name]: true };
  try {
    await api.post(`/services/${start ? 'start' : 'stop'}`, { name });
  } finally {
    servicesStore.loading = { ...servicesStore.loading, [name]: false };
    await refreshServices();
  }
}
