// 工作台当前激活的 Tab
import useStore from 'resso';

export type TabKey = 'agent' | 'draw' | 'prompt' | 'records';

export const uiStore = useStore<{ activeTab: TabKey }>({
  activeTab: 'agent',
});
