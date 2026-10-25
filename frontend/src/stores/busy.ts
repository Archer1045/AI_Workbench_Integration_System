// 资源忙碌状态：供 AI 绘画 / 训练 / 打标 / 陪伴发送做跨项目冲突拦截
import { Modal } from 'antd';
import useStore from 'resso';
import { api } from '../api';

export interface BusyTask {
  type: string;
  label: string;
}

interface BusyState {
  busy: boolean;
  tasks: BusyTask[];
  [key: string]: unknown;
}

export const busyStore = useStore<BusyState>({
  busy: false,
  tasks: [],
});

export async function refreshBusy(): Promise<void> {
  try {
    const { data } = await api.get<{ busy: boolean; tasks: BusyTask[] }>('/system/busy');
    busyStore.busy = Boolean(data.busy);
    busyStore.tasks = data.tasks || [];
  } catch {
    busyStore.busy = false;
    busyStore.tasks = [];
  }
}

export function busyMessage(tasks: BusyTask[]): string {
  const labels = tasks.map((item) => item.label).join('、');
  return labels ? `有其他项目正在运行（${labels}），请稍后再进行` : '有其他项目正在运行，请稍后再进行';
}

export async function busyBlockMessage(): Promise<string | null> {
  await refreshBusy();
  return busyStore.busy ? busyMessage(busyStore.tasks) : null;
}

export function showBusyWarning(message: string): void {
  Modal.warning({
    title: '资源冲突',
    content: message,
  });
}
