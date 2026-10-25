// 数据看板：记录列表 + 提示词统计（表格 + 柱形图）
import { Column, Line } from '@ant-design/charts';
import { ReloadOutlined } from '@ant-design/icons';
import { Button, DatePicker, InputNumber, message, Popover, Segmented, Select, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';
import { api, type DashboardV3Data, type RecordsStats, type TrainingJob } from '../api';
import { getRuntimeConfig } from '../stores/runtimeConfig';
import { exportExcel, loadRecords, recordsStore, type RecordsKind } from '../stores/records';
import { restoreDrawRecord } from '../stores/draw';
import { uiStore } from '../stores/ui';
import { parseDrawLoras } from '../drawLoras';
import DashboardOverview from './DashboardOverview';

const kindOptions = [
  { label: '招聘 Agent 对话', value: 'agent' },
  { label: 'AI 绘画', value: 'draw' },
  { label: '提示词 Agent', value: 'prompt' },
  { label: 'AI 动画', value: 'video' },
];

// 数据库字段名到中文表头的映射
const headerMap: Record<RecordsKind, Record<string, string>> = {
  agent: {
    id: 'ID',
    session_id: '会话ID',
    created_at: '对话时间',
    sender: '发送人',
    content: '对话内容',
    retrieval_score: '检索匹配度',
    source: '来源',
  },
  draw: {
    id: 'ID',
    batch_id: '批次ID',
    group_index: '组号',
    started_at: '任务开始时间',
    finished_at: '任务结束时间',
    duration_seconds: '任务耗时(秒)',
    prompt: '提示词',
    prompt_translation: '提示词翻译',
    negative_prompt: '负面提示词',
    negative_translation: '负面提示词翻译',
    width: '宽度',
    height: '高度',
    steps: '步数',
    cfg: 'CFG',
    model: '模型',
    lora_anima_turbo: 'anima-turbo-lora-v0.2',
    lora_high_contrast: 'high-contrast aesthetic',
    image_path: '图片路径',
    image_url: '图片地址',
    seed: '随机种子',
    status: '状态',
    error: '错误信息',
  },
  prompt: {
    id: 'ID',
    started_at: '任务开始时间',
    finished_at: '任务结束时间',
    duration_seconds: '任务耗时(秒)',
    mode: '模式',
    user_input: '用户输入',
    image_path: '图片路径',
    description: '原始描述',
    prompt_result: '生成提示词',
    model: '模型',
    status: '状态',
  },
  video: {
    id: 'ID',
    job_id: '任务ID',
    script_id: '剧本ID',
    keyframe_name: '关键帧',
    video_name: '成片文件',
    prompt: '正向提示词',
    negative_prompt: '负面提示词',
    model: '模型',
    loras: 'LoRA',
    seed: '随机种子',
    width: '宽度',
    height: '高度',
    frames: '帧数',
    fps: '帧率',
    duration_seconds: '耗时(秒)',
    status: '状态',
    error: '错误信息',
    created_at: '创建时间',
    finished_at: '结束时间',
  },
};

// 把英文枚举值显示成中文
function formatValue(key: string, value: unknown): string {
  if (key === 'sender') return value === 'assistant' ? '大模型' : value === 'user' ? '用户' : String(value ?? '');
  if (key === 'source') return value === 'llm' ? '大模型回答' : value === 'fallback' ? '检索回答' : String(value ?? '');
  if (key === 'status') {
    if (value === 'success' || value === 'done') return '成功';
    if (value === 'running') return '进行中';
    if (value === 'error') return '失败';
    if (value === 'stopped') return '已停止';
    if (value === 'interrupted') return '已中断';
    return String(value ?? '');
  }
  if (key === 'mode') return value === 'image' ? '图片' : value === 'text' ? '文字' : String(value ?? '');
  if (key === 'loras_json') {
    return parseDrawLoras({ loras_json: String(value ?? '') }).join('、') || '无';
  }
  if (key === 'lora_anima_turbo' || key === 'lora_high_contrast') return value === 1 || value === '1' ? '是' : '否';
  return String(value ?? '');
}

// 统一数值展示，避免出现科学计数法
function formatNumber(value: number | undefined | null, digits = 10): string {
  if (value == null) return '-';
  return Number(value)
    .toFixed(digits)
    .replace(/\.?0+$/, '');
}

// 长文本字段需要省略号 + Popover 查看
const wrapKeys = new Set([
  'prompt',
  'prompt_translation',
  'negative_prompt',
  'negative_translation',
  'loras_json',
  'content',
  'description',
  'prompt_result',
  'user_input',
  'image_path',
  'image_url',
  'error',
]);

// 一键复制到剪贴板
async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    message.success('已复制');
  } catch (e) {
    message.error('复制失败');
  }
}

function renderStatusTags(status?: Record<string, number>) {
  if (!status || Object.keys(status).length === 0) return <Tag>暂无</Tag>;
  return Object.entries(status).map(([key, value]) => (
    <Tag key={key}>
      {key}: {value}
    </Tag>
  ));
}

interface PromptStatItem {
  tag: string;
  count: number;
  percent: number;
  translation?: string;
}

interface PromptStats {
  total_tags: number;
  total_images: number;
  top: number;
  items: PromptStatItem[];
}

interface PromptOverviewItem {
  tag: string;
  translation?: string;
}

interface PromptOverview {
  total: number;
  items: PromptOverviewItem[];
}

export default function RecordsPanel() {
  const { kind, page, pageSize, dateFrom, dateTo, data, loading } = recordsStore;
  const queryConfig = getRuntimeConfig().query;
  const [view, setView] = useState<'dashboard' | 'records' | 'stats' | 'overview' | 'summary' | 'modules' | 'train'>('dashboard');
  const [rangePreset, setRangePreset] = useState<'5' | '7' | '30' | '90' | 'custom'>('7');
  const [dashboardSort, setDashboardSort] = useState<'default' | 'recent'>(() => {
    const stored = localStorage.getItem('rider-studio:dashboard-sort-v1');
    return stored === 'recent' ? 'recent' : 'default';
  });
  const [dashboardData, setDashboardData] = useState<DashboardV3Data | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardRefreshKey, setDashboardRefreshKey] = useState(0);
  const [topN, setTopN] = useState(queryConfig.prompt_stats_top_default);
  const [stats, setStats] = useState<PromptStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [overview, setOverview] = useState<PromptOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [summary, setSummary] = useState<RecordsStats | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [moduleData, setModuleData] = useState<Record<string, any> | null>(null);
  const [moduleLoading, setModuleLoading] = useState(false);
  const [trainingJobs, setTrainingJobs] = useState<TrainingJob[]>([]);
  const [trainingLoading, setTrainingLoading] = useState(false);
  const [selectedTrainIds, setSelectedTrainIds] = useState<string[]>([]);
  const [recordsRefreshKey, setRecordsRefreshKey] = useState(0);
  const [statsRefreshKey, setStatsRefreshKey] = useState(0);
  const [overviewRefreshKey, setOverviewRefreshKey] = useState(0);
  const [summaryRefreshKey, setSummaryRefreshKey] = useState(0);
  const [moduleRefreshKey, setModuleRefreshKey] = useState(0);
  const [trainingRefreshKey, setTrainingRefreshKey] = useState(0);

  useEffect(() => {
    localStorage.setItem('rider-studio:dashboard-sort-v1', dashboardSort);
  }, [dashboardSort]);

  useEffect(() => {
    if (rangePreset === 'custom') return;
    const end = dayjs();
    recordsStore.dateFrom = end.subtract(Number(rangePreset) - 1, 'day').format('YYYY-MM-DD');
    recordsStore.dateTo = end.format('YYYY-MM-DD');
    recordsStore.page = 1;
  }, [rangePreset]);

  useEffect(() => {
    void loadRecords();
  }, [kind, page, pageSize, dateFrom, dateTo, recordsRefreshKey]);

  // 提示词统计随日期和 Top N 变化自动刷新
  useEffect(() => {
    if (view !== 'stats') return;
    let cancelled = false;
    setStatsLoading(true);
    api
      .get<PromptStats>('/records/prompt-stats', {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          top: topN,
        },
      })
      .then((res) => {
        if (!cancelled) setStats(res.data);
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      })
      .finally(() => {
        if (!cancelled) setStatsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, dateFrom, dateTo, topN, statsRefreshKey]);

  // 提示词总览随日期变化自动刷新
  useEffect(() => {
    if (view !== 'overview') return;
    let cancelled = false;
    setOverviewLoading(true);
    api
      .get<PromptOverview>('/records/prompt-overview', {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      })
      .then((res) => {
        if (!cancelled) setOverview(res.data);
      })
      .catch(() => {
        if (!cancelled) setOverview(null);
      })
      .finally(() => {
        if (!cancelled) setOverviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, dateFrom, dateTo, overviewRefreshKey]);

  useEffect(() => {
    if (view !== 'dashboard') return;
    let cancelled = false;
    setDashboardLoading(true);
    api
      .get<DashboardV3Data>('/records/dashboard/v3', {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      })
      .then((res) => {
        if (!cancelled) setDashboardData(res.data);
      })
      .catch(() => {
        if (!cancelled) setDashboardData(null);
      })
      .finally(() => {
        if (!cancelled) setDashboardLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, dateFrom, dateTo, dashboardRefreshKey]);

  // 统计总览
  useEffect(() => {
    if (view !== 'summary') return;
    let cancelled = false;
    setSummaryLoading(true);
    api
      .get<RecordsStats>('/records/stats', {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      })
      .then((res) => {
        if (!cancelled) setSummary(res.data);
      })
      .catch(() => {
        if (!cancelled) setSummary(null);
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, dateFrom, dateTo, summaryRefreshKey]);

  useEffect(() => {
    if (view !== 'modules') return;
    let cancelled = false;
    setModuleLoading(true);
    api
      .get<Record<string, any>>('/records/module-summary/v2')
      .then((res) => {
        if (!cancelled) setModuleData(res.data);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setModuleLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, moduleRefreshKey]);

  useEffect(() => {
    if (view !== 'train') return;
    let cancelled = false;
    setTrainingLoading(true);
    api
      .get<{ jobs: TrainingJob[] }>('/train/history')
      .then((res) => {
        if (!cancelled) setTrainingJobs(res.data.jobs || []);
      })
      .catch(() => {
        if (!cancelled) setTrainingJobs([]);
      })
      .finally(() => {
        if (!cancelled) setTrainingLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, trainingRefreshKey]);

  const handleRefresh = () => {
    if (view === 'dashboard') setDashboardRefreshKey((value) => value + 1);
    else if (view === 'records') setRecordsRefreshKey((value) => value + 1);
    else if (view === 'stats') setStatsRefreshKey((value) => value + 1);
    else if (view === 'overview') setOverviewRefreshKey((value) => value + 1);
    else if (view === 'summary') setSummaryRefreshKey((value) => value + 1);
    else if (view === 'modules') setModuleRefreshKey((value) => value + 1);
    else setTrainingRefreshKey((value) => value + 1);
  };

  const handleRestore = (record: Record<string, unknown>) => {
    restoreDrawRecord(record);
    message.success('已恢复到 AI 绘画预览区');
  };

  // 记录列表动态列
  const keys = data?.items?.[0] ? Object.keys(data.items[0]) : [];
  const columns: ColumnsType<Record<string, unknown>> = keys.map((key) => {
    const isWrap = wrapKeys.has(key);
    return {
      title: headerMap[kind][key] || key,
      dataIndex: key,
      key,
      ellipsis: !isWrap,
      render: (value: unknown) => {
        const text = formatValue(key, value);
        if (!isWrap) return text;
        return (
          <div className="cell-action">
            <Popover
              trigger="hover"
              placement="topLeft"
              title={headerMap[kind][key] || key}
              content={<div className="popover-text">{text}</div>}
            >
              <span className="cell-ellipsis">{text}</span>
            </Popover>
            {key === 'prompt' && (
              <Button size="small" type="link" onClick={() => void copyText(String(value ?? ''))}>
                复制
              </Button>
            )}
          </div>
        );
      },
    };
  });
  if (kind === 'draw') {
    columns.push({
      title: '操作',
      key: 'restore',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <Button size="small" onClick={() => handleRestore(record)}>
          恢复预览
        </Button>
      ),
    });
  }

  // 提示词统计表格
  const statRows = (stats?.items || []).map((item, index) => ({ ...item, rank: index + 1 }));
  const statColumns: ColumnsType<PromptStatItem & { rank: number }> = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 70 },
    { title: '提示词', dataIndex: 'tag', key: 'tag' },
    { title: '中文翻译', dataIndex: 'translation', key: 'translation', width: 180, render: (value: string) => value || '暂无翻译' },
    { title: '使用次数', dataIndex: 'count', key: 'count', width: 110 },
    { title: '占比(%)', dataIndex: 'percent', key: 'percent', width: 110 },
  ];
  const chartData = statRows.slice(0, 20);
  const dailyData = (summary?.daily || []).map((item) => ({ date: item.date, count: item.count, avg_duration: item.avg_duration }));
  const modelData = Object.entries(summary?.model_counts || {}).map(([model, count]) => ({ model, count }));
  const sizeData = Object.entries(summary?.size_counts || {}).map(([size, count]) => ({ size, count }));
  const overviewColumns: ColumnsType<PromptOverviewItem> = [
    { title: '提示词', dataIndex: 'tag', key: 'tag' },
    { title: '中文翻译', dataIndex: 'translation', key: 'translation', width: 220, render: (value: string) => value || '暂无翻译' },
  ];

  const statusColor = (status?: string) =>
    status === 'done' ? 'green' : status === 'running' ? 'blue' : status === 'error' ? 'red' : 'orange';
  const statusText = (status?: string) =>
    status === 'done' ? '完成' : status === 'running' ? '训练中' : status === 'error' ? '失败' : status === 'stopped' ? '已停止' : String(status || '-');
  const trainColumns: ColumnsType<TrainingJob> = [
    { title: '训练时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (value: string) => value || '-' },
    { title: '输出名', dataIndex: 'output_name', key: 'output_name', ellipsis: true, render: (value: string) => value || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (value: string) => <Tag color={statusColor(value)}>{statusText(value)}</Tag>,
    },
    { title: '分辨率', dataIndex: 'resolution', key: 'resolution', width: 100, render: (value: number) => (value ? `${value}×${value}` : '-') },
    { title: '重复次数', dataIndex: 'repeats', key: 'repeats', width: 90, render: (value: number) => value ?? '-' },
    { title: 'Batch', dataIndex: 'batch_size', key: 'batch_size', width: 70, render: (value: number) => value ?? '-' },
    { title: 'dim', dataIndex: 'network_dim', key: 'network_dim', width: 70, render: (value: number) => value ?? '-' },
    { title: 'alpha', dataIndex: 'network_alpha', key: 'network_alpha', width: 70, render: (value: number) => value ?? '-' },
    { title: '学习率', dataIndex: 'learning_rate', key: 'learning_rate', width: 110, render: (value: number) => formatNumber(value) },
    { title: '轮数', dataIndex: 'epochs', key: 'epochs', width: 70, render: (value: number) => value ?? '-' },
    { title: '保存间隔', dataIndex: 'save_every', key: 'save_every', width: 90, render: (value: number) => value ?? '-' },
    { title: '最大步数', dataIndex: 'max_steps', key: 'max_steps', width: 90, render: (value: number) => value ?? '-' },
    {
      title: '已走步数',
      dataIndex: 'steps_done',
      key: 'steps_done',
      width: 110,
      render: (value: number, record) => `${value ?? 0}/${record.steps_total ?? 0}`,
    },
    { title: '最低 Loss', dataIndex: 'min_loss', key: 'min_loss', width: 100, render: (value: number) => formatNumber(value, 4) },
    { title: '时长', dataIndex: 'duration_seconds', key: 'duration_seconds', width: 90, render: (value: number) => (value == null ? '-' : `${Math.round(Number(value))}s`) },
  ];
  const selectedTrainJobs = trainingJobs.filter((job) => selectedTrainIds.includes(job.job_id));
  const trainChartData = selectedTrainJobs.flatMap((job) =>
    (job.loss_history || []).map((point) => ({ step: point.step, loss: point.loss, job: job.output_name || job.job_id })),
  );
  const compareRows =
    selectedTrainJobs.length === 2
      ? [
          ['训练时间', selectedTrainJobs[0].created_at || '-', selectedTrainJobs[1].created_at || '-'],
          ['输出名', selectedTrainJobs[0].output_name || '-', selectedTrainJobs[1].output_name || '-'],
          ['分辨率', selectedTrainJobs[0].resolution ? `${selectedTrainJobs[0].resolution}×${selectedTrainJobs[0].resolution}` : '-', selectedTrainJobs[1].resolution ? `${selectedTrainJobs[1].resolution}×${selectedTrainJobs[1].resolution}` : '-'],
          ['重复次数', selectedTrainJobs[0].repeats ?? '-', selectedTrainJobs[1].repeats ?? '-'],
          ['Batch', selectedTrainJobs[0].batch_size ?? '-', selectedTrainJobs[1].batch_size ?? '-'],
          ['dim', selectedTrainJobs[0].network_dim ?? '-', selectedTrainJobs[1].network_dim ?? '-'],
          ['alpha', selectedTrainJobs[0].network_alpha ?? '-', selectedTrainJobs[1].network_alpha ?? '-'],
          ['学习率', formatNumber(selectedTrainJobs[0].learning_rate), formatNumber(selectedTrainJobs[1].learning_rate)],
          ['轮数', selectedTrainJobs[0].epochs ?? '-', selectedTrainJobs[1].epochs ?? '-'],
          ['保存间隔', selectedTrainJobs[0].save_every ?? '-', selectedTrainJobs[1].save_every ?? '-'],
          ['最大步数', selectedTrainJobs[0].max_steps ?? '-', selectedTrainJobs[1].max_steps ?? '-'],
          ['已走步数', `${selectedTrainJobs[0].steps_done ?? 0}/${selectedTrainJobs[0].steps_total ?? 0}`, `${selectedTrainJobs[1].steps_done ?? 0}/${selectedTrainJobs[1].steps_total ?? 0}`],
          ['最低 Loss', formatNumber(selectedTrainJobs[0].min_loss, 4), formatNumber(selectedTrainJobs[1].min_loss, 4)],
          ['时长', selectedTrainJobs[0].duration_seconds == null ? '-' : `${Math.round(selectedTrainJobs[0].duration_seconds)}s`, selectedTrainJobs[1].duration_seconds == null ? '-' : `${Math.round(selectedTrainJobs[1].duration_seconds)}s`],
        ]
      : [];

  return (
    <div className="panel-box records-box">
      <div className="records-bar">
        <Segmented
          value={view}
          options={[
            { label: '总览', value: 'dashboard' },
            { label: '记录列表', value: 'records' },
            { label: '绘画统计', value: 'summary' },
            { label: '模块概览', value: 'modules' },
            { label: '提示词统计', value: 'stats' },
            { label: '提示词总览', value: 'overview' },
            { label: '训练历史', value: 'train' },
          ]}
          onChange={(value) => setView(value as 'dashboard' | 'records' | 'stats' | 'overview' | 'summary' | 'modules' | 'train')}
        />
        {view === 'records' ? (
          <Tooltip title="记录类型：招聘 Agent 对话 / AI 绘画 / 提示词 Agent / AI 动画。">
            <Select
              value={kind}
              options={kindOptions}
              onChange={(value) => {
                recordsStore.kind = value as RecordsKind;
                recordsStore.page = 1;
              }}
              style={{ width: 160 }}
            />
          </Tooltip>
        ) : null}
        <Select
          value={rangePreset}
          options={[
            { label: '近 5 天', value: '5' },
            { label: '近 7 天', value: '7' },
            { label: '近 30 天', value: '30' },
            { label: '近 90 天', value: '90' },
            { label: '自定义', value: 'custom' },
          ]}
          onChange={(value) => setRangePreset(value as '5' | '7' | '30' | '90' | 'custom')}
          style={{ width: 112 }}
        />
        <Tooltip title="按开始/创建时间筛选。">
          <DatePicker.RangePicker
            value={[dateFrom ? dayjs(dateFrom) : null, dateTo ? dayjs(dateTo) : null]}
            onChange={(dates: [Dayjs | null, Dayjs | null] | null) => {
              recordsStore.dateFrom = dates?.[0] ? dates[0].format('YYYY-MM-DD') : '';
              recordsStore.dateTo = dates?.[1] ? dates[1].format('YYYY-MM-DD') : '';
              setRangePreset('custom');
              recordsStore.page = 1;
            }}
          />
        </Tooltip>
        {view === 'dashboard' ? (
          <Select
            value={dashboardSort}
            options={[
              { label: '默认排序', value: 'default' },
              { label: '按近期使用', value: 'recent' },
            ]}
            onChange={(value) => setDashboardSort(value as 'default' | 'recent')}
            style={{ width: 120 }}
          />
        ) : null}
        {view === 'records' ? (
          <>
            <Tooltip title="每页显示的记录条数。">
              <Select
                value={pageSize}
                options={Array.from(
                  new Set([queryConfig.records_page_size_default, queryConfig.records_page_size_max]),
                ).map((value) => ({ label: `${value} 条/页`, value }))}
                onChange={(value) => {
                  recordsStore.pageSize = value;
                  recordsStore.page = 1;
                }}
                style={{ width: 120 }}
              />
            </Tooltip>
            <Button onClick={exportExcel}>导出 Excel</Button>
          </>
        ) : view === 'stats' ? (
          <>
            <Tooltip title="提示词统计中最多展示的标签数量。">
              <span>Top N</span>
            </Tooltip>
            <InputNumber
              min={queryConfig.page_min}
              max={queryConfig.prompt_stats_top_max}
              value={topN}
              onChange={(value) => setTopN(value ?? queryConfig.prompt_stats_top_default)}
            />
          </>
        ) : null}
        <Button
          icon={<ReloadOutlined />}
          loading={
            view === 'dashboard'
              ? dashboardLoading
              : view === 'records'
                ? loading
                : view === 'stats'
                  ? statsLoading
                  : view === 'overview'
                    ? overviewLoading
                    : view === 'summary'
                      ? summaryLoading
                      : view === 'modules'
                        ? moduleLoading
                        : trainingLoading
          }
          onClick={handleRefresh}
        >
          刷新
        </Button>
      </div>

      {view === 'dashboard' ? (
        <DashboardOverview data={dashboardData} loading={dashboardLoading} sort={dashboardSort} />
      ) : view === 'records' ? (
        <Table
          rowKey={(record) => String(record.id ?? '')}
          columns={columns}
          dataSource={data?.items || []}
          loading={loading}
          size="small"
          scroll={{ x: true }}
          pagination={{
            current: page,
            pageSize,
            total: data?.total || 0,
            showSizeChanger: false,
            showTotal: (total) => <Tag>共 {total} 条</Tag>,
            onChange: (nextPage) => {
              recordsStore.page = nextPage;
            },
          }}
        />
      ) : view === 'stats' ? (
        <>
          <div className="stats-summary">
            <Tag>共 {stats?.total_tags ?? 0} 个标签</Tag>
            <Tag>统计图片 {stats?.total_images ?? 0} 张</Tag>
          </div>
          <Table
            rowKey="tag"
            columns={statColumns}
            dataSource={statRows}
            loading={statsLoading}
            size="small"
            pagination={false}
          />
          <div className="chart-box">
            <Column
              data={chartData}
              xField="tag"
              yField="count"
              height={320}
              label={{ position: 'top' }}
              xAxis={{ label: { autoRotate: true, autoHide: true } }}
              tooltip={{
                title: (datum: any) => `${datum.tag}（${datum.translation || '暂无翻译'}）`,
                items: [{ channel: 'y', name: '使用次数', valueFormatter: (d: any) => `${d} 次` }],
              }}
            />
          </div>
        </>
      ) : view === 'summary' ? (
        <div className="summary-box">
          {summaryLoading && !summary ? (
            <div className="train-status-text">加载中...</div>
          ) : (
            <>
              <div className="stats-summary">
                {Object.entries(summary?.status_counts || {}).map(([key, value]) => (
                  <Tag key={key}>
                    {key}: {value}
                  </Tag>
                ))}
              </div>
              <div className="chart-box">
                <div className="chart-title">每日生成数量</div>
                <Column data={dailyData} xField="date" yField="count" height={260} label={{ position: 'top' }} />
              </div>
              <div className="chart-box">
                <div className="chart-title">模型分布</div>
                <Column data={modelData} xField="model" yField="count" height={260} xAxis={{ label: { autoRotate: true, autoHide: true } }} />
              </div>
              <div className="chart-box">
                <div className="chart-title">尺寸分布</div>
                <Column data={sizeData} xField="size" yField="count" height={220} xAxis={{ label: { autoRotate: true, autoHide: true } }} />
              </div>
            </>
          )}
        </div>
      ) : view === 'modules' ? (
        <div className="summary-box">
          {moduleLoading && !moduleData ? (
            <div className="train-status-text">加载中...</div>
          ) : (
            <>
              <div className="module-system-bar">
                <b>系统状态</b>
                <Tag color={moduleData?.system?.busy ? 'orange' : 'green'}>
                  {moduleData?.system?.busy ? '有任务运行' : '空闲'}
                </Tag>
                <Tag>
                  GPU {moduleData?.system?.gpu_used_mb ?? 0} / {moduleData?.system?.gpu_total_mb ?? 0} MB
                </Tag>
                {((moduleData?.system?.active_models as { name: string; size_mb: number }[]) || []).map((model) => (
                  <Tag key={model.name} color="blue">
                    {model.name}
                  </Tag>
                ))}
              </div>
              <div className="module-card-grid">
                <div className="module-card" onClick={() => { uiStore.activeTab = 'train'; }}>
                  <div className="module-card-header">
                    <b>LoRA 训练</b>
                    <Tag>{moduleData?.train?.count ?? 0} 次</Tag>
                  </div>
                  <div className="module-card-stats">{renderStatusTags(moduleData?.train?.status)}</div>
                  <Column data={moduleData?.train?.daily || []} xField="date" yField="count" height={100} />
                  <div className="module-card-footer">
                    <span>失败率 {Math.round((moduleData?.train?.error_rate ?? 0) * 100)}%</span>
                    <span>平均 {(moduleData?.train?.avg_duration ?? 0)}s</span>
                    <span>产物 {moduleData?.train?.output_count ?? 0}</span>
                  </div>
                  {moduleData?.train?.recent_errors?.length ? (
                    <div className="module-error-text">最近错误：{moduleData.train.recent_errors[0]}</div>
                  ) : null}
                </div>

                <div className="module-card" onClick={() => { uiStore.activeTab = 'video'; }}>
                  <div className="module-card-header">
                    <b>AI 动画</b>
                    <Tag>{moduleData?.video?.count ?? 0} 个视频</Tag>
                  </div>
                  <div className="module-card-stats">{renderStatusTags(moduleData?.video?.status)}</div>
                  <Column data={moduleData?.video?.daily || []} xField="date" yField="count" height={100} />
                  <div className="module-card-footer">
                    <span>失败率 {Math.round((moduleData?.video?.error_rate ?? 0) * 100)}%</span>
                    <span>平均 {(moduleData?.video?.avg_duration ?? 0)}s</span>
                  </div>
                  {moduleData?.video?.recent_errors?.length ? (
                    <div className="module-error-text">最近错误：{moduleData.video.recent_errors[0]}</div>
                  ) : null}
                </div>

                <div className="module-card" onClick={() => { uiStore.activeTab = 'draw'; }}>
                  <div className="module-card-header">
                    <b>批量绘画</b>
                    <Tag>{moduleData?.batch?.count ?? 0} 批</Tag>
                  </div>
                  <div className="module-card-stats">{renderStatusTags(moduleData?.batch?.status)}</div>
                  <Column data={moduleData?.batch?.daily || []} xField="date" yField="count" height={100} />
                  <div className="module-card-footer">
                    <span>失败率 {Math.round((moduleData?.batch?.error_rate ?? 0) * 100)}%</span>
                    <span>平均 {(moduleData?.batch?.avg_duration ?? 0)}s</span>
                  </div>
                  {moduleData?.batch?.recent_errors?.length ? (
                    <div className="module-error-text">最近错误：{moduleData.batch.recent_errors[0]}</div>
                  ) : null}
                </div>

                <div className="module-card" onClick={() => { uiStore.activeTab = 'draw'; }}>
                  <div className="module-card-header">
                    <b>图片库</b>
                    <Tag>{moduleData?.image_library?.count ?? 0} 张</Tag>
                  </div>
                  <div className="module-card-stats">
                    <Tag>今日 {moduleData?.image_library?.today_count ?? 0}</Tag>
                    {Object.entries((moduleData?.image_library?.model_counts as Record<string, number>) || {})
                      .slice(0, 3)
                      .map(([key, value]) => (
                        <Tag key={key}>
                          {key}: {value}
                        </Tag>
                      ))}
                  </div>
                  <Column data={moduleData?.image_library?.daily || []} xField="date" yField="count" height={100} />
                  <div className="module-card-footer">
                    {Object.entries((moduleData?.image_library?.size_counts as Record<string, number>) || {})
                      .slice(0, 2)
                      .map(([key, value]) => (
                        <span key={key}>
                          {key}×{value}
                        </span>
                      ))}
                  </div>
                </div>

                <div className="module-card" onClick={() => { uiStore.activeTab = 'prompt'; }}>
                  <div className="module-card-header">
                    <b>提示词集</b>
                    <Tag>{moduleData?.prompt_sets?.count ?? 0} 条</Tag>
                  </div>
                  <div className="module-card-stats">
                    {Object.entries((moduleData?.prompt_sets?.by_type as Record<string, number>) || {}).map(([key, value]) => (
                      <Tag key={key}>
                        {key}: {value}
                      </Tag>
                    ))}
                    <Tag>未使用 {moduleData?.prompt_sets?.unused_count ?? 0}</Tag>
                  </div>
                  <div className="module-card-list">
                    Top：{((moduleData?.prompt_sets?.top_used as { name?: string; use_count?: number }[]) || []).map((item) => `${item.name}(${item.use_count ?? 0})`).join('、') || '暂无'}
                  </div>
                </div>

                <div className="module-card" onClick={() => { uiStore.activeTab = 'companion'; }}>
                  <div className="module-card-header">
                    <b>情感陪伴</b>
                    <Tag>{moduleData?.companion?.messages ?? 0} 条</Tag>
                  </div>
                  <div className="module-card-stats">
                    <Tag>会话 {moduleData?.companion?.sessions ?? 0}</Tag>
                    <Tag>今日活跃 {moduleData?.companion?.active_sessions ?? 0}</Tag>
                    <Tag>记忆 {moduleData?.companion?.memories ?? 0}</Tag>
                  </div>
                  <div className="module-card-list">
                    {Object.entries((moduleData?.companion?.by_persona as Record<string, number>) || {}).map(([key, value]) => (
                      <span key={key}>
                        {key}: {value} 条
                      </span>
                    ))}
                  </div>
                  <div className="module-card-footer">
                    {Object.entries((moduleData?.companion?.recent_emotions as Record<string, number>) || {}).map(([key, value]) => (
                      <span key={key}>
                        {key} {value}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      ) : view === 'train' ? (
        <div className="summary-box">
          {trainingLoading && trainingJobs.length === 0 ? (
            <div className="train-status-text">加载中...</div>
          ) : (
            <>
              <Table
                rowKey="job_id"
                columns={trainColumns}
                dataSource={trainingJobs}
                loading={trainingLoading}
                size="small"
                scroll={{ x: true }}
                pagination={{ pageSize: 10, showSizeChanger: false }}
                rowSelection={{
                  selectedRowKeys: selectedTrainIds,
                  onChange: (keys) => setSelectedTrainIds(keys.map(String).slice(-2)),
                }}
              />
              <div className="stats-summary">
                <Tag>已选 {selectedTrainJobs.length}/2</Tag>
              </div>
              {trainChartData.length > 0 ? (
                <div className="chart-box">
                  <div className="chart-title">{selectedTrainJobs.length === 2 ? 'Loss 曲线对比' : 'Loss 曲线'}</div>
                  <Line data={trainChartData} xField="step" yField="loss" seriesField="job" height={320} point={{ size: 2 }} />
                </div>
              ) : selectedTrainJobs.length > 0 ? (
                <div className="train-status-text" style={{ marginTop: 10 }}>
                  所选记录暂无 Loss 数据
                </div>
              ) : null}
              {compareRows.length > 0 ? (
                <div className="chart-box">
                  <div className="chart-title">参数对比</div>
                  <Table
                    rowKey="label"
                    size="small"
                    pagination={false}
                    columns={[
                      { title: '参数', dataIndex: 'label', key: 'label', width: 120 },
                      { title: 'A', dataIndex: 'a', key: 'a' },
                      { title: 'B', dataIndex: 'b', key: 'b' },
                    ]}
                    dataSource={compareRows.map((row) => ({ label: row[0], a: row[1], b: row[2] }))}
                  />
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : (
        <Table
          rowKey="tag"
          columns={overviewColumns}
          dataSource={overview?.items || []}
          loading={overviewLoading}
          size="small"
          pagination={{
            pageSize: 20,
            showSizeChanger: false,
            showTotal: (total) => <Tag>共 {total} 个</Tag>,
          }}
        />
      )}
    </div>
  );
}
