import { spawn, type ChildProcess } from 'child_process';
import net from 'net';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

// 后端地址与启动参数
const BACKEND_PORT = 8500;
const BACKEND_DIR = 'D:/workSpace/code/骑手招聘助手/studio/backend';
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
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8500',
    },
  },
});
