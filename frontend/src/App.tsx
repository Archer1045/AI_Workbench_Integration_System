// 工作台主布局：服务状态栏 + 四个工作区
import { Button, Layout, Space, Switch, Tabs, Tag } from "antd";
import { useEffect } from "react";
import AgentChat from "./components/AgentChat";
import DrawPanel from "./components/DrawPanel";
import PromptAgent from "./components/PromptAgent";
import RecordsPanel from "./components/RecordsPanel";
import {
  refreshServices,
  servicesStore,
  toggleService,
} from "./stores/services";
import {
  loadSettings,
  settingsStore,
  toggleRestriction,
} from "./stores/settings";
import { uiStore, type TabKey } from "./stores/ui";

const tabItems = [
  { key: "agent", label: "招聘 Agent", children: <AgentChat /> },
  { key: "draw", label: "AI 绘画", children: <DrawPanel /> },
  { key: "prompt", label: "提示词 Agent", children: <PromptAgent /> },
  { key: "records", label: "数据看板", children: <RecordsPanel /> },
];

export default function App() {
  const { ollama, comfyui, loading } = servicesStore;
  const { restrictionEnabled, loading: settingsLoading } = settingsStore;

  // 启动时和后端保持服务状态同步
  useEffect(() => {
    void refreshServices();
    void loadSettings();
    const timer = setInterval(() => void refreshServices(), 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <Layout className="app-layout">
      <Layout.Header className="app-header">
        <div className="brand">AI 工作台</div>
        <Space wrap>
          <Switch
            checked={restrictionEnabled}
            loading={settingsLoading}
            onChange={(checked) => void toggleRestriction(checked)}
          />
          <span>内容限制</span>
          <Tag color={ollama ? "green" : "red"}>
            Ollama {ollama ? "运行中" : "未运行"}
          </Tag>
          <Button
            size="small"
            loading={loading}
            onClick={() => void toggleService("ollama", !ollama)}
          >
            {ollama ? "停止" : "启动"}
          </Button>
          <Tag color={comfyui ? "green" : "red"}>
            ComfyUI {comfyui ? "运行中" : "未运行"}
          </Tag>
          <Button
            size="small"
            loading={loading}
            onClick={() => void toggleService("comfyui", !comfyui)}
          >
            {comfyui ? "停止" : "启动"}
          </Button>
        </Space>
      </Layout.Header>
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
