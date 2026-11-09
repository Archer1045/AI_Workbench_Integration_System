// 工作台主布局：服务状态栏 + 四个工作区
import { Button, Layout, Menu, Space, Switch, Tabs, Tag, Tooltip } from "antd";
import { lazy, Suspense, useEffect } from "react";
import AutoShutdownBanner from "./components/AutoShutdownBanner";
import GpuMonitor from "./components/GpuMonitor";
import TaskNotificationControl from "./components/TaskNotificationControl";
import {
  refreshServices,
  servicesStore,
  toggleService,
} from "./stores/services";
import { autoShutdownStore, loadAutoShutdown } from "./stores/autoShutdown";
import { refreshBusy } from "./stores/busy";
import {
  loadSettings,
  settingsStore,
  toggleRestriction,
} from "./stores/settings";
import { uiStore, type TabKey } from "./stores/ui";
import { NAV_GROUPS } from "./navigation";

const AIDrawingWorkspace = lazy(() => import("./components/AIDrawingWorkspace"));
const GameAssistantPanel = lazy(() => import("./components/GameAssistantPanel"));
const McPanel = lazy(() => import("./components/McPanel"));
const AkPanel = lazy(() => import("./components/AkPanel"));
const FgoPanel = lazy(() => import("./components/FgoPanel"));
const HsrPanel = lazy(() => import("./components/HsrPanel"));
const AgentPanel = lazy(() => import("./components/AgentPanel"));
const AzurPanel = lazy(() => import("./components/AzurPanel"));
const VideoPanel = lazy(() => import("./components/VideoPanel"));
const TrainPanel = lazy(() => import("./components/TrainPanel"));
const PromptAgent = lazy(() => import("./components/PromptAgent"));
const PresetAssetWorkshopPanel = lazy(() => import("./components/PresetAssetWorkshopPanel"));
const PresetLibraryPanel = lazy(() => import("./components/PresetLibraryPanel"));
const RecordsPanel = lazy(() => import("./components/RecordsPanel"));
const CompanionPanel = lazy(() => import("./components/CompanionPanel"));
const AgentChat = lazy(() => import("./components/AgentChat"));
const SettingsPanel = lazy(() => import("./components/SettingsPanel"));

function PanelFallback() {
  return <div className="tab-loading">加载中...</div>;
}

// 面板与 TabKey 的映射：导航结构由 navigation.ts 决定，这里只负责渲染
const PANELS: Record<TabKey, { label: string; render: () => JSX.Element }> = {
  draw: { label: "AI 绘画", render: () => <AIDrawingWorkspace /> },
  gameAssistant: { label: "游戏助手", render: () => <GameAssistantPanel /> },
  mcAssistant: { label: "我的世界", render: () => <McPanel /> },
  akAssistant: { label: "明日方舟", render: () => <AkPanel /> },
  fgoAssistant: { label: "FGO", render: () => <FgoPanel /> },
  hsrAssistant: { label: "星穹铁道", render: () => <HsrPanel /> },
  agentAssistant: { label: "总助手", render: () => <AgentPanel /> },
  azurAssistant: { label: "碧蓝航线", render: () => <AzurPanel /> },
  video: { label: "AI 动画", render: () => <VideoPanel /> },
  train: { label: "LoRA 训练", render: () => <TrainPanel /> },
  prompt: { label: "提示词 Agent", render: () => <PromptAgent /> },
  presetLibrary: { label: "预设库", render: () => <PresetLibraryPanel /> },
  presetAssets: { label: "预设工坊", render: () => <PresetAssetWorkshopPanel /> },
  records: { label: "数据看板", render: () => <RecordsPanel /> },
  companion: { label: "情感陪伴", render: () => <CompanionPanel /> },
  agent: { label: "招聘 Agent", render: () => <AgentChat /> },
  settings: { label: "全局设置", render: () => <SettingsPanel /> },
};

const tabItems = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({
    key: item.key,
    label: PANELS[item.key].label,
    children: <Suspense fallback={<PanelFallback />}>{PANELS[item.key].render()}</Suspense>,
  })),
);

export default function App() {
  const { ollama, comfyui, loading } = servicesStore;
  const { restrictionEnabled, loading: settingsLoading } = settingsStore;

  // 启动时和后端保持服务状态同步
  useEffect(() => {
    void refreshServices();
    void refreshBusy();
    void loadSettings();
    void loadAutoShutdown().catch(() => undefined);
    const timer = setInterval(() => {
      void refreshServices();
      void refreshBusy();
      if (autoShutdownStore.enabled) {
        void loadAutoShutdown().catch(() => undefined);
      }
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  // 顶部导航：分组菜单，选中项跟随 activeTab
  const navItems = NAV_GROUPS.map((group) => {
    if (group.items.length === 1) {
      return { key: group.items[0].key, label: group.label };
    }
    return {
      key: group.key,
      label: group.label,
      children: group.items.map((item) => ({ key: item.key, label: item.label })),
    };
  });

  return (
    <Layout className="app-layout">
      <Layout.Header className="app-header">
        <div className="brand">AI工作台</div>
        <Menu
          mode="horizontal"
          selectedKeys={[uiStore.activeTab]}
          items={navItems}
          onClick={({ key }) => {
            if (PANELS[key as TabKey]) {
              uiStore.activeTab = key as TabKey;
            }
          }}
          className="app-nav"
          disabledOverflow
        />
        <Space wrap className="app-header-actions">
          <GpuMonitor />
          <TaskNotificationControl />
          <Tooltip title="全局内容限制：影响 AI 绘画、提示词 Agent 与情感陪伴；开启后拦截 NSFW 关键词，未成年相关内容始终拦截。">
            <Space>
              <Switch
                checked={restrictionEnabled}
                loading={settingsLoading}
                onChange={(checked) => void toggleRestriction(checked)}
              />
              <span>内容限制</span>
            </Space>
          </Tooltip>
          <Tag color={ollama ? "green" : "red"}>
            Ollama {ollama ? "运行中" : "未运行"}
          </Tag>
          <Button
            size="small"
            loading={loading.ollama}
            onClick={() => void toggleService("ollama", !ollama)}
          >
            {ollama ? "停止" : "启动"}
          </Button>
          <Tag color={comfyui ? "green" : "red"}>
            ComfyUI {comfyui ? "运行中" : "未运行"}
          </Tag>
          <Button
            size="small"
            loading={loading.comfyui}
            onClick={() => void toggleService("comfyui", !comfyui)}
          >
            {comfyui ? "停止" : "启动"}
          </Button>
        </Space>
      </Layout.Header>
      <AutoShutdownBanner />
      <Layout.Content className="app-content">
        <Tabs
          activeKey={uiStore.activeTab}
          onChange={(key) => {
            uiStore.activeTab = key as TabKey;
          }}
          items={tabItems}
          tabBarStyle={{ display: "none" }}
        />
      </Layout.Content>
    </Layout>
  );
}
