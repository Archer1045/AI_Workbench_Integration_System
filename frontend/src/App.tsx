// 工作台主布局：服务状态栏 + 四个工作区
import { Button, Layout, Space, Switch, Tabs, Tag, Tooltip } from "antd";
import { lazy, Suspense, useEffect } from "react";
import AutoShutdownBanner from "./components/AutoShutdownBanner";
import GpuMonitor from "./components/GpuMonitor";
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

const AIDrawingWorkspace = lazy(() => import("./components/AIDrawingWorkspace"));
const GameAssistantPanel = lazy(() => import("./components/GameAssistantPanel"));
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

const tabItems = [
  { key: "draw", label: "AI 绘画", children: <Suspense fallback={<PanelFallback />}><AIDrawingWorkspace /></Suspense> },
  { key: "gameAssistant", label: "游戏助手", children: <Suspense fallback={<PanelFallback />}><GameAssistantPanel /></Suspense> },
  { key: "video", label: "AI 动画", children: <Suspense fallback={<PanelFallback />}><VideoPanel /></Suspense> },
  { key: "train", label: "LoRA 训练", children: <Suspense fallback={<PanelFallback />}><TrainPanel /></Suspense> },
  { key: "prompt", label: "提示词 Agent", children: <Suspense fallback={<PanelFallback />}><PromptAgent /></Suspense> },
  { key: "presetLibrary", label: "预设库", children: <Suspense fallback={<PanelFallback />}><PresetLibraryPanel /></Suspense> },
  { key: "presetAssets", label: "预设工坊", children: <Suspense fallback={<PanelFallback />}><PresetAssetWorkshopPanel /></Suspense> },
  { key: "records", label: "数据看板", children: <Suspense fallback={<PanelFallback />}><RecordsPanel /></Suspense> },
  { key: "companion", label: "情感陪伴", children: <Suspense fallback={<PanelFallback />}><CompanionPanel /></Suspense> },
  { key: "agent", label: "招聘 Agent", children: <Suspense fallback={<PanelFallback />}><AgentChat /></Suspense> },
  { key: "settings", label: "全局设置", children: <Suspense fallback={<PanelFallback />}><SettingsPanel /></Suspense> },
];

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

  return (
    <Layout className="app-layout">
      <Layout.Header className="app-header">
        <div className="brand">AI工作台</div>
        <Space wrap>
          <GpuMonitor />
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
        />
      </Layout.Content>
    </Layout>
  );
}
