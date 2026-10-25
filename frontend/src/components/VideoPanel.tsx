// AI 视频：单镜头剧本 + i2v 生成任务 + 成片库
import {
  DeleteOutlined,
  ExperimentOutlined,
  FolderOpenOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  StopOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Button,
  Input,
  InputNumber,
  message,
  Popconfirm,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useRef, useState } from 'react';
import {
  api,
  type VideoJobStatus,
  type VideoRecord,
  type VideoScriptItem,
  type VideoScriptPayload,
} from '../api';
import { busyBlockMessage, showBusyWarning } from '../stores/busy';
import { getRuntimeConfig } from '../stores/runtimeConfig';
import { settingsStore } from '../stores/settings';

const { TextArea } = Input;
const VIDEO_TASK_KEY = 'rider-studio:video-task-v1';
const VIDEO_STATE_KEY = 'rider-studio:video-state-v1';

interface KeyframeItem {
  name: string;
  url: string;
}

interface VideoPersistState {
  storyInput: string;
  prompt: string;
  negativePrompt: string;
  selectedKeyframe: string;
  frames: number;
  size: string;
  steps: number;
  cfg: number;
  denoise: number;
  loraStrength: number;
  seedText: string;
}

function clamp(value: unknown, min: number, max: number, fallback: number): number {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

function loadVideoState(): VideoPersistState | null {
  try {
    const raw = localStorage.getItem(VIDEO_STATE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<VideoPersistState> & { v?: number };
    if (!parsed || parsed.v !== 1) return null;
    const config = getRuntimeConfig().video;
    const size =
      typeof parsed.size === 'string' &&
      config.allowed_sizes.some(([width, height]) => `${width}×${height}` === parsed.size)
        ? parsed.size
        : `${config.default_width}×${config.default_height}`;
    return {
      storyInput: typeof parsed.storyInput === 'string' ? parsed.storyInput : '',
      prompt: typeof parsed.prompt === 'string' ? parsed.prompt : '',
      negativePrompt:
        typeof parsed.negativePrompt === 'string' ? parsed.negativePrompt : '',
      selectedKeyframe:
        typeof parsed.selectedKeyframe === 'string' ? parsed.selectedKeyframe : '',
      frames: config.allowed_frames.includes(Number(parsed.frames))
        ? Number(parsed.frames)
        : config.default_frames,
      size,
      steps: clamp(parsed.steps, config.steps_min, config.steps_max, config.default_steps),
      cfg: clamp(parsed.cfg, config.cfg_min, config.cfg_max, config.default_cfg),
      denoise: clamp(
        parsed.denoise,
        config.denoise_min,
        config.denoise_max,
        config.default_denoise,
      ),
      loraStrength: clamp(
        parsed.loraStrength,
        config.lora_strength_min,
        config.lora_strength_max,
        config.default_lora_strength,
      ),
      seedText: typeof parsed.seedText === 'string' ? parsed.seedText : '',
    };
  } catch {
    return null;
  }
}

function saveVideoState(state: VideoPersistState): void {
  try {
    localStorage.setItem(VIDEO_STATE_KEY, JSON.stringify({ v: 1, ...state }));
  } catch {
    // 隐私模式或存储满时静默失败
  }
}

function terminalStatus(status?: string): boolean {
  return !status || ['done', 'error', 'stopped', 'interrupted'].includes(status);
}

function statusText(status?: string): string {
  if (status === 'running') return '生成中';
  if (status === 'done') return '完成';
  if (status === 'error') return '失败';
  if (status === 'stopped') return '已停止';
  if (status === 'interrupted') return '已中断';
  return String(status || '-');
}

export default function VideoPanel() {
  const { restrictionEnabled } = settingsStore;
  const videoConfig = getRuntimeConfig().video;
  const [savedState] = useState<VideoPersistState | null>(loadVideoState);
  const [storyInput, setStoryInput] = useState(savedState?.storyInput || '');
  const [scriptLoading, setScriptLoading] = useState(false);
  const [script, setScript] = useState<VideoScriptItem | null>(null);
  const [keyframes, setKeyframes] = useState<KeyframeItem[]>([]);
  const [selectedKeyframe, setSelectedKeyframe] = useState(savedState?.selectedKeyframe || '');
  const [prompt, setPrompt] = useState(savedState?.prompt || '');
  const [negativePrompt, setNegativePrompt] = useState(savedState?.negativePrompt || '');
  const [frames, setFrames] = useState<number>(savedState?.frames ?? videoConfig.default_frames);
  const [size, setSize] = useState(
    savedState?.size ?? `${videoConfig.default_width}×${videoConfig.default_height}`,
  );
  const [steps, setSteps] = useState(savedState?.steps ?? videoConfig.default_steps);
  const [cfg, setCfg] = useState(savedState?.cfg ?? videoConfig.default_cfg);
  const [denoise, setDenoise] = useState(savedState?.denoise ?? videoConfig.default_denoise);
  const [loraStrength, setLoraStrength] = useState(
    savedState?.loraStrength ?? videoConfig.default_lora_strength,
  );
  const [seedText, setSeedText] = useState(savedState?.seedText || '');
  const [generating, setGenerating] = useState(false);
  const [activeRecord, setActiveRecord] = useState<VideoRecord | null>(null);
  const [activeTask, setActiveTask] = useState<{
    status?: string;
    current?: string;
    total?: number;
    done?: number;
  } | null>(null);
  const [library, setLibrary] = useState<VideoRecord[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const jobIdRef = useRef('');

  const loadKeyframes = async () => {
    try {
      const { data } = await api.get<{ items: KeyframeItem[] }>('/video/keyframes');
      setKeyframes(data.items || []);
      const stillExists = data.items.some((item) => item.name === selectedKeyframe);
      if ((!selectedKeyframe || !stillExists) && data.items.length > 0) {
        setSelectedKeyframe(data.items[0].name);
      }
    } catch {
      // 后端未就绪时保持空列表
    }
  };

  const loadLibrary = async () => {
    setLibraryLoading(true);
    try {
      const { data } = await api.get<{ items: VideoRecord[] }>('/video/library');
      setLibrary(data.items || []);
    } catch {
      setLibrary([]);
    } finally {
      setLibraryLoading(false);
    }
  };

  const pollJob = async (jobId: string) => {
    try {
      const { data } = await api.get<VideoJobStatus>(`/video/jobs/${jobId}`);
      setActiveRecord(data.record || null);
      setActiveTask(data.task || null);
      if (data.record && terminalStatus(data.record.status) && data.record.video_url) {
        await loadLibrary();
      }
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        jobIdRef.current = '';
        setActiveRecord(null);
        setActiveTask(null);
        try {
          localStorage.removeItem(VIDEO_TASK_KEY);
        } catch {
          // 忽略本地清理失败
        }
      }
    }
  };

  useEffect(() => {
    void loadKeyframes();
    void loadLibrary();
    try {
      const saved = localStorage.getItem(VIDEO_TASK_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as { jobId?: string };
        if (parsed?.jobId) {
          jobIdRef.current = parsed.jobId;
          void pollJob(parsed.jobId);
        }
      }
    } catch {
      // 忽略本地恢复失败
    }
    const timer = window.setInterval(() => {
      void loadKeyframes();
      if (jobIdRef.current) void pollJob(jobIdRef.current);
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    saveVideoState({
      storyInput,
      prompt,
      negativePrompt,
      selectedKeyframe,
      frames,
      size,
      steps,
      cfg,
      denoise,
      loraStrength,
      seedText,
    });
  }, [
    storyInput,
    prompt,
    negativePrompt,
    selectedKeyframe,
    frames,
    size,
    steps,
    cfg,
    denoise,
    loraStrength,
    seedText,
  ]);

  useEffect(() => {
    if (refreshKey > 0) {
      void loadLibrary();
    }
  }, [refreshKey]);

  const handleGenerateScript = async () => {
    if (!storyInput.trim()) {
      message.warning('请先输入剧情描述');
      return;
    }
    setScriptLoading(true);
    try {
      const { data } = await api.post<{ script_id: number; script: VideoScriptPayload }>('/video/script', {
        input: storyInput,
      });
      setScript({
        id: data.script_id,
        source_input: storyInput,
        script: data.script,
        model: '',
        content_limited: false,
        created_at: '',
      });
      setPrompt(data.script.prompt);
      setNegativePrompt(data.script.negative_prompt || '');
      message.success('剧本已生成');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '剧本生成失败');
    } finally {
      setScriptLoading(false);
    }
  };

  const handleUploadKeyframe = async (file: File) => {
    if (!file.type.startsWith('image/')) {
      message.warning('请选择图片文件');
      return;
    }
    if (file.size > videoConfig.keyframe_max_bytes) {
      message.error(`图片不能超过 ${Math.round(videoConfig.keyframe_max_bytes / 1024 / 1024)}MB`);
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const { data } = await api.post<KeyframeItem>('/video/keyframes', {
          name: file.name,
          data: String(reader.result || ''),
        });
        setSelectedKeyframe(data.name);
        await loadKeyframes();
        message.success('关键帧已上传');
      } catch (error) {
        const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        message.error(detail || '关键帧上传失败');
      }
    };
    reader.onerror = () => message.error('读取图片失败');
    reader.readAsDataURL(file);
  };

  const handleGenerate = async () => {
    if (!selectedKeyframe) {
      message.warning('请先上传或选择关键帧');
      return;
    }
    if (!prompt.trim()) {
      message.warning('正向提示词不能为空');
      return;
    }
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    const [widthText, heightText] = size.split('×');
    const payload: Record<string, unknown> = {
      keyframe_name: selectedKeyframe,
      prompt,
      negative_prompt: negativePrompt,
      script_id: script?.id,
      frames,
      width: Number(widthText),
      height: Number(heightText),
      steps,
      cfg,
      denoise,
      lora_strength: loraStrength,
      use_lora: true,
    };
    if (seedText.trim()) {
      const seed = Number(seedText.trim());
      if (!Number.isInteger(seed) || seed < videoConfig.seed_min) {
        message.error('随机种子必须是正整数');
        return;
      }
      payload.seed = seed;
    }
    setGenerating(true);
    try {
      const { data } = await api.post<{ job_id: string; status: string }>('/video/generate', payload);
      jobIdRef.current = data.job_id;
      try {
        localStorage.setItem(VIDEO_TASK_KEY, JSON.stringify({ jobId: data.job_id }));
      } catch {
        // 存储失败不阻断任务
      }
      setActiveRecord(null);
      setActiveTask({ status: 'running' });
      void pollJob(data.job_id);
      message.success('视频任务已提交');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '视频生成提交失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleStop = async () => {
    if (!jobIdRef.current) return;
    try {
      await api.post(`/video/jobs/${jobIdRef.current}/stop`);
      message.success('已请求停止');
      void pollJob(jobIdRef.current);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '停止失败');
    }
  };

  const handleDelete = async (recordId: number) => {
    try {
      await api.delete(`/video/library/${recordId}`);
      setRefreshKey((value) => value + 1);
      message.success('已删除');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '删除失败');
    }
  };

  const videoRunning =
    activeRecord?.status === 'running' || (!activeRecord && activeTask?.status === 'running');
  const doneRatio =
    activeTask && Number(activeTask.total)
      ? Math.min(100, Math.round(((Number(activeTask.done) || 0) / Number(activeTask.total)) * 100))
      : videoRunning
        ? 35
        : 0;

  const columns: ColumnsType<VideoRecord> = [
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value: string) => value || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (value: string, record) => (
        <Tooltip title={record.error || ''}>
          <Tag color={value === 'done' ? 'green' : value === 'running' ? 'blue' : value === 'error' ? 'red' : 'orange'}>
            {statusText(value)}
          </Tag>
        </Tooltip>
      ),
    },
    {
      title: '参数',
      key: 'params',
      width: 160,
      render: (_, record) => (
        <span className="video-param-text">
          {record.width}×{record.height} · {record.frames}f @ {record.fps || videoConfig.default_fps}fps
        </span>
      ),
    },
    {
      title: '预览',
      key: 'preview',
      width: 220,
      render: (_, record) =>
        record.video_url ? (
          <video className="video-preview-video" controls preload="metadata" src={record.video_url} />
        ) : (
          <span className="video-empty-text">无成片</span>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      fixed: 'right',
      render: (_, record) => (
        <Popconfirm title="删除该视频记录与本地文件？" onConfirm={() => void handleDelete(record.id)}>
          <Button size="small" icon={<DeleteOutlined />} danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div className="panel-box video-layout">
      <div className="video-create">
        <div className="video-block">
          <div className="video-block-header">
            <b>单镜头剧本</b>
            <Tag>{restrictionEnabled ? '内容限制开启' : '内容限制关闭'}</Tag>
          </div>
          <TextArea
            value={storyInput}
            onChange={(event) => setStoryInput(event.target.value)}
            rows={3}
            maxLength={videoConfig.script_max_length}
            placeholder="例如：夜晚的街道，少女从低头走路到转身回望…"
          />
          <div className="video-toolbar">
            <Button icon={<ExperimentOutlined />} onClick={() => void handleGenerateScript()} loading={scriptLoading}>
              生成剧本
            </Button>
          </div>
          {script ? (
            <div className="video-script-result">
              <div className="video-param-text">
                场景：{script.script.scene || '-'}；动作：{script.script.action || '-'}；情绪：
                {script.script.mood || '-'}
              </div>
            </div>
          ) : null}
          <div className="video-block-label">正向提示词</div>
          <TextArea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} />
          <div className="video-block-label">负面提示词</div>
          <TextArea value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} rows={2} />
        </div>

        <div className="video-block">
          <div className="video-block-header">
            <b>关键帧</b>
            <Space wrap>
              <Upload
                accept="image/*"
                showUploadList={false}
                beforeUpload={() => false}
                onChange={(info) => {
                  const file = info.file.originFileObj;
                  if (file) void handleUploadKeyframe(file);
                }}
              >
                <Button size="small" icon={<UploadOutlined />}>
                  上传
                </Button>
              </Upload>
              <Button
                size="small"
                icon={<FolderOpenOutlined />}
                onClick={() => void api.post('/video/open-keyframes').catch(() => undefined)}
              >
                打开目录
              </Button>
            </Space>
          </div>
          {keyframes.length === 0 ? (
            <div className="video-empty-text">暂无关键帧</div>
          ) : (
            <div className="video-key-grid">
              {keyframes.map((item) => (
                <button
                  key={item.name}
                  type="button"
                  className={`video-key-item ${selectedKeyframe === item.name ? 'active' : ''}`}
                  onClick={() => setSelectedKeyframe(item.name)}
                  title={item.name}
                >
                  <img src={item.url} alt={item.name} />
                  <span>{item.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="video-block">
          <div className="video-block-header">
            <b>生成参数</b>
            <Tag color="blue">Wan2.1 I2V 14B fp8 + NSFW LoRA</Tag>
          </div>
          <div className="video-form-row">
            <span className="video-label">帧数</span>
            <Select
              value={frames}
              onChange={setFrames}
              options={videoConfig.allowed_frames.map((value) => ({
                label: `${value} 帧 · 约 ${(value / videoConfig.default_fps).toFixed(1)} 秒${
                  value === videoConfig.default_frames ? '（推荐）' : ''
                }`,
                value,
              }))}
            />
            <span className="video-label">分辨率</span>
            <Segmented
              value={size}
              onChange={(value) => setSize(String(value))}
              options={videoConfig.allowed_sizes.map(([width, height]) => ({
                label: `${width}×${height}`,
                value: `${width}×${height}`,
              }))}
            />
            <span className="video-label">步数</span>
            <InputNumber
              min={videoConfig.steps_min}
              max={videoConfig.steps_max}
              value={steps}
              onChange={(value) => setSteps(value ?? videoConfig.default_steps)}
              style={{ width: 90 }}
            />
            <span className="video-label">CFG</span>
            <InputNumber
              min={videoConfig.cfg_min}
              max={videoConfig.cfg_max}
              step={videoConfig.cfg_step}
              value={cfg}
              onChange={(value) => setCfg(value ?? videoConfig.default_cfg)}
              style={{ width: 90 }}
            />
            <span className="video-label">降噪</span>
            <InputNumber
              min={videoConfig.denoise_min}
              max={videoConfig.denoise_max}
              step={videoConfig.denoise_step}
              value={denoise}
              onChange={(value) => setDenoise(value ?? videoConfig.default_denoise)}
              style={{ width: 90 }}
            />
            <span className="video-label">LoRA 强度</span>
            <InputNumber
              min={videoConfig.lora_strength_min}
              max={videoConfig.lora_strength_max}
              step={videoConfig.lora_strength_step}
              value={loraStrength}
              onChange={(value) => setLoraStrength(value ?? videoConfig.default_lora_strength)}
              style={{ width: 90 }}
            />
            <span className="video-label">随机种子</span>
            <InputNumber
              value={seedText === '' ? undefined : Number(seedText)}
              onChange={(value) => setSeedText(value == null ? '' : String(value))}
              min={videoConfig.seed_min}
              style={{ width: 130 }}
              placeholder="随机"
            />
          </div>
          <div className="video-toolbar">
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={generating}
              disabled={videoRunning}
              onClick={() => void handleGenerate()}
            >
              生成视频
            </Button>
            {videoRunning ? (
              <Button icon={<StopOutlined />} onClick={() => void handleStop()}>
                停止
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="video-side">
        <div className="video-block">
          <div className="video-block-header">
            <b>当前任务</b>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => {
                if (jobIdRef.current) void pollJob(jobIdRef.current);
                setRefreshKey((value) => value + 1);
              }}
            >
              刷新
            </Button>
          </div>
          {!jobIdRef.current && !activeRecord ? (
            <div className="video-empty-text">暂无任务</div>
          ) : (
            <div className="video-status-box">
              <div>
                <Tag color={videoRunning ? 'blue' : 'green'}>{statusText(activeRecord?.status || activeTask?.status)}</Tag>
                <span className="video-current-text">{activeRecord?.video_name || activeTask?.current || activeRecord?.job_id}</span>
              </div>
              {videoRunning ? <Progress percent={doneRatio} size="small" /> : null}
              {activeRecord?.error ? <div className="video-error-text">{activeRecord.error}</div> : null}
              {activeRecord?.video_url ? (
                <video className="video-preview-video wide" controls src={activeRecord.video_url} />
              ) : null}
            </div>
          )}
        </div>

        <div className="video-block">
          <div className="video-block-header">
            <b>视频库</b>
            <Button
              size="small"
              icon={<FolderOpenOutlined />}
              onClick={() => void api.post('/video/open-library').catch(() => undefined)}
            >
              打开目录
            </Button>
          </div>
          <Table
            rowKey="id"
            columns={columns}
            dataSource={library}
            loading={libraryLoading}
            size="small"
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 760 }}
          />
        </div>
      </div>
    </div>
  );
}
