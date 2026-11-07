// 任务完成后自动关机：全局开关、状态与取消操作
import useStore from 'resso';
import { api, type AutoShutdownSettings } from '../api';
import { getRuntimeConfig } from './runtimeConfig';

type AutoShutdownState = AutoShutdownSettings & Record<string, unknown>;

const settingsConfig = getRuntimeConfig().settings;

export const autoShutdownStore = useStore<AutoShutdownState>({
  enabled: false,
  delay_seconds: settingsConfig.auto_shutdown_delay_default,
  phase: 'disabled',
  remaining_seconds: null,
  task_type: null,
  task_label: '',
  finished_at: null,
  shutdown_at: null,
  last_error: null,
});

export async function loadAutoShutdown(): Promise<AutoShutdownSettings> {
  const { data } = await api.get<AutoShutdownSettings>('/settings/auto-shutdown');
  Object.assign(autoShutdownStore, data);
  return data;
}

export async function saveAutoShutdown(payload: Partial<AutoShutdownSettings>): Promise<AutoShutdownSettings> {
  const { data } = await api.post<AutoShutdownSettings>('/settings/auto-shutdown', payload);
  Object.assign(autoShutdownStore, data);
  return data;
}

export async function cancelAutoShutdown(): Promise<AutoShutdownSettings> {
  const { data } = await api.post<AutoShutdownSettings>('/system/auto-shutdown/cancel');
  Object.assign(autoShutdownStore, data);
  return data;
}
