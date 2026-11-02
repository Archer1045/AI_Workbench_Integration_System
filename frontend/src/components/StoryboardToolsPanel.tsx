import {
  DeleteOutlined,
  DownloadOutlined,
  InboxOutlined,
  MergeCellsOutlined,
  ScissorOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  InputNumber,
  message,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import {
  mergeVideoSegments,
  preflightVideoMerge,
  sliceStoryboard,
  type MergedVideoResult,
  type StoryboardSliceResult,
  type VideoMergeFileInfo,
  type VideoMergePreflight,
} from '../api';
import { getRuntimeConfig } from '../stores/runtimeConfig';

const { Dragger } = Upload;

function formatBytes(value: number): string {
  if (value >= 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

function formatDuration(value: number): string {
  const seconds = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds % 60).toFixed(2).padStart(5, '0')}`;
}

async function readError(error: unknown, fallback: string): Promise<string> {
  const response = (error as { response?: { data?: unknown } }).response;
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
  return fallback;
}

export default function StoryboardToolsPanel({ active }: { active: boolean }) {
  const imageLimits = getRuntimeConfig().image_tools;
  const [mode, setMode] = useState<'slice' | 'merge'>('slice');
  const [sliceFile, setSliceFile] = useState<File | null>(null);
  const [sliceUrl, setSliceUrl] = useState('');
  const [sliceDimensions, setSliceDimensions] = useState('');
  const [grid, setGrid] = useState<4 | 6 | 9>(4);
  const [cropMargin, setCropMargin] = useState(0);
  const [slicing, setSlicing] = useState(false);
  const [sliceResult, setSliceResult] = useState<StoryboardSliceResult | null>(null);
  const [sliceError, setSliceError] = useState('');

  const [videoFiles, setVideoFiles] = useState<File[]>([]);
  const [preflight, setPreflight] = useState<VideoMergePreflight | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [mergeLoading, setMergeLoading] = useState(false);
  const [mergeError, setMergeError] = useState('');
  const [mergeResult, setMergeResult] = useState<MergedVideoResult | null>(null);

  useEffect(() => {
    if (!sliceFile) {
      setSliceUrl('');
      return;
    }
    const url = URL.createObjectURL(sliceFile);
    setSliceUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [sliceFile]);

  const resetMerge = () => {
    setPreflight(null);
    setMergeResult(null);
    setMergeError('');
  };

  const addVideo = (file: File) => {
    if (videoFiles.length >= 10) {
      message.warning('一次最多合并 10 个片段');
      return;
    }
    setVideoFiles((current) => [...current, file]);
    resetMerge();
  };

  const handleSlice = async () => {
    if (!sliceFile) return;
    setSlicing(true);
    setSliceError('');
    try {
      setSliceResult(await sliceStoryboard(sliceFile, grid, cropMargin));
    } catch (error) {
      setSliceResult(null);
      setSliceError(await readError(error, '分镜切片失败'));
    } finally {
      setSlicing(false);
    }
  };

  const downloadSlices = () => {
    if (!sliceResult) return;
    const url = URL.createObjectURL(sliceResult.blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${(sliceFile?.name || 'storyboard').replace(/\.[^.]+$/, '')}_${grid}cells.zip`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const handlePreflight = async () => {
    if (videoFiles.length < 2) {
      message.warning('至少选择两个视频片段');
      return;
    }
    setPreflightLoading(true);
    setMergeError('');
    setMergeResult(null);
    try {
      setPreflight(await preflightVideoMerge(videoFiles));
    } catch (error) {
      setPreflight(null);
      setMergeError(await readError(error, '视频预检失败'));
    } finally {
      setPreflightLoading(false);
    }
  };

  const handleMerge = async () => {
    if (!preflight?.compatible) return;
    setMergeLoading(true);
    setMergeError('');
    try {
      setMergeResult(await mergeVideoSegments(videoFiles));
    } catch (error) {
      setMergeError(await readError(error, '视频合并失败'));
    } finally {
      setMergeLoading(false);
    }
  };

  const fileColumns: ColumnsType<VideoMergeFileInfo> = [
    {
      title: '顺序',
      key: 'order',
      width: 70,
      render: (_, __, index) => index + 1,
    },
    { title: '片段', dataIndex: 'name', ellipsis: true },
    {
      title: '时长',
      dataIndex: 'duration',
      width: 100,
      render: (value: number) => formatDuration(value),
    },
    {
      title: '视频',
      key: 'video',
      width: 190,
      render: (_, item) =>
        `${item.video.codec} · ${item.video.width}×${item.video.height} · ${item.video.fps.toFixed(2)} fps`,
    },
    {
      title: '音频',
      key: 'audio',
      width: 170,
      render: (_, item) =>
        item.audio
          ? `${item.audio.codec} · ${item.audio.sample_rate} Hz · ${item.audio.layout}`
          : '无音轨',
    },
    {
      title: '大小',
      dataIndex: 'bytes',
      width: 100,
      render: (value: number) => formatBytes(value),
    },
  ];

  const gridPreviewCells = Array.from(
    { length: grid },
    (_, index) => index,
  );
  const previewColumns = grid === 4 ? 2 : 3;

  return (
    <section className="storyboard-tools" aria-label="分镜与视频合并">
      <header className="image-tool-header">
        <div>
          <Typography.Title level={3}>分镜与视频合并</Typography.Title>
          <Typography.Paragraph>
            将四宫格、六宫格或九宫格分镜切成独立 PNG，并在合并前核对分辨率、帧率和音轨。
          </Typography.Paragraph>
        </div>
        <Tag color="purple">本地 CPU 工具</Tag>
      </header>

      <Segmented
        className="storyboard-mode"
        value={mode}
        options={[
          { value: 'slice', label: '分镜切片' },
          { value: 'merge', label: '视频合并' },
        ]}
        onChange={(value) => setMode(value as 'slice' | 'merge')}
      />

      {mode === 'slice' ? (
        <>
          <Card>
            <Dragger
              accept="image/png,image/jpeg,image/webp"
              maxCount={1}
              showUploadList={false}
              disabled={slicing}
              beforeUpload={(file) => {
                setSliceFile(file as File);
                setSliceResult(null);
                setSliceError('');
                setSliceDimensions('');
                return Upload.LIST_IGNORE;
              }}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">拖入或选择分镜整图</p>
              <p className="ant-upload-hint">
                PNG/JPEG/WebP，最大 {formatBytes(imageLimits.storyboard_max_bytes)}；
                输出 ZIP 内含每个单元 PNG 和 manifest.json
              </p>
            </Dragger>
            <div className="storyboard-controls">
              <label>
                <span>网格</span>
                <Select
                  value={grid}
                  options={[
                    { value: 4, label: '四宫格 2×2' },
                    { value: 6, label: '六宫格 2×3' },
                    { value: 9, label: '九宫格 3×3' },
                  ]}
                  onChange={(value) => {
                    setGrid(value as 4 | 6 | 9);
                    setSliceResult(null);
                  }}
                />
              </label>
              <label>
                <span>每格裁剪边距</span>
                <InputNumber
                  min={0}
                  max={imageLimits.storyboard_crop_margin_max}
                  value={cropMargin}
                  onChange={(value) => {
                    setCropMargin(Number(value || 0));
                    setSliceResult(null);
                  }}
                  suffix="px"
                />
              </label>
              <Button
                type="primary"
                icon={<ScissorOutlined />}
                loading={slicing}
                disabled={!sliceFile}
                onClick={() => void handleSlice()}
              >
                生成 {grid} 个分镜 PNG
              </Button>
            </div>
          </Card>

          {sliceFile ? (
            <div className="storyboard-slice-grid">
              <Card
                title="切片位置预览"
                extra={<Tag>{sliceDimensions || '读取尺寸'}</Tag>}
              >
                <Spin spinning={slicing}>
                  <div className="storyboard-source-stage">
                    <img
                      src={sliceUrl}
                      alt="待切分镜图"
                      onLoad={(event) =>
                        setSliceDimensions(
                          `${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`,
                        )
                      }
                    />
                    <div
                      className="storyboard-grid-overlay"
                      style={{
                        gridTemplateColumns: `repeat(${previewColumns}, minmax(0, 1fr))`,
                      }}
                    >
                      {gridPreviewCells.map((index) => (
                        <span key={index}>{index + 1}</span>
                      ))}
                    </div>
                  </div>
                </Spin>
              </Card>
              <Card title="切片报告">
                {sliceResult ? (
                  <>
                    <Descriptions column={2} size="small" bordered>
                      <Descriptions.Item label="源尺寸">
                        {sliceResult.report.source_width} × {sliceResult.report.source_height}
                      </Descriptions.Item>
                      <Descriptions.Item label="网格">
                        {sliceResult.report.rows} × {sliceResult.report.columns}
                      </Descriptions.Item>
                      <Descriptions.Item label="单元数">
                        {sliceResult.report.cell_count}
                      </Descriptions.Item>
                      <Descriptions.Item label="裁剪">
                        {sliceResult.report.crop_margin} px
                      </Descriptions.Item>
                      <Descriptions.Item label="源文件" span={2}>
                        {sliceResult.report.source_name}
                      </Descriptions.Item>
                    </Descriptions>
                    <Space wrap>
                      <Button
                        type="primary"
                        icon={<DownloadOutlined />}
                        onClick={downloadSlices}
                      >
                        下载 ZIP + 元数据
                      </Button>
                      <Tag color="green">未写入图片库</Tag>
                    </Space>
                  </>
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={slicing ? '正在切片' : '切片后显示单元尺寸和顺序'}
                  />
                )}
              </Card>
            </div>
          ) : null}
          {sliceError ? (
            <Alert type="error" showIcon message="分镜切片失败" description={sliceError} />
          ) : null}
        </>
      ) : (
        <>
          <Card title="选择视频片段">
            <Upload
              accept=".mp4,.mov,.mkv,.webm,video/*"
              multiple
              showUploadList={false}
              beforeUpload={(file) => {
                addVideo(file as File);
                return Upload.LIST_IGNORE;
              }}
            >
              <Button icon={<UploadOutlined />}>添加片段</Button>
            </Upload>
            {videoFiles.length ? (
              <div className="storyboard-video-file-list">
                {videoFiles.map((file, index) => (
                  <div key={`${file.name}:${file.lastModified}:${index}`}>
                    <span>{index + 1}</span>
                    <strong title={file.name}>{file.name}</strong>
                    <small>{formatBytes(file.size)}</small>
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => {
                        setVideoFiles((current) =>
                          current.filter((_, itemIndex) => itemIndex !== index),
                        );
                        resetMerge();
                      }}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="至少添加两个片段" />
            )}
            <Space wrap>
              <Button
                loading={preflightLoading}
                disabled={videoFiles.length < 2}
                onClick={() => void handlePreflight()}
              >
                合并前预检
              </Button>
              <Button
                type="primary"
                icon={<MergeCellsOutlined />}
                loading={mergeLoading}
                disabled={!preflight?.compatible}
                onClick={() => void handleMerge()}
              >
                无损合并
              </Button>
              <Tag>不兼容时不会写出成片</Tag>
            </Space>
          </Card>

          {mergeError ? (
            <Alert type="error" showIcon message="视频合并失败" description={mergeError} />
          ) : null}
          {preflight ? (
            <Card title="预检结果">
              <Alert
                type={preflight.compatible ? 'success' : 'error'}
                showIcon
                message={
                  preflight.compatible
                    ? `兼容，可无损合并为 ${preflight.output_format.toUpperCase()}`
                    : '片段不兼容，已阻止合并'
                }
                description={
                  preflight.issues.length
                    ? preflight.issues.join('；')
                    : `总时长 ${formatDuration(preflight.total_duration)}`
                }
              />
              <Table
                rowKey={(record) => `${record.name}:${record.bytes}`}
                columns={fileColumns}
                dataSource={preflight.files}
                pagination={false}
                size="small"
                scroll={{ x: 850 }}
              />
            </Card>
          ) : null}
          {mergeResult ? (
            <Card
              title="合并结果"
              extra={<Tag color="green">{mergeResult.format.toUpperCase()}</Tag>}
            >
              <video
                className="storyboard-merged-video"
                controls
                src={mergeResult.url}
              />
              <Space wrap>
                <a href={mergeResult.url} download={mergeResult.filename}>
                  <Button icon={<DownloadOutlined />}>下载合并视频</Button>
                </a>
                <Tag>{formatDuration(mergeResult.total_duration)}</Tag>
                <Tag>{formatBytes(mergeResult.bytes)}</Tag>
                <Tag>仅本次显式合并生成</Tag>
              </Space>
            </Card>
          ) : null}
        </>
      )}
    </section>
  );
}
