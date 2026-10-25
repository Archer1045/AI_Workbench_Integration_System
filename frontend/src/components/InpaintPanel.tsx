import {
  ClearOutlined,
  PictureOutlined,
  StopOutlined,
  UndoOutlined,
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
  Segmented,
  Select,
  Slider,
  Space,
  Tag,
  Tooltip,
} from 'antd';
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import {
  api,
  type DrawImageRecord,
  type InpaintJob,
  type InpaintResult,
  type InpaintSource,
  type LoraItem,
  type ModelItem,
  type PromptDocumentV1,
} from '../api';
import { getRuntimeConfig } from '../stores/runtimeConfig';
import ImageLibraryDrawer from './ImageLibraryDrawer';

interface SourceState {
  sourceId?: string;
  recordId?: number;
  imageUrl: string;
  width: number;
  height: number;
  label: string;
}

export interface InpaintInitialSource {
  recordId?: number;
  imageUrl: string;
  width: number;
  height: number;
  label: string;
  prompt?: string;
  negativePrompt?: string;
  promptDocument?: PromptDocumentV1 | null;
}

type BrushMode = 'paint' | 'erase';

function errorText(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message?: unknown }).message || fallback);
  }
  return fallback;
}

function workingSize(value: number | null | undefined): number {
  const raw = Number(value || 0);
  return Math.max(64, Math.floor(raw / 8) * 8);
}

export default function InpaintPanel({
  initialSource,
}: {
  initialSource?: InpaintInitialSource;
} = {}) {
  const drawConfig = getRuntimeConfig().draw;
  const [models, setModels] = useState<ModelItem[]>([]);
  const [loras, setLoras] = useState<LoraItem[]>([]);
  const [model, setModel] = useState(drawConfig.default_model);
  const [selectedLoras, setSelectedLoras] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState(drawConfig.default_negative_prompt);
  const [maskedPrompt, setMaskedPrompt] = useState('');
  const [promptDocument, setPromptDocument] = useState<PromptDocumentV1 | null>(null);
  const [denoise, setDenoise] = useState(0.75);
  const [count, setCount] = useState(2);
  const [steps, setSteps] = useState(drawConfig.default_steps);
  const [cfg, setCfg] = useState(drawConfig.default_cfg);
  const [seed, setSeed] = useState<number | null>(null);
  const [grow, setGrow] = useState(12);
  const [feather, setFeather] = useState(8);
  const [brushSize, setBrushSize] = useState(28);
  const [brushMode, setBrushMode] = useState<BrushMode>('paint');
  const [hasMask, setHasMask] = useState(false);
  const [source, setSource] = useState<SourceState | null>(null);
  const [sourceImage, setSourceImage] = useState<HTMLImageElement | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState<InpaintJob | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const displayCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const maskCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const historyRef = useRef<ImageData[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    api
      .get<{ models: ModelItem[] }>('/models')
      .then((response) => setModels(response.data.models || []))
      .catch(() => setModels([]));
    api
      .get<{ loras: LoraItem[] }>('/loras')
      .then((response) =>
        setLoras(
          (response.data.loras || []).filter(
            (item) => item.compatible !== false && item.purpose !== 'video',
          ),
        ),
      )
      .catch(() => setLoras([]));
  }, []);

  const redraw = () => {
    const display = displayCanvasRef.current;
    const mask = maskCanvasRef.current;
    if (!display || !mask || !source || !sourceImage) return;
    const context = display.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, source.width, source.height);
    context.drawImage(
      sourceImage,
      0,
      0,
      source.width,
      source.height,
      0,
      0,
      source.width,
      source.height,
    );
    const tint = document.createElement('canvas');
    tint.width = source.width;
    tint.height = source.height;
    const tintContext = tint.getContext('2d');
    if (!tintContext) return;
    tintContext.drawImage(mask, 0, 0);
    tintContext.globalCompositeOperation = 'source-in';
    tintContext.fillStyle = 'rgba(239, 68, 68, 0.55)';
    tintContext.fillRect(0, 0, source.width, source.height);
    context.drawImage(tint, 0, 0);
  };

  useEffect(() => {
    const display = displayCanvasRef.current;
    if (!display || !source || !sourceImage) return;
    display.width = source.width;
    display.height = source.height;
    let mask = maskCanvasRef.current;
    if (!mask) {
      mask = document.createElement('canvas');
      maskCanvasRef.current = mask;
    }
    mask.width = source.width;
    mask.height = source.height;
    const maskContext = mask.getContext('2d');
    maskContext?.clearRect(0, 0, source.width, source.height);
    historyRef.current = [];
    setHasMask(false);
    redraw();
  }, [source, sourceImage]);

  useEffect(() => {
    if (!jobId) return;
    let timer: number | undefined;
    let disposed = false;
    const poll = async () => {
      try {
        const response = await api.get<InpaintJob>(`/draw/inpaint/jobs/${jobId}`);
        if (disposed) return;
        setJob(response.data);
        if (response.data.status === 'queued' || response.data.status === 'running') {
          timer = window.setTimeout(poll, 1000);
        } else if (response.data.status === 'succeeded') {
          message.success(`局部重绘完成，已生成 ${response.data.results.length} 个候选`);
        } else if (response.data.status === 'failed') {
          message.error(response.data.error?.message || '局部重绘失败');
        }
      } catch (error) {
        if (!disposed) timer = window.setTimeout(poll, 2000);
      }
    };
    void poll();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId]);

  const loadSource = (
    imageUrl: string,
    width: number,
    height: number,
    options: { sourceId?: string; recordId?: number; label: string },
  ) => {
    setSourceLoading(true);
    const image = new window.Image();
    image.onload = () => {
      setSource({
        sourceId: options.sourceId,
        recordId: options.recordId,
        imageUrl,
        width,
        height,
        label: options.label,
      });
      setSourceImage(image);
      setJob(null);
      setJobId('');
      setSourceLoading(false);
    };
    image.onerror = () => {
      setSourceLoading(false);
      message.error('底图加载失败');
    };
    image.src = imageUrl;
  };

  useEffect(() => {
    if (!initialSource) return;
    setPrompt(initialSource.prompt || '');
    if (initialSource.negativePrompt != null) {
      setNegativePrompt(initialSource.negativePrompt);
    }
    setPromptDocument(initialSource.promptDocument || null);
    loadSource(
      initialSource.imageUrl,
      workingSize(initialSource.width),
      workingSize(initialSource.height),
      { recordId: initialSource.recordId, label: initialSource.label },
    );
  }, [initialSource]);

  const handleUpload = async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    setSourceLoading(true);
    try {
      const { data } = await api.post<InpaintSource>('/draw/inpaint/sources', form);
      loadSource(data.preview_url, data.working_width, data.working_height, {
        sourceId: data.source_id,
        label: file.name || '上传底图',
      });
    } catch (error) {
      setSourceLoading(false);
      message.error(errorText(error, '底图上传失败'));
    }
  };

  const handleLibrarySelect = (record: DrawImageRecord) => {
    if (!record.image_url || !record.width || !record.height) {
      message.error('该图片记录没有可用文件');
      return;
    }
    loadSource(
      record.image_url,
      workingSize(record.width),
      workingSize(record.height),
      { recordId: record.id, label: `图片库 #${record.id}` },
    );
    setLibraryOpen(false);
  };

  const pointFromEvent = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const canvas = displayCanvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * canvas.width,
      y: ((event.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  const drawStroke = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const mask = maskCanvasRef.current;
    const context = mask?.getContext('2d');
    if (!context) return;
    context.globalCompositeOperation = brushMode === 'erase' ? 'destination-out' : 'source-over';
    context.strokeStyle = '#ffffff';
    context.lineWidth = brushSize;
    context.lineCap = 'round';
    context.lineJoin = 'round';
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.stroke();
    redraw();
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!source) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drawingRef.current = true;
    const point = pointFromEvent(event);
    lastPointRef.current = point;
    drawStroke(point, point);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current || !lastPointRef.current) return;
    const point = pointFromEvent(event);
    drawStroke(lastPointRef.current, point);
    lastPointRef.current = point;
  };

  const handlePointerUp = () => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    lastPointRef.current = null;
    const mask = maskCanvasRef.current;
    const context = mask?.getContext('2d');
    if (!mask || !context) return;
    const imageData = context.getImageData(0, 0, mask.width, mask.height);
    historyRef.current.push(imageData);
    if (historyRef.current.length > 20) historyRef.current.shift();
    const nonEmpty = imageData.data.some(
      (value, index) => index % 4 === 3 && value > 0,
    );
    setHasMask(nonEmpty);
    redraw();
  };

  const handleUndo = () => {
    const mask = maskCanvasRef.current;
    const context = mask?.getContext('2d');
    if (!mask || !context) return;
    historyRef.current.pop();
    context.clearRect(0, 0, mask.width, mask.height);
    const previous = historyRef.current[historyRef.current.length - 1];
    if (previous) context.putImageData(previous, 0, 0);
    setHasMask(Boolean(previous));
    redraw();
  };

  const handleClear = () => {
    const mask = maskCanvasRef.current;
    const context = mask?.getContext('2d');
    if (!mask || !context) return;
    context.clearRect(0, 0, mask.width, mask.height);
    historyRef.current = [];
    setHasMask(false);
    redraw();
  };

  const exportMask = (): string => {
    const mask = maskCanvasRef.current;
    if (!mask || !source) return '';
    const output = document.createElement('canvas');
    output.width = source.width;
    output.height = source.height;
    const context = output.getContext('2d');
    if (!context) return '';
    context.fillStyle = '#000000';
    context.fillRect(0, 0, source.width, source.height);
    context.drawImage(mask, 0, 0);
    return output.toDataURL('image/png');
  };

  const submit = async () => {
    if (!source) {
      message.warning('请先选择或上传底图');
      return;
    }
    if (!prompt.trim() && !promptDocument) {
      message.warning('请输入整图提示词');
      return;
    }
    if (!hasMask) {
      message.warning('请先在画布上画出 mask');
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        ...(source.sourceId
          ? { source_id: source.sourceId }
          : { source_record_id: source.recordId }),
        mask_base64: exportMask(),
        prompt: prompt.trim(),
        ...(promptDocument ? { prompt_document: promptDocument } : {}),
        negative_prompt: negativePrompt,
        masked_prompt: maskedPrompt.trim(),
        denoise,
        count,
        seed,
        model,
        loras: selectedLoras,
        steps,
        cfg,
        grow,
        feather,
      };
      const { data } = await api.post<{ job_id: string }>('/draw/inpaint/jobs', payload);
      setJobId(data.job_id);
      setJob({
        job_id: data.job_id,
        status: 'queued',
        progress: { completed: 0, total: count },
        results: [],
      });
    } catch (error) {
      message.error(errorText(error, '提交局部重绘失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (!jobId) return;
    try {
      const { data } = await api.post<InpaintJob>(`/draw/inpaint/jobs/${jobId}/cancel`);
      setJob(data);
    } catch (error) {
      message.error(errorText(error, '取消失败'));
    }
  };

  const continueEditing = (result: InpaintResult) => {
    loadSource(
      result.image_url,
      workingSize(result.width),
      workingSize(result.height),
      { recordId: result.record_id, label: `结果 #${result.record_id}` },
    );
  };

  const jobRunning = job?.status === 'queued' || job?.status === 'running';
  const progressPercent = job?.progress.total
    ? Math.round((job.progress.completed / job.progress.total) * 100)
    : 0;

  return (
    <div className="inpaint-panel">
      <div className="inpaint-header">
        <div>
          <h2>局部重绘</h2>
          <p>选择底图，在画布上涂抹要重绘的区域，再生成 1–4 个候选。mask 外会保留原像素。</p>
        </div>
        <Space wrap>
          <Button loading={sourceLoading} icon={<UploadOutlined />} onClick={() => fileInputRef.current?.click()}>
            上传底图
          </Button>
          <Button icon={<PictureOutlined />} onClick={() => setLibraryOpen(true)}>
            从图片库选择
          </Button>
        </Space>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleUpload(file);
          event.target.value = '';
        }}
      />

      <div className="inpaint-grid">
        <Card size="small" title="底图与参数" className="inpaint-card">
          {source ? (
            <div className="inpaint-source-summary">
              <img src={source.imageUrl} alt="" />
              <div>
                <strong>{source.label}</strong>
                <span>{source.width} × {source.height}</span>
              </div>
            </div>
          ) : (
            <Alert
              type="info"
              showIcon
              message="先选择底图"
              description="可以上传本地图片，或从图片库选择已有记录。"
            />
          )}
          <label className="inpaint-field">
            <span>
              整图提示词
              {promptDocument ? <Tag color="blue">已带入当前组结构化提示词</Tag> : null}
            </span>
            <Input.TextArea
              rows={3}
              value={prompt}
              onChange={(event) => {
                setPrompt(event.target.value);
                setPromptDocument(null);
              }}
              placeholder="描述底图/当前组的整体内容"
            />
          </label>
          <label className="inpaint-field">
            <span>局部提示词</span>
            <Input.TextArea
              rows={2}
              value={maskedPrompt}
              onChange={(event) => setMaskedPrompt(event.target.value)}
              placeholder="留空则使用整图提示词"
            />
          </label>
          <label className="inpaint-field">
            <span>负面提示词</span>
            <Input.TextArea
              rows={2}
              value={negativePrompt}
              onChange={(event) => {
                setNegativePrompt(event.target.value);
                setPromptDocument(null);
              }}
            />
          </label>
          <div className="inpaint-field">
            <span>重绘强度</span>
            <Segmented
              value={denoise}
              options={[
                { label: '修细节 0.45', value: 0.45 },
                { label: '换内容 0.75', value: 0.75 },
                { label: '大改 0.90', value: 0.9 },
              ]}
              onChange={(value) => setDenoise(Number(value))}
            />
            <InputNumber
              min={0.2}
              max={1}
              step={0.05}
              value={denoise}
              onChange={(value) => setDenoise(Number(value ?? 0.75))}
            />
          </div>
          <div className="inpaint-field-row">
            <label className="inpaint-field">
              <span>候选数</span>
              <InputNumber min={1} max={4} value={count} onChange={(value) => setCount(Number(value ?? 2))} />
            </label>
            <label className="inpaint-field">
              <span>步数</span>
              <InputNumber min={1} max={60} value={steps} onChange={(value) => setSteps(Number(value ?? 18))} />
            </label>
            <label className="inpaint-field">
              <span>CFG</span>
              <InputNumber min={0} max={30} step={0.1} value={cfg} onChange={(value) => setCfg(Number(value ?? 1))} />
            </label>
            <label className="inpaint-field">
              <span>Seed</span>
              <InputNumber
                min={0}
                max={9007199254740991}
                value={seed}
                placeholder="随机"
                onChange={(value) => setSeed(value == null ? null : Number(value))}
              />
            </label>
          </div>
          <div className="inpaint-field-row">
            <label className="inpaint-field">
              <span>Grow</span>
              <InputNumber min={0} max={64} value={grow} onChange={(value) => setGrow(Number(value ?? 12))} />
            </label>
            <label className="inpaint-field">
              <span>Feather</span>
              <InputNumber min={0} max={64} value={feather} onChange={(value) => setFeather(Number(value ?? 8))} />
            </label>
          </div>
          <label className="inpaint-field">
            <span>底模</span>
            <Select
              value={model}
              options={models.map((item) => ({ label: item.name, value: item.name }))}
              onChange={setModel}
              showSearch
            />
          </label>
          <label className="inpaint-field">
            <span>LoRA</span>
            <Select
              mode="multiple"
              value={selectedLoras}
              options={loras.map((item) => ({ label: item.name, value: item.name }))}
              onChange={setSelectedLoras}
              placeholder="可选择多个"
              optionFilterProp="label"
            />
          </label>
          <Button
            type="primary"
            block
            loading={submitting}
            disabled={!source || !hasMask || (!prompt.trim() && !promptDocument) || jobRunning}
            onClick={() => void submit()}
          >
            {jobRunning ? '正在生成…' : `生成 ${count} 个候选`}
          </Button>
          {jobRunning ? (
            <Button block danger icon={<StopOutlined />} onClick={() => void cancel()}>
              取消任务
            </Button>
          ) : null}
        </Card>

        <Card size="small" title="Mask 画布" className="inpaint-card inpaint-canvas-card">
          {source ? (
            <>
              <div className="inpaint-canvas-wrap">
                <canvas
                  ref={displayCanvasRef}
                  className="inpaint-canvas"
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  onPointerCancel={handlePointerUp}
                />
              </div>
              <div className="inpaint-toolbar">
                <Segmented
                  value={brushMode}
                  options={[
                    { label: '画笔', value: 'paint' },
                    { label: '橡皮', value: 'erase' },
                  ]}
                  onChange={(value) => setBrushMode(value as BrushMode)}
                />
                <span>笔刷</span>
                <Slider min={4} max={96} value={brushSize} onChange={setBrushSize} style={{ minWidth: 120 }} />
                <Tooltip title="撤销上一笔">
                  <Button icon={<UndoOutlined />} onClick={handleUndo} disabled={!hasMask} />
                </Tooltip>
                <Tooltip title="清空 mask">
                  <Button icon={<ClearOutlined />} onClick={handleClear} disabled={!hasMask} />
                </Tooltip>
                <Tag color={hasMask ? 'green' : 'default'}>{hasMask ? '已画 mask' : '未画 mask'}</Tag>
              </div>
              <p className="inpaint-hint">画布显示为半透明红色；导出时白色=重绘，黑色=保留。</p>
            </>
          ) : (
            <Empty description="选择底图后在这里涂抹 mask" />
          )}
        </Card>

        <Card size="small" title="候选结果" className="inpaint-card">
          {job ? (
            <>
              <div className="inpaint-job-line">
                <Tag color={job.status === 'succeeded' ? 'green' : job.status === 'failed' ? 'red' : 'processing'}>
                  {job.status}
                </Tag>
                <span>{job.progress.completed}/{job.progress.total}</span>
                {jobRunning ? (
                  <Progress percent={progressPercent} size="small" status="active" />
                ) : null}
              </div>
              {job.error ? <Alert type="error" showIcon message={job.error.message} /> : null}
              <div className="inpaint-results">
                {job.results.map((result) => (
                  <div className="inpaint-result" key={result.record_id}>
                    <img src={result.image_url} alt={`候选 ${result.record_id}`} />
                    <div className="inpaint-result-meta">
                      <span>#{result.record_id}</span>
                      <span>seed {result.seed}</span>
                      <span>denoise {result.denoise}</span>
                    </div>
                    <Space size={4} wrap>
                      <Button size="small" onClick={() => window.open(result.image_url, '_blank')}>
                        查看
                      </Button>
                      <Button size="small" onClick={() => continueEditing(result)}>
                        继续编辑
                      </Button>
                    </Space>
                    <small>已自动保存到图片库</small>
                  </div>
                ))}
              </div>
              {!jobRunning && job.results.length === 0 && job.status !== 'failed' ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无候选" />
              ) : null}
            </>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="提交后会在这里显示候选" />
          )}
        </Card>
      </div>

      <ImageLibraryDrawer
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        onSelect={handleLibrarySelect}
      />
    </div>
  );
}
