// 工作台导航结构：分组定义，App.tsx 只负责渲染
import type { TabKey } from './stores/ui';

export type NavItem = {
  key: TabKey;
  label: string;
};

export type NavGroup = {
  key: string;
  label: string;
  items: NavItem[];
};

// 游戏助手使用频率高，单独成组并排在创作之后
export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'create',
    label: '创作',
    items: [
      { key: 'draw', label: 'AI 绘画' },
      { key: 'video', label: 'AI 动画' },
      { key: 'train', label: 'LoRA 训练' },
    ],
  },
  {
    key: 'gameGroup',
    label: '游戏助手',
    items: [
      { key: 'gameAssistant', label: '游戏助手' },
      { key: 'mcAssistant', label: '我的世界' },
      { key: 'akAssistant', label: '明日方舟' },
      { key: 'fgoAssistant', label: 'FGO' },
      { key: 'hsrAssistant', label: '星穹铁道' },
      { key: 'azurAssistant', label: '碧蓝航线' },
    ],
  },
  {
    key: 'assets',
    label: '资产',
    items: [
      { key: 'presetLibrary', label: '预设库' },
      { key: 'presetAssets', label: '预设工坊' },
      { key: 'prompt', label: '提示词 Agent' },
    ],
  },
  {
    key: 'system',
    label: '系统',
    items: [
      { key: 'records', label: '数据看板' },
      { key: 'settings', label: '全局设置' },
    ],
  },
  {
    key: 'more',
    label: '更多',
    items: [
      { key: 'companion', label: '情感陪伴' },
      { key: 'agent', label: '招聘 Agent' },
    ],
  },
];

// 单页面分组（分组内只有一项，渲染时可省略二级导航）
export const SINGLE_ITEM_GROUPS = new Set(['gameAssistant']);

export function findGroupByTab(tab: TabKey): NavGroup {
  const group = NAV_GROUPS.find((item) => item.items.some((sub) => sub.key === tab));
  return group ?? NAV_GROUPS[0];
}
