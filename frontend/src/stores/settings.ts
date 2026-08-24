// 内容限制开关状态
import useStore from 'resso';
import { api } from '../api';

interface SettingsState {
  restrictionEnabled: boolean;
  loading: boolean;
  [key: string]: unknown;
}

export const settingsStore = useStore<SettingsState>({
  restrictionEnabled: false,
  loading: false,
});

// 读取当前内容限制状态
export async function loadSettings(): Promise<void> {
  try {
    const { data } = await api.get('/settings/content-restriction');
    settingsStore.restrictionEnabled = Boolean(data.enabled);
  } catch (e) {
    // 后端未就绪时保持默认
  }
}

// 切换内容限制
export async function toggleRestriction(enabled: boolean): Promise<void> {
  settingsStore.loading = true;
  try {
    await api.post('/settings/content-restriction', { enabled });
    settingsStore.restrictionEnabled = enabled;
  } finally {
    settingsStore.loading = false;
  }
}
