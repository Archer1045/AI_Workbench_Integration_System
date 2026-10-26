import {
  ClearOutlined,
  DownloadOutlined,
  InboxOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  message,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
} from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  deobfuscateImage,
  type ImageToolResult,
} from '../api';
import { getRuntimeConfig } from '../stores/runtimeConfig';

const { Dragger } = Upload;

interface FailureState {
  detail: string;
  canForce: boolean;
}

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

function resultFileName(input: string): string {
  const stem = input.replace(/\.[^.]+$/, '').trim() || 'image';
  return `${stem}_deobfuscated.png`;
}

async function readFailure(error: unknown): Promise<FailureState> {
  const response = (error as {
    response?: {
      status?: number;
      data?: unknown;
    };
  }).response;
  let detail = '图片处理失败，请稍后重试';
  let data = response?.data;
  if (data instanceof Blob) {
    try {
      data = JSON.parse(await data.text());
    } catch {
      data = null;
    }
  }
  if (data && typeof data === 'object' && 'detail' in data) {
    const value = (data as { detail?: unknown }).detail;
    if (typeof value === 'string') detail = value;
  } else if (typeof data === 'string' && data.trim()) {
    detail = data;
  }
  return {
    detail,
    canForce: response?.status === 422,
  };
}

export default function ImageDeobfuscationPanel({ active }: { active: boolean }) {
  const limits = getRuntimeConfig().image_tools;
  const [file, setFile] = useState<File | null>(null);
  const [originalUrl, setOriginalUrl] = useState('');
  const [result, setResult] = useState<ImageToolResult | null>(null);
  const [resultUrl, setResultUrl] = useState('');
  const [failure, setFailure] = useState<FailureState | null>(null);
  const [loading, setLoading] = useState(false);
  const [forceView, setForceView] = useState(false);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const requestSequence = useRef(0);

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

  const processFile = useCallback(
    async (nextFile: File, force: boolean) => {
      const requestId = ++requestSequence.current;
      setFile(nextFile);
      setResult(null);
      setFailure(null);
      setElapsedMs(null);
      setLoading(true);
      const startedAt = performance.now();
      try {
        const value = await deobfuscateImage(nextFile, { force });
        if (requestSequence.current !== requestId) return;
        setResult(value);
        setElapsedMs(performance.now() - startedAt);
      } catch (error) {
        if (requestSequence.current !== requestId) return;
        setFailure(await readFailure(error));
      } finally {
        if (requestSequence.current === requestId) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!active) return;
    const onPaste = (event: ClipboardEvent) => {
      const pasted = Array.from(event.clipboardData?.files || []).find((item) =>
        item.type.startsWith('image/'),
      );
      if (!pasted) return;
      event.preventDefault();
      void processFile(pasted, forceView);
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [active, forceView, processFile]);

  const clear = () => {
    requestSequence.current += 1;
    setLoading(false);
    setFile(null);
    setResult(null);
    setFailure(null);
    setElapsedMs(null);
  };

  const download = () => {
    if (!result || !file) return;
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = resultFileName(file.name);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.success('已下载 PNG；原图未被覆盖');
  };

  return (
    <section className="image-tool-panel" aria-label="图片解混淆">
      <header className="image-tool-header">
        <div>
          <Typography.Title level={3}>图片解混淆</Typography.Title>
          <Typography.Paragraph>
            本地还原小番茄 / Gilbert 曲线混淆图。算法只做可逆像素重排，不负责去马赛克或画质增强。
          </Typography.Paragraph>
        </div>
        <Tag icon={<SafetyCertificateOutlined />} color="green">
          仅本机处理
        </Tag>
      </header>

      <Alert
        type="info"
        showIcon
        message="图片只在工作台后端内存中处理，不会上传到外部服务，也不会自动写入图片库。"
        description={`支持 PNG、JPEG、WebP 等常见图片；最大 ${formatBytes(limits.max_bytes)} / ${limits.max_pixels.toLocaleString()} 像素。普通图片会被识别门槛拒绝。`}
      />

      <Card className="image-tool-input-card">
        <Dragger
          accept="image/*"
          maxCount={1}
          multiple={false}
          showUploadList={false}
          disabled={loading}
          beforeUpload={(candidate) => {
            void processFile(candidate as File, forceView);
            return Upload.LIST_IGNORE;
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">拖入图片、点击选择，或按 Ctrl+V 粘贴</p>
          <p className="ant-upload-hint">
            新图片会替换当前结果；不会覆盖原文件
          </p>
        </Dragger>
        <div className="image-tool-actions">
          <Checkbox
            checked={forceView}
            disabled={loading}
            onChange={(event) => setForceView(event.target.checked)}
          >
            强制查看未通过识别的结果
          </Checkbox>
          <Space wrap>
            <Button
              loading={loading}
              disabled={!file}
              onClick={() => {
                if (file) void processFile(file, forceView);
              }}
            >
              重新解混淆
            </Button>
            <Button icon={<ClearOutlined />} disabled={loading || !file} onClick={clear}>
              清空
            </Button>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              disabled={!result || loading}
              onClick={download}
            >
              下载 PNG
            </Button>
          </Space>
        </div>
      </Card>

      {failure && (
        <Alert
          type="warning"
          showIcon
          message="未能确认这是小番茄混淆图"
          description={
            <>
              <div>{failure.detail}</div>
              {failure.canForce && (
                <div className="image-tool-force-hint">
                  如果仍想检查像素重排结果，请勾选“强制查看未通过识别的结果”后重新解混淆。
                </div>
              )}
            </>
          }
        />
      )}

      {result && !result.report.accepted && (
        <Alert
          type="warning"
          showIcon
          message="当前为强制查看结果"
          description="粗糙度没有达到自动识别门槛，图片可能不是小番茄混淆图，或使用了尚未支持的版本。"
        />
      )}

      {(file || loading) && (
        <Spin spinning={loading} tip="正在本地生成 Gilbert 曲线并重排像素">
          <div className="image-tool-compare">
            <Card title="原图" className="image-tool-preview-card">
              {originalUrl ? (
                <div className="image-tool-preview-frame">
                  <img src={originalUrl} alt="待处理的原始图片" />
                </div>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="等待图片" />
              )}
              {file && (
                <Typography.Text type="secondary">
                  {file.name} · {formatBytes(file.size)}
                </Typography.Text>
              )}
            </Card>

            <Card title="解混淆结果" className="image-tool-preview-card">
              {resultUrl ? (
                <div className="image-tool-preview-frame">
                  <img src={resultUrl} alt="解混淆后的图片" />
                </div>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={loading ? '处理中' : '尚无结果'}
                />
              )}
              {result && (
                <Space size={[6, 6]} wrap>
                  <Tag color={result.report.accepted ? 'green' : 'orange'}>
                    {result.report.accepted ? '识别通过' : '强制查看'}
                  </Tag>
                  <Tag>{result.report.source_format || '未知格式'}</Tag>
                  <Tag>{result.report.mode}</Tag>
                  {elapsedMs !== null && <Tag>{Math.round(elapsedMs)} ms</Tag>}
                </Space>
              )}
            </Card>
          </div>
        </Spin>
      )}

      {result && (
        <Card title="处理报告">
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="尺寸">
              {result.report.width} × {result.report.height}
            </Descriptions.Item>
            <Descriptions.Item label="像素数">
              {result.report.pixel_count.toLocaleString()}
            </Descriptions.Item>
            <Descriptions.Item label="粗糙度（处理前）">
              {result.report.roughness_before.toFixed(3)}
            </Descriptions.Item>
            <Descriptions.Item label="粗糙度（处理后）">
              {result.report.roughness_after.toFixed(3)}
            </Descriptions.Item>
            <Descriptions.Item label="粗糙度比例">
              {(result.report.roughness_ratio * 100).toFixed(1)}%
            </Descriptions.Item>
            <Descriptions.Item label="算法">
              {result.report.algorithm}
            </Descriptions.Item>
            <Descriptions.Item label="输入 SHA-256" span={2}>
              <Typography.Text copyable className="image-tool-hash">
                {result.report.input_sha256}
              </Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="输出 SHA-256" span={2}>
              <Typography.Text copyable className="image-tool-hash">
                {result.report.output_sha256}
              </Typography.Text>
            </Descriptions.Item>
          </Descriptions>
          <Typography.Paragraph type="secondary" className="image-tool-report-note">
            粗糙度越低通常表示局部像素变化越平缓。识别通过仍不替代人工查看；下载动作不会改变原图或图片库。
          </Typography.Paragraph>
        </Card>
      )}
    </section>
  );
}
