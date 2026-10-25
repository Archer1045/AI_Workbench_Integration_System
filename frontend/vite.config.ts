import { spawn, type ChildProcess } from 'child_process';
import net from 'net';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

// 后端地址与启动参数
const BACKEND_PORT = 8500;
const FRONTEND_PORT = 5173;
const BACKEND_DIR = process.env.AI_WORKBENCH_BACKEND_DIR || 'D:/workSpace/code/ai-workbench/studio/backend';
const PYTHON = 'D:/workSpace/code/.venv/Scripts/python.exe';

// 探测后端是否已经在运行
function checkBackend(): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect(BACKEND_PORT, '127.0.0.1');
    socket.setTimeout(800);
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.once('error', () => resolve(false));
  });
}

function checkFrontendPort(): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect(FRONTEND_PORT, '127.0.0.1');
    socket.setTimeout(800);
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.once('error', () => resolve(false));
  });
}

// 轮询等待后端健康
async function waitBackend(maxWaitMs = 30000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    if (await checkBackend()) return true;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}

// Vite 插件：前端启动时自动拉起后端
function autoStartBackend(): Plugin {
  let backendProcess: ChildProcess | null = null;

  return {
    name: 'auto-start-backend',
    configureServer(server) {
      // 重复实例校验：5173 被占用时直接退出，不再自动换端口
      void (async () => {
        if (await checkFrontendPort()) {
          console.error(`[frontend] 检测到端口 ${FRONTEND_PORT} 已有前端实例在运行，已停止启动。请复用现有实例，或先停止旧进程再启动。`);
          process.exit(1);
        }
      })();

      // 启动前端前先检查并拉起后端
      void (async () => {
        if (await checkBackend()) {
          console.log('[backend] 后端已在运行');
          return;
        }
        console.log('[backend] 后端未运行，自动启动...');
        backendProcess = spawn(PYTHON, ['run.py'], {
          cwd: BACKEND_DIR,
          stdio: 'inherit',
          windowsHide: true,
        });
        const ready = await waitBackend();
        console.log(ready ? '[backend] 后端已就绪' : '[backend] 后端启动超时');
      })();

      // 前端退出时关闭由前端拉起的后端
      const shutdown = () => {
        if (backendProcess) {
          backendProcess.kill();
        }
      };
      process.on('exit', shutdown);
      server.httpServer?.once('close', shutdown);
    },
  };
}

export default defineConfig({
  plugins: [react(), autoStartBackend()],
  server: {
    port: FRONTEND_PORT,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8500',
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-antd': ['antd', '@ant-design/icons'],
          'vendor-charts': ['@ant-design/charts', '@ant-design/plots'],
          'vendor-axios': ['axios'],
        },
      },
    },
  },
});
