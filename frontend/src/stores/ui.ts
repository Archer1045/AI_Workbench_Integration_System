// 工作台当前激活的 Tab
import useStore from 'resso';

export type TabKey =
  | 'agent'
  | 'draw'
  | 'gameAssistant'
  | 'prompt'
  | 'presetLibrary'
  | 'presetAssets'
  | 'records'
  | 'train'
  | 'companion'
  | 'settings'
  | 'video';

export const uiStore = useStore<{ activeTab: TabKey }>({
  activeTab: 'draw',
});
