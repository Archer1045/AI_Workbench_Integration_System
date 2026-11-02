import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  message,
  Progress,
  Select,
  Space,
  Tag,
  Upload,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import {
  api,
  getLongVideoStatus,
  resumeLongVideo,
  startLongVideo,
  stopLongVideo,
  type LongVideoSegment,
  type LongVideoStatus,
} from '../api';
import { getRuntimeConfig } from '../stores/runtimeConfig';

const TASK_KEY = 'rider-studio:long-video-task-v1';

interface KeyframeItem {
  name: string;
  url: string;
}

function statusLabel(status: string): string {
  if (status === 'pending') return '等待';
  if (status === 'running') return '生成中';
  if (status === 'ready') return '已落盘';
  if (status === 'failed') return '失败';
  if (status === 'done') return '完成';
  if (status === 'stopped') return '已停止';
  if (status === 'interrupted') return '已中断';
  return status;
}

function statusColor(status: string): string {
  if (status === 'ready' || status === 'done') return 'green';
  if (status === 'running') return 'blue';
  if (status === 'failed') return 'red';
  if (status === 'stopped' || status === 'interrupted') return 'orange';
  return 'default';
}

export default function LongVideoPanel() {
  const videoConfig = getRuntimeConfig().video;
  const [keyframes, setKeyframes] = useState<KeyframeItem[]>([]);
  const [keyframe, setKeyframe] = useState('');
  const [prompts, setPrompts] = useState(['', '']);
  const [negativePrompt, setNegativePrompt] = useState(
    'worst quality, deformed, static, blurry, extra limbs, text, watermark',
  );
  const [frames, setFrames] = useState(videoConfig.default_frames);
  const [size, setSize] = useState(
    `${videoConfig.default_width}×${videoConfig.default_height}`,
  );
  const [steps, setSteps] = useState(videoConfig.default_steps);
  const [cfg, setCfg] = useState(videoConfig.default_cfg);
  const [denoise, setDenoise] = useState(videoConfig.default_denoise);
  const [seedText, setSeedText] = useState('');
  const [starting, setStarting] = useState(false);
  const [jobId, setJobId] = useState('');
  const [status, setStatus] = useState<LongVideoStatus | null>(null);
  const [error, setError] = useState('');
  const [resuming, setResuming] = useState<number | null>(null);
  const pollTimer = useRef<number | undefined>(undefined);

  const loadKeyframes = async () => {
    try {
      const response = await api.get<{ items: KeyframeItem[] }>(
        '/video/keyframes',
      );
      setKeyframes(response.data.items || []);
      setKeyframe((current) => {
        if (response.data.items.some((item) => item.name === current)) {
          return current;
        }
        return response.data.items[0]?.name || '';
      });
    } catch {
      setKeyframes([]);
    }
  };

  const poll = async (id: string) => {
    try {
      const value = await getLongVideoStatus(id);
      setStatus(value);
      setError('');
      if (value.state.status === 'running') {
        pollTimer.current = window.setTimeout(() => void poll(id), 3000);
      }
    } catch (requestFailure) {
      setError(
        (requestFailure as { response?: { data?: { detail?: string } } })
          .response?.data?.detail || '读取长视频任务失败',
      );
    }
  };

  useEffect(() => {
    void loadKeyframes();
    try {
      const stored = localStorage.getItem(TASK_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as { jobId?: string };
        if (parsed.jobId) {
          setJobId(parsed.jobId);
          void poll(parsed.jobId);
        }
      }
    } catch {
      // Ignore stale local task state.
    }
    return () => {
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!jobId || status) return;
    void poll(jobId);
  }, [jobId, status]);

  const saveJob = (id: string) => {
    setJobId(id);
    try {
      localStorage.setItem(TASK_KEY, JSON.stringify({ jobId: id }));
    } catch {
      // The backend checkpoint is authoritative.
    }
  };

  const updatePrompt = (index: number, value: string) => {
    setPrompts((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? value : item)),
    );
  };

  const movePrompt = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= prompts.length) return;
    setPrompts((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const removePrompt = (index: number) => {
    if (prompts.length <= 2) {
      message.warning('长视频至少保留两个分段');
      return;
    }
    setPrompts((current) =>
      current.filter((_, itemIndex) => itemIndex !== index),
    );
  };

  const uploadKeyframe = async (file: File) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const response = await api.post<KeyframeItem>('/video/keyframes', {
          name: file.name,
          data: String(reader.result || ''),
        });
        await loadKeyframes();
        setKeyframe(response.data.name);
      } catch (requestFailure) {
        message.error(
          (requestFailure as { response?: { data?: { detail?: string } } })
            .response?.data?.detail || '关键帧上传失败',
        );
      }
    };
    reader.readAsDataURL(file);
  };

  const start = async () => {
    if (!keyframe) {
      message.warning('请先选择关键帧');
      return;
    }
    if (prompts.some((prompt) => !prompt.trim())) {
      message.warning('每个分段都必须填写提示词');
      return;
    }
    const [width, height] = size.split('×').map(Number);
    const seed = seedText.trim() ? Number(seedText) : undefined;
    if (seed !== undefined && (!Number.isInteger(seed) || seed < 0)) {
      message.error('随机种子必须是非负整数');
      return;
    }
    setStarting(true);
    setError('');
    try {
      const response = await startLongVideo({
        keyframe_name: keyframe,
        prompts: prompts.map((prompt) => prompt.trim()),
        negative_prompt: negativePrompt,
        frames,
        fps: videoConfig.default_fps,
        width,
        height,
        steps,
        cfg,
        denoise,
        lora_strength: videoConfig.default_lora_strength,
        seed,
        use_lora: true,
      });
      saveJob(response.job_id);
      setStatus(null);
      await poll(response.job_id);
      message.success('长视频已开始，逐段生成并落盘');
    } catch (requestFailure) {
      setError(
        (requestFailure as { response?: { data?: { detail?: string } } })
          .response?.data?.detail || '长视频任务提交失败',
      );
    } finally {
      setStarting(false);
    }
  };

  const stop = async () => {
    if (!jobId) return;
    try {
      await stopLongVideo(jobId);
      message.success('已请求停止；已完成片段会保留');
      await poll(jobId);
    } catch (requestFailure) {
      setError(
        (requestFailure as { response?: { data?: { detail?: string } } })
          .response?.data?.detail || '停止失败',
      );
    }
  };

  const resume = async (segmentIndex?: number) => {
    if (!jobId) return;
    setResuming(segmentIndex || 0);
    setError('');
    try {
      await resumeLongVideo(jobId, segmentIndex);
      await poll(jobId);
      message.success(
        segmentIndex
          ? `已从第 ${segmentIndex} 段继续`
          : '已从未完成片段继续',
      );
    } catch (requestFailure) {
      setError(
        (requestFailure as { response?: { data?: { detail?: string } } })
          .response?.data?.detail || '恢复长视频失败',
      );
    } finally {
      setResuming(null);
    }
  };

  const effectiveStatus =
    status?.state.status === 'running' &&
    status.task?.status &&
    status.task.status !== 'running'
      ? status.task.status
      : status?.state.status || '';
  const running = effectiveStatus === 'running';
  const recoverable = ['error', 'stopped', 'interrupted'].includes(
    effectiveStatus,
  );
  const actualSegments = status?.state.segments || [];

  return (
    <section className="long-video-panel" aria-label="长视频分段">
      <header className="image-tool-header">
        <div>
          <h3>长视频分段接力</h3>
          <p>
            按段生成 Wan I2V，每段完成立即落盘；后续段以上一段尾帧为起点，失败只恢复未完成部分。
          </p>
        </div>
        <Tag color="blue">检查点可恢复</Tag>
      </header>

      <Alert
        type="info"
        showIcon
        message="长视频不会一次性占满全长帧数"
        description={`最多 ${videoConfig.long_video_max_segments} 段、${videoConfig.long_video_max_total_frames} 帧。任务持续占用 GPU/ComfyUI 租约，停止或失败时自动释放。`}
      />

      <Card title="分段脚本">
        <div className="long-video-keyframe-row">
          <Select
            value={keyframe || undefined}
            placeholder="选择起始关键帧"
            options={keyframes.map((item) => ({
              value: item.name,
              label: item.name,
            }))}
            onChange={setKeyframe}
            showSearch
            optionFilterProp="label"
          />
          <Upload
            accept="image/*"
            showUploadList={false}
            beforeUpload={(file) => {
              void uploadKeyframe(file as File);
              return Upload.LIST_IGNORE;
            }}
          >
            <Button icon={<UploadOutlined />}>上传关键帧</Button>
          </Upload>
        </div>
        <div className="long-video-segments">
          {prompts.map((prompt, index) => (
            <div key={index} className="long-video-segment-editor">
              <span>{index + 1}</span>
              <Input.TextArea
                rows={2}
                value={prompt}
                onChange={(event) => updatePrompt(index, event.target.value)}
                placeholder={`第 ${index + 1} 段动作描述`}
              />
              <Space size={2}>
                <Button
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={index === 0 || running}
                  onClick={() => movePrompt(index, -1)}
                />
                <Button
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={index === prompts.length - 1 || running}
                  onClick={() => movePrompt(index, 1)}
                />
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={running}
                  onClick={() => removePrompt(index)}
                />
              </Space>
            </div>
          ))}
        </div>
        <Button
          disabled={running || prompts.length >= videoConfig.long_video_max_segments}
          onClick={() => setPrompts((current) => [...current, ''])}
        >
          添加分段
        </Button>
        <label className="comic-field">
          <span>负面提示词</span>
          <Input.TextArea
            rows={2}
            value={negativePrompt}
            onChange={(event) => setNegativePrompt(event.target.value)}
          />
        </label>
        <div className="long-video-params">
          <label>
            <span>每段帧数</span>
            <Select
              value={frames}
              options={videoConfig.allowed_frames.map((value) => ({
                value,
                label: `${value} 帧`,
              }))}
              onChange={setFrames}
            />
          </label>
          <label>
            <span>分辨率</span>
            <Select
              value={size}
              options={videoConfig.allowed_sizes.map(([width, height]) => ({
                value: `${width}×${height}`,
                label: `${width}×${height}`,
              }))}
              onChange={(value) => setSize(value)}
            />
          </label>
          <label>
            <span>步数</span>
            <InputNumber min={videoConfig.steps_min} max={videoConfig.steps_max} value={steps} onChange={(value) => setSteps(Number(value || videoConfig.default_steps))} />
          </label>
          <label>
            <span>CFG</span>
            <InputNumber min={videoConfig.cfg_min} max={videoConfig.cfg_max} step={videoConfig.cfg_step} value={cfg} onChange={(value) => setCfg(Number(value || videoConfig.default_cfg))} />
          </label>
          <label>
            <span>降噪</span>
            <InputNumber min={videoConfig.denoise_min} max={videoConfig.denoise_max} step={videoConfig.denoise_step} value={denoise} onChange={(value) => setDenoise(Number(value ?? videoConfig.default_denoise))} />
          </label>
          <label>
            <span>基础 seed</span>
            <InputNumber value={seedText ? Number(seedText) : undefined} min={0} placeholder="随机" onChange={(value) => setSeedText(value == null ? '' : String(value))} />
          </label>
        </div>
        <div className="long-video-start-row">
          <Tag>
            总帧数 {frames * prompts.length} / {videoConfig.long_video_max_total_frames}
          </Tag>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={starting}
            disabled={running || frames * prompts.length > videoConfig.long_video_max_total_frames}
            onClick={() => void start()}
          >
            开始分段生成
          </Button>
        </div>
      </Card>

      {error ? <Alert type="error" showIcon message="长视频任务错误" description={error} /> : null}

      {status ? (
        <Card
          title="任务检查点"
          extra={
            <Space wrap>
              <Tag color={statusColor(effectiveStatus)}>
                {statusLabel(effectiveStatus)}
              </Tag>
              {running ? (
                <Button size="small" icon={<PauseCircleOutlined />} onClick={() => void stop()}>
                  停止
                </Button>
              ) : null}
              {recoverable ? (
                <Button size="small" icon={<ReloadOutlined />} loading={resuming === 0} onClick={() => void resume()}>
                  从未完成段恢复
                </Button>
              ) : null}
            </Space>
          }
        >
          <Progress
            percent={
              status.task?.total
                ? Math.round(((status.task.done || 0) / status.task.total) * 100)
                : 0
            }
            status={running ? 'active' : effectiveStatus === 'done' ? 'success' : 'normal'}
          />
          <div className="long-video-segment-status-list">
            {actualSegments.map((segment: LongVideoSegment) => (
              <div key={segment.index} className="long-video-segment-status">
                <strong>#{segment.index}</strong>
                <Tag color={statusColor(segment.status)}>{statusLabel(segment.status)}</Tag>
                <span title={segment.prompt}>{segment.prompt}</span>
                <small>{segment.video_name || `尝试 ${segment.attempts} 次`}</small>
                {recoverable && segment.index <= actualSegments.length ? (
                  <Button
                    size="small"
                    disabled={segment.index > 1 && actualSegments[segment.index - 2].status !== 'ready'}
                    loading={resuming === segment.index}
                    onClick={() => void resume(segment.index)}
                  >
                    从此段恢复
                  </Button>
                ) : null}
                {segment.error ? <em>{segment.error}</em> : null}
              </div>
            ))}
          </div>
          {status.task?.current ? (
            <p className="long-video-current">{status.task.current}</p>
          ) : null}
          {status.state.error ? (
            <Alert type="error" showIcon message={status.state.error} />
          ) : null}
        </Card>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="开始任务后显示每段检查点"
        />
      )}

      {status?.state.final_url ? (
        <Card title="长视频结果">
          <video
            className="storyboard-merged-video"
            controls
            src={status.state.final_url}
          />
          <a href={status.state.final_url} download={status.state.final_video_name}>
            <Button icon={<PlayCircleOutlined />}>下载合并成片</Button>
          </a>
        </Card>
      ) : null}
    </section>
  );
}
