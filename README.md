# 骑手招聘助手 AI 工作台（前后端分离版）

统一入口，一个项目同时提供“招聘 Agent、AI 绘画、提示词 Agent、数据看板”四个工作区。

## 项目结构

```text
studio/
├── backend/                 # FastAPI 后端
│   ├── app.py               # 应用入口：CORS、路由装配、数据库初始化
│   ├── run.py               # 后端启动器（带单实例端口检查）
│   ├── database.py          # SQLite 数据层
│   ├── llm.py               # Ollama 对话调用（含流式）
│   ├── services.py          # Ollama / ComfyUI 进程管理
│   ├── comfy_worker.py      # Anima 文生图工作流
│   ├── prompt_agent.py      # 图片反推与文字转提示词
│   ├── requirements.txt     # 后端依赖
│   └── routers/             # 业务路由
│       ├── chat.py          # Agent 对话 + SSE 流式 + 翻译
│       ├── draw.py          # AI 绘画 + LoRA + 图片访问
│       ├── prompt.py        # 提示词 Agent
│       ├── records.py       # 数据看板 + Excel 导出
│       └── services_router.py
├── frontend/                # React 前端
│   ├── vite.config.ts       # 自动启动后端插件 + API 代理
│   └── src/
│       ├── stores/          # resso 状态管理
│       ├── components/      # 四个工作区组件
│       ├── api.ts           # axios 客户端
│       └── App.tsx          # 主布局
├── static/                  # 旧版单文件界面（保留备用）
└── main.py                  # 旧版入口（保留备用）
```

## 启动方式

### 推荐：只启动前端（会自动拉起后端）

```powershell
cd D:\workSpace\code\骑手招聘助手\studio\frontend
npm run dev
```

浏览器打开 `http://localhost:5173`。

`vite.config.ts` 中的插件会在前端启动时检查 `127.0.0.1:8500`，如果后端未运行，会自动执行：

```powershell
D:\workSpace\code\.venv\Scripts\python.exe run.py
```

前端退出时会关闭由它拉起的后端进程。

### 单独启动后端

```powershell
cd D:\workSpace\code\骑手招聘助手\studio\backend
D:\workSpace\code\.venv\Scripts\python.exe run.py
```

- API 文档：`http://127.0.0.1:8500/docs`
- 健康检查：`http://127.0.0.1:8500/health`

## 服务依赖

- Ollama：`D:\AI\Ollama\ollama.exe`，模型库 `D:\AI\Ollama\models`
- ComfyUI：`D:\AI\ComfyUI\venv\Scripts\python.exe`，端口 `8188`
- 手动启动脚本：
  - `D:\AI\start-ollama.cmd`
  - `D:\AI\start-comfyui.cmd`

## 内容限制

- 工作台顶部提供“内容限制”开关
- 开启后，AI 绘画和提示词 Agent 会拦截 NSFW 相关关键词
- 未成年相关内容（如萝莉、正太、loli、幼女等）无论开关状态都始终拦截

## 本地模型清单

### Ollama 大模型

- `qwen3:8b`：招聘 Agent 对话模型，约 5.2GB
- `qwen2.5vl:3b`：图片识别/提示词 Agent 视觉模型，约 3.2GB

### 向量模型

- `BAAI/bge-small-zh-v1.5`：RAG 向量检索模型（fastembed ONNX），约 90MB

### ComfyUI 绘画模型

- 底模：
  - `chosenMixAnima_v10.safetensors`：旧模型，约 3.9GB
  - `chosenIrisesMix_v20Anima.safetensors`：新模型，约 3.9GB
- 文本编码器：
  - `qwen_3_06b_base.safetensors`：Anima 文本编码器，约 1.1GB
  - `clip_l.safetensors`：Flux 备用，约 235MB
  - `t5xxl_fp8_e4m3fn.safetensors`：Flux 备用，约 4.6GB
- VAE：
  - `qwen_image_vae.safetensors`：Anima VAE，约 242MB
  - `flux-vae-bf16.safetensors`：Flux 备用，约 160MB
- LoRA：
  - `anima-turbo-lora-v0.2.safetensors`：约 142MB
  - `high-contrast aesthetic.safetensors`：约 43.9MB

## 四个工作区

1. 招聘 Agent：`qwen3:8b` 大模型 + 向量知识库，SSE 流式显示思考过程和回答；Ollama 未启动时自动回退纯检索。
2. AI 绘画：Anima 文生图，支持新旧底模选择、多组提示词批量生成（每组最多 10 张、单次最多 20 张），提示词/负面提示词实时中文翻译，LoRA 勾选，图片自动保存。
3. 提示词 Agent：图片反推（`qwen2.5vl:3b`）和自然语言转英文提示词，可发送到绘画区并选择自动生成。
4. 数据看板：按日筛选、分页（10/20/50/100）、导出 Excel。

## 数据库

- 位置：`D:\workSpace\code\骑手招聘助手\AIproduct\rider_studio.db`
- 表结构：
  - `agent_chat_records`：对话时间、发送人、内容、检索匹配度、来源
  - `draw_records`：批次ID、组号、底模、提示词、翻译、负面提示词、尺寸、步数、CFG、LoRA、耗时、图片路径、状态
  - `prompt_agent_records`：模式、输入、图片路径、描述、结果、耗时、状态

## 主要接口

- `GET /health`：健康检查
- `GET /api/services` / `POST /api/services/start` / `stop`
- `POST /api/chat/stream`：SSE 流式对话
- `POST /api/translate`：提示词翻译
- `GET /api/loras`、`GET /api/models`
- `POST /api/draw/batch`：提交批量绘画任务
- `GET /api/draw/batch/{id}`：查询任务进度
- `POST /api/draw`：单张绘画（兼容旧接口）
- `GET /api/images/{filename}`
- `POST /api/prompt/from-text`、`POST /api/prompt/from-image`
- `GET /api/records`、`GET /api/export/{kind}`

## 手动重启

```powershell
# 停止前端（在终端按 Ctrl+C），后端若由前端拉起会自动关闭
# 停止后端
Stop-Process -Id <后端 PID> -Force

# 重新启动
cd D:\workSpace\code\骑手招聘助手\studio\frontend
npm run dev
```

后端自带单实例检查：端口 `8500` 已被占用时会提示并退出。
