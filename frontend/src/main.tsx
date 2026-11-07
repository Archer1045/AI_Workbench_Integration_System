// 前端入口：挂载 React 应用并配置 antd 中文语言包与主题 token
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import React from 'react';
import ReactDOM from 'react-dom/client';
import 'antd/dist/reset.css';
import './styles.css';
import { loadRuntimeConfig } from './stores/runtimeConfig';

// 与 styles.css 顶部的 :root 变量保持一致，改一处要同步另一处
const themeTokens = {
  token: {
    colorPrimary: '#2f6bff',
    colorInfo: '#2f6bff',
    colorSuccess: '#14a05a',
    colorWarning: '#d98324',
    colorError: '#d93a3a',
    colorBgLayout: '#f8fafc',
    colorBorder: '#e5e7eb',
    colorBorderSecondary: '#eef0f4',
    colorText: '#1f2937',
    colorTextSecondary: '#64748b',
    colorTextTertiary: '#94a3b8',
    borderRadius: 10,
    borderRadiusLG: 12,
    borderRadiusSM: 8,
    fontSize: 14,
    controlHeight: 34,
  },
};

async function bootstrap() {
  await loadRuntimeConfig();
  const { default: App } = await import('./App');
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <ConfigProvider locale={zhCN} theme={themeTokens}>
        <App />
      </ConfigProvider>
    </React.StrictMode>,
  );
}

void bootstrap();
