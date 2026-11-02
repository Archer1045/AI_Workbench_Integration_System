import {
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  InboxOutlined,
  PlusOutlined,
  ScanOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  message,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  detectComicBubbles,
  getComicCapabilities,
  parseComicScript,
  renderComicText,
  type ComicBubble,
  type ComicCapabilities,
  type ComicDialogue,
  type ComicScriptResult,
  type ComicTextBox,
  type ComicTextRenderResult,
} from '../api';
import { getRuntimeConfig } from '../stores/runtimeConfig';

const { Dragger } = Upload;

interface EditableTextBox extends ComicTextBox {
  id: string;
}

interface CanvasSize {
  width: number;
  height: number;
}

async function requestError(error: unknown, fallback: string): Promise<string> {
  const response = (error as {
    response?: { data?: unknown; status?: number };
  }).response;
  let detail = response?.data;
  if (detail instanceof Blob) {
    try {
      detail = JSON.parse(await detail.text());
    } catch {
      detail = null;
    }
  }
  if (detail && typeof detail === 'object' && 'detail' in detail) {
    const value = (detail as { detail?: unknown }).detail;
    if (typeof value === 'string') return value;
  }
  if (typeof detail === 'string' && detail.trim()) return detail;
  return fallback;
}

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

export default function ComicTextPanel({ active }: { active: boolean }) {
  const limits = getRuntimeConfig().image_tools;
  const [file, setFile] = useState<File | null>(null);
  const [originalUrl, setOriginalUrl] = useState('');
  const [canvasSize, setCanvasSize] = useState<CanvasSize>({ width: 0, height: 0 });
  const [capabilities, setCapabilities] = useState<ComicCapabilities | null>(null);
  const [fontId, setFontId] = useState('');
  const [script, setScript] = useState('');
  const [bubbleBase, setBubbleBase] = useState('纯白干净的空白对话框');
  const [scriptResult, setScriptResult] = useState<ComicScriptResult | null>(null);
  const [parsing, setParsing] = useState(false);
  const [boxes, setBoxes] = useState<EditableTextBox[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [rendering, setRendering] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [result, setResult] = useState<ComicTextRenderResult | null>(null);
  const [resultUrl, setResultUrl] = useState('');
  const [error, setError] = useState('');
  const counter = useRef(0);

  const selectedBox = boxes.find((box) => box.id === selectedId) || null;

  useEffect(() => {
    getComicCapabilities()
      .then((value) => {
        setCapabilities(value);
        setFontId((current) => current || value.default_font);
      })
      .catch(() => {
        setCapabilities({ fonts: [], default_font: '', opencv: false, auto_bubble_requires: 'opencv-python' });
      });
  }, []);

  useEffect(() => {
    if (!file) {
      setOriginalUrl('');
      return;
    }
    const url = URL.createObjectURL(file);
    setOriginalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!result) {
      setResultUrl('');
      return;
    }
    const url = URL.createObjectURL(result.blob);
    setResultUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [result]);

  const loadFile = useCallback((nextFile: File) => {
    setFile(nextFile);
    setCanvasSize({ width: 0, height: 0 });
    setBoxes([]);
    setSelectedId('');
    setResult(null);
    setError('');
  }, []);

  useEffect(() => {
    if (!active) return;
    const onPaste = (event: ClipboardEvent) => {
      const pasted = Array.from(event.clipboardData?.files || []).find((item) =>
        item.type.startsWith('image/'),
      );
      if (!pasted) return;
      event.preventDefault();
      loadFile(pasted);
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [active, loadFile]);

  const parse = async () => {
    if (!script.trim()) {
      message.warning('请先输入带 [台词] 标记的剧本');
      return;
    }
    setParsing(true);
    try {
      const value = await parseComicScript({
        raw_prompt: script,
        base_bubble_description: bubbleBase,
      });
      setScriptResult(value);
      if (!value.dialogue_count) message.warning(value.warning);
    } catch (requestFailure) {
      message.error(await requestError(requestFailure, '解析剧本失败'));
    } finally {
      setParsing(false);
    }
  };

  const makeBox = (
    text: string,
    index: number,
    bubble?: ComicBubble,
  ): EditableTextBox => {
    counter.current += 1;
    if (bubble) {
      const margin = 10;
      return {
        id: `comic-box-${counter.current}`,
        text,
        x: bubble.x + margin,
        y: bubble.y + margin,
        max_width: Math.max(24, bubble.width - margin * 2),
        max_height: Math.max(24, bubble.height - margin * 2),
        font_size: 36,
        alignment: 'center',
        text_color: '#000000',
        outline_width: 0,
        outline_color: '#FFFFFF',
      };
    }
    const width = Math.max(80, Math.round(canvasSize.width * 0.4));
    const height = Math.max(50, Math.round(canvasSize.height * 0.16));
    return {
      id: `comic-box-${counter.current}`,
      text,
      x: clamp(Math.round(canvasSize.width * 0.06), 0, Math.max(0, canvasSize.width - 1)),
      y: clamp(
        Math.round(canvasSize.height * 0.08 + index * height * 1.15),
        0,
        Math.max(0, canvasSize.height - 1),
      ),
      max_width: Math.min(width, Math.max(1, canvasSize.width - Math.round(canvasSize.width * 0.06))),
      max_height: Math.min(height, Math.max(1, canvasSize.height - Math.round(canvasSize.height * 0.08))),
      font_size: 36,
      alignment: 'center',
      text_color: '#000000',
      outline_width: 0,
      outline_color: '#FFFFFF',
    };
  };

  const addDialogues = (bubbles: ComicBubble[] = []) => {
    if (!canvasSize.width || !canvasSize.height) {
      message.warning('请先载入漫画图');
      return;
    }
    const dialogues = scriptResult?.dialogues || [];
    if (!dialogues.length) {
      message.warning('没有可加入的台词，请先解析剧本');
      return;
    }
    const created = dialogues.map((dialogue, index) =>
      makeBox(dialogue.text, index, bubbles[index]),
    );
    setBoxes((current) => [...current, ...created]);
    setSelectedId(created[0]?.id || '');
    setResult(null);
    if (bubbles.length && dialogues.length > bubbles.length) {
      message.warning(`只有前 ${bubbles.length} 句台词匹配到了检测气泡`);
    }
  };

  const addEmptyBox = () => {
    if (!canvasSize.width || !canvasSize.height) return;
    const created = makeBox('新文字框', boxes.length);
    setBoxes((current) => [...current, created]);
    setSelectedId(created.id);
    setResult(null);
  };

  const updateBox = (patch: Partial<ComicTextBox>) => {
    if (!selectedBox) return;
    setBoxes((current) =>
      current.map((box) => (box.id === selectedBox.id ? { ...box, ...patch } : box)),
    );
    setResult(null);
  };

  const removeBox = (id: string) => {
    setBoxes((current) => current.filter((box) => box.id !== id));
    if (selectedId === id) setSelectedId('');
    setResult(null);
  };

  const placeAt = (event: React.MouseEvent<HTMLImageElement>) => {
    if (!selectedBox || !canvasSize.width || !canvasSize.height) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.round(((event.clientX - rect.left) / rect.width) * canvasSize.width);
    const y = Math.round(((event.clientY - rect.top) / rect.height) * canvasSize.height);
    const nextX = clamp(x, 0, canvasSize.width - 1);
    const nextY = clamp(y, 0, canvasSize.height - 1);
    updateBox({
      x: nextX,
      y: nextY,
      max_width: Math.max(1, Math.min(selectedBox.max_width, canvasSize.width - nextX)),
      max_height: Math.max(1, Math.min(selectedBox.max_height, canvasSize.height - nextY)),
    });
  };

  const render = async () => {
    if (!file || !fontId || !boxes.length) return;
    setRendering(true);
    setError('');
    try {
      const value = await renderComicText(
        file,
        boxes.map(({ id: _id, ...box }) => box),
        fontId,
      );
      setResult(value);
    } catch (requestFailure) {
      setError(
        await requestError(
          requestFailure,
          '文字渲染失败，请检查文字框位置、尺寸和字体。',
        ),
      );
    } finally {
      setRendering(false);
    }
  };

  const detect = async () => {
    if (!file) return;
    setDetecting(true);
    try {
      const detection = await detectComicBubbles(file);
      if (!detection.count) {
        message.warning('未检测到气泡，请调整阈值或使用手动坐标');
      } else {
        addDialogues(detection.bubbles);
      }
    } catch (requestFailure) {
      message.error(await requestError(requestFailure, '自动气泡检测失败'));
    } finally {
      setDetecting(false);
    }
  };

  const download = () => {
    if (!result) return;
    const anchor = document.createElement('a');
    anchor.href = resultUrl;
    anchor.download = `${(file?.name || 'comic').replace(/\.[^.]+$/, '')}_text.png`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    message.success('已下载 PNG；原图和图库均未被修改');
  };

  const dialogueRows = useMemo(
    () => scriptResult?.dialogues || [],
    [scriptResult],
  );

  return (
    <section className="comic-text-panel" aria-label="漫画文字">
      <header className="image-tool-header">
        <div>
          <Typography.Title level={3}>漫画文字</Typography.Title>
          <Typography.Paragraph>
            从剧本方括号中提取对白，使用受控字体精确排版。文字在服务端栅格化为 PNG，不依赖扩散模型绘制汉字。
          </Typography.Paragraph>
        </div>
        <Tag color="blue">精确文字渲染</Tag>
      </header>

      <Alert
        type="info"
        showIcon
        message="结果只进入预览，不会自动覆盖原图或写入图片库。"
        description={`支持 PNG/JPEG/WebP；最大 ${formatBytes(limits.comic_max_bytes)} / ${limits.comic_max_pixels.toLocaleString()} 像素，最多 ${limits.comic_max_boxes} 个文字框。`}
      />

      {capabilities && !capabilities.opencv ? (
        <Alert
          type="warning"
          showIcon
          message="自动气泡检测当前不可用"
          description={`可继续使用点击图片定位和手动坐标。若需要全自动检测，需另行确认安装 ${capabilities.auto_bubble_requires}。`}
        />
      ) : null}

      <Card className="image-tool-input-card">
        <Dragger
          accept="image/png,image/jpeg,image/webp"
          maxCount={1}
          multiple={false}
          showUploadList={false}
          disabled={rendering}
          beforeUpload={(candidate) => {
            loadFile(candidate as File);
            return Upload.LIST_IGNORE;
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">拖入漫画图、点击选择，或按 Ctrl+V 粘贴</p>
          <p className="ant-upload-hint">图片仅在本地后端处理，不调用外部 OCR 或生成服务</p>
        </Dragger>
      </Card>

      <div className="comic-script-grid">
        <label className="comic-field">
          <span>剧本 / 提示词（用 [文字] 标记台词）</span>
          <Input.TextArea
            rows={5}
            value={script}
            onChange={(event) => setScript(event.target.value)}
            placeholder="例：漫画分镜，空白气泡。[这是第一句。] [Second line.]"
          />
        </label>
        <label className="comic-field">
          <span>气泡基础描述</span>
          <Input
            value={bubbleBase}
            onChange={(event) => setBubbleBase(event.target.value)}
          />
          <Button loading={parsing} icon={<ThunderboltOutlined />} onClick={() => void parse()}>
            提取对白并清洗提示词
          </Button>
        </label>
      </div>

      {scriptResult ? (
        <Card size="small" title={`对白提取（${scriptResult.dialogue_count} 句）`}>
          <div className="comic-cleaned-prompt">
            <Typography.Text copyable={Boolean(scriptResult.cleaned_prompt)}>
              {scriptResult.cleaned_prompt || '没有清洗后的提示词'}
            </Typography.Text>
            <Button
              size="small"
              icon={<CopyOutlined />}
              disabled={!scriptResult.cleaned_prompt}
              onClick={() => {
                void navigator.clipboard.writeText(scriptResult.cleaned_prompt);
                message.success('已复制清洗后的提示词');
              }}
            >
              复制
            </Button>
          </div>
          {dialogueRows.length ? (
            <div className="comic-dialogue-list">
              {dialogueRows.map((dialogue) => (
                <Tag key={dialogue.index} color="geekblue">
                  {dialogue.index}. {dialogue.text} · {dialogue.bubble_size}
                </Tag>
              ))}
            </div>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={scriptResult.warning} />
          )}
          <Space wrap>
            <Button icon={<PlusOutlined />} onClick={() => addDialogues()}>
              全部加入画布
            </Button>
            <Tooltip
              title={
                capabilities?.opencv
                  ? '按白色气泡轮廓自动放置文字框'
                  : '需单独授权安装 opencv-python'
              }
            >
              <Button
                icon={<ScanOutlined />}
                loading={detecting}
                disabled={!capabilities?.opencv || !file || !dialogueRows.length}
                onClick={() => void detect()}
              >
                自动检测气泡
              </Button>
            </Tooltip>
          </Space>
        </Card>
      ) : null}

      {file ? (
        <Spin spinning={rendering} tip="正在用受控字体渲染文字">
          <div className="comic-workspace">
            <Card
              size="small"
              title="原图与文字框"
              extra={<Tag>{canvasSize.width ? `${canvasSize.width} × ${canvasSize.height}` : '读取尺寸'}</Tag>}
            >
              <div className="comic-canvas-wrap">
                <div className="comic-canvas-stage">
                  <img
                    src={originalUrl}
                    alt="漫画原图"
                    onClick={placeAt}
                    onLoad={(event) =>
                      setCanvasSize({
                        width: event.currentTarget.naturalWidth,
                        height: event.currentTarget.naturalHeight,
                      })
                    }
                  />
                  {canvasSize.width && canvasSize.height
                    ? boxes.map((box) => (
                        <button
                          type="button"
                          key={box.id}
                          className={`comic-box-overlay${box.id === selectedId ? ' is-selected' : ''}`}
                          style={{
                            left: `${(box.x / canvasSize.width) * 100}%`,
                            top: `${(box.y / canvasSize.height) * 100}%`,
                            width: `${(box.max_width / canvasSize.width) * 100}%`,
                            height: `${(box.max_height / canvasSize.height) * 100}%`,
                            color: box.text_color,
                          }}
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedId(box.id);
                          }}
                        >
                          {box.text}
                        </button>
                      ))
                    : null}
                </div>
              </div>
              <Typography.Paragraph type="secondary" className="comic-hint">
                选择文字框后，点击原图可设置左上角位置。文字会自动缩小以适配框宽和框高。
              </Typography.Paragraph>
            </Card>

            <Card
              size="small"
              title="文字框参数"
              extra={
                <Button size="small" icon={<PlusOutlined />} onClick={addEmptyBox}>
                  新增
                </Button>
              }
            >
              <label className="comic-field">
                <span>字体</span>
                <Select
                  value={fontId || undefined}
                  placeholder="未发现可用字体"
                  options={(capabilities?.fonts || []).map((font) => ({
                    value: font.id,
                    label: `${font.label} · ${font.source}`,
                  }))}
                  onChange={setFontId}
                  showSearch
                  optionFilterProp="label"
                />
              </label>
              {selectedBox ? (
                <>
                  <label className="comic-field">
                    <span>文字</span>
                    <Input.TextArea
                      rows={3}
                      value={selectedBox.text}
                      onChange={(event) => updateBox({ text: event.target.value })}
                    />
                  </label>
                  <div className="comic-number-grid">
                    {[
                      ['x', 'X', canvasSize.width - 1],
                      ['y', 'Y', canvasSize.height - 1],
                      ['max_width', '最大宽度', canvasSize.width - selectedBox.x],
                      ['max_height', '最大高度', canvasSize.height - selectedBox.y],
                      ['font_size', '字号', 500],
                      ['outline_width', '描边', 20],
                    ].map(([key, label, maximum]) => (
                      <label key={String(key)} className="comic-field">
                        <span>{String(label)}</span>
                        <InputNumber
                          min={key === 'font_size' ? 8 : 0}
                          max={Number(maximum)}
                          value={selectedBox[key as keyof ComicTextBox] as number}
                          onChange={(value) =>
                            updateBox({ [key]: Number(value || 0) })
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <label className="comic-field">
                    <span>对齐</span>
                    <Select
                      value={selectedBox.alignment}
                      options={[
                        { value: 'left', label: '左对齐' },
                        { value: 'center', label: '居中' },
                        { value: 'right', label: '右对齐' },
                      ]}
                      onChange={(value) =>
                        updateBox({ alignment: value as ComicTextBox['alignment'] })
                      }
                    />
                  </label>
                  <div className="comic-color-grid">
                    <label className="comic-field">
                      <span>文字颜色</span>
                      <Input
                        value={selectedBox.text_color}
                        onChange={(event) => updateBox({ text_color: event.target.value })}
                      />
                    </label>
                    <label className="comic-field">
                      <span>描边颜色</span>
                      <Input
                        value={selectedBox.outline_color}
                        onChange={(event) => updateBox({ outline_color: event.target.value })}
                      />
                    </label>
                  </div>
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => removeBox(selectedBox.id)}
                  >
                    删除此文字框
                  </Button>
                </>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={boxes.length ? '选择画布中的文字框' : '先加入对白或新增文字框'}
                />
              )}
              <Button
                type="primary"
                block
                loading={rendering}
                disabled={!fontId || !boxes.length}
                onClick={() => void render()}
              >
                渲染 {boxes.length} 个文字框
              </Button>
            </Card>
          </div>

          {error ? <Alert type="error" showIcon message="文字渲染失败" description={error} /> : null}

          {result ? (
            <Card
              title="渲染结果"
              extra={
                <Button type="primary" icon={<DownloadOutlined />} onClick={download}>
                  下载 PNG
                </Button>
              }
            >
              <div className="image-tool-preview-frame comic-result-frame">
                <img src={resultUrl} alt="漫画文字渲染结果" />
              </div>
              <Space wrap>
                <Tag color="green">{result.report.box_count} 个文字框</Tag>
                <Tag>{result.report.width} × {result.report.height}</Tag>
                <Tag>未写入图片库</Tag>
              </Space>
            </Card>
          ) : null}
        </Spin>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="载入漫画图后可预览文字框位置"
        />
      )}
    </section>
  );
}
