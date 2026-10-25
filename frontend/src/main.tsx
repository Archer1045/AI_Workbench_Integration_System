// 前端入口：挂载 React 应用并配置 antd 中文语言包
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import React from 'react';
import ReactDOM from 'react-dom/client';
import 'antd/dist/reset.css';
import './styles.css';
import { loadRuntimeConfig } from './stores/runtimeConfig';

async function bootstrap() {
  await loadRuntimeConfig();
  const { default: App } = await import('./App');
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <ConfigProvider locale={zhCN}>
        <App />
      </ConfigProvider>
    </React.StrictMode>,
  );
}

void bootstrap();
