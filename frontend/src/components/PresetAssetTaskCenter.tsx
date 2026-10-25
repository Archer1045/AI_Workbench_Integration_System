import {
  EyeOutlined,
  ReloadOutlined,
  StopOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Collapse,
  Drawer,
  Empty,
  List,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  message,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import type {
  PresetAssetJob,
  PresetAssetJobItem,
} from '../api';
import {
  apiErrorMessage,
  cancelPresetAssetTask,
  loadPresetAssetJobs,
  presetAssetStore,
  retryPresetAssetTask,
  retryPresetAssetTaskItem,
  type PresetAssetSelection,
} from '../stores/presetAssetStore';
import type { PresetAssetTaskFilter } from '../presetAssetPageState';
import type { PresetAssetTaskStatusFilter } from '../presetAssetPageState';

const ACTIVE_STATUSES = new Set([
  'queued',
  'preparing',
  'running',
  'cancel_requested',
]);
const RECOVERABLE_ITEM_STATUSES = new Set([
  'failed',
  'interrupted',
  'cancelled',
]);
const FAILED_ITEM_STATUSES = new Set(['failed', 'interrupted']);
const RECOVERABLE_JOB_STATUSES = new Set([
  'error',
  'interrupted',
  'cancelled',
]);
const ACTIVE_CANDIDATE_STATUSES = new Set([
  'queued',
  'preparing',
  'running',
  'cancel_requested',
]);
const RECOVERABLE_CANDIDATE_STATUSES = new Set([
  'failed',
  'interrupted',
]);
const CANCELLED_CANDIDATE_STATUSES = new Set(['cancelled', 'stopped']);

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  preparing: '准备中',
  running: '生成中',
  cancel_requested: '取消中',
  cancelled: '已取消',
  stopped: '已停止',
  interrupted: '已中断',
  error: '失败',
  failed: '失败',
  done: '已完成',
};

const STATUS_COLORS: Record<string, string> = {
  queued: 'gold',
  preparing: 'gold',
  running: 'processing',
  cancel_requested: 'orange',
  cancelled: 'default',
  stopped: 'default',
  interrupted: 'red',
  error: 'red',
  failed: 'red',
  done: 'green',
};

interface FailureReason {
  label: string;
  color: string;
}

const FAILURE_REASON_BY_CODE: Record<string, FailureReason> = {
  generation_timeout: { label: '超时', color: 'gold' },
  generation_service_unavailable: {
    label: '生成服务不可用',
    color: 'red',
  },
  gpu_busy: { label: 'GPU/显存忙碌', color: 'volcano' },
  generation_failed: { label: '生成失败', color: 'red' },
  invalid_parameters: { label: '参数问题', color: 'orange' },
  invalid_preset: { label: '预设问题', color: 'orange' },
  cancelled: { label: '已取消', color: 'default' },
};

const FAILURE_REASON_BY_ACTION: Record<string, FailureReason> = {
  wait_and_retry: { label: '超时', color: 'gold' },
  start_service: { label: '生成服务不可用', color: 'red' },
  free_gpu: { label: 'GPU/显存忙碌', color: 'volcano' },
  fix_parameters: { label: '参数问题', color: 'orange' },
  review_preset: { label: '预设问题', color: 'orange' },
  retry: { label: '生成失败', color: 'red' },
};

const FAILURE_REASON_RULES: Array<{
  reason: FailureReason;
  keywords: string[];
}> = [
  {
    reason: { label: '超时', color: 'gold' },
    keywords: ['timeout', 'timed out', 'deadline', '超时'],
  },
  {
    reason: { label: 'GPU/显存忙碌', color: 'volcano' },
    keywords: [
      'gpu',
      'cuda',
      'oom',
      'out of memory',
      '显存',
      'busy',
      '忙碌',
      '等待其他重任务',
    ],
  },
  {
    reason: { label: '生成服务不可用', color: 'red' },
    keywords: [
      'comfyui',
      'ollama',
      'connection',
      'econnrefused',
      'refused',
      'unavailable',
      '连接',
      '服务不可用',
      '502',
      '503',
    ],
  },
  {
    reason: { label: '参数或预设问题', color: 'orange' },
    keywords: [
      '参数',
      '预设不存在',
      '尺寸',
      'seed',
      '提示词',
      '非法',
      '范围',
      '校验',
      'invalid',
      'validation',
    ],
  },
  {
    reason: { label: '生成失败', color: 'red' },
    keywords: ['生成失败', 'generation failed', 'failed to generate'],
  },
];

const STATUS_FILTER_OPTIONS: {
  label: string;
  value: Exclude<PresetAssetTaskStatusFilter, ''>;
}[] = [
  { label: '排队中', value: 'queued' },
  { label: '准备中', value: 'preparing' },
  { label: '生成中', value: 'running' },
  { label: '取消中', value: 'cancel_requested' },
  { label: '已完成', value: 'done' },
  { label: '失败', value: 'error' },
  { label: '已取消', value: 'cancelled' },
  { label: '已停止', value: 'stopped' },
  { label: '已中断', value: 'interrupted' },
];

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

function jobItems(job: PresetAssetJob): PresetAssetJobItem[] {
  return job.items || [];
}

function candidatesForItem(
  job: PresetAssetJob,
  item: PresetAssetJobItem,
): PresetAssetJob['candidates'] {
  return (job.candidates || []).filter(
    (candidate) =>
      candidate.preset_type === item.preset_type &&
      candidate.preset_id === item.preset_id,
  );
}

function summarizeCandidates(candidates: PresetAssetJob['candidates']) {
  return {
    total: candidates.length,
    ready: candidates.filter((candidate) => candidate.status === 'ready')
      .length,
    active: candidates.filter((candidate) =>
      ACTIVE_CANDIDATE_STATUSES.has(candidate.status),
    ).length,
    failed: candidates.filter((candidate) =>
      RECOVERABLE_CANDIDATE_STATUSES.has(candidate.status),
    ).length,
    cancelled: candidates.filter((candidate) =>
      CANCELLED_CANDIDATE_STATUSES.has(candidate.status),
    ).length,
    adopted: candidates.filter((candidate) => candidate.status === 'adopted')
      .length,
  };
}

function summarizeItemCandidates(
  job: PresetAssetJob,
  item: PresetAssetJobItem,
) {
  if (typeof item.candidate_count === 'number') {
    return {
      total: item.candidate_count,
      ready: item.ready_count || 0,
      active: item.active_count || 0,
      failed: item.failed_count || 0,
      cancelled: item.cancelled_count || 0,
      adopted: item.adopted_count || 0,
    };
  }
  return summarizeCandidates(candidatesForItem(job, item));
}

function summarizeJobItems(items: PresetAssetJobItem[]) {
  return {
    done: items.filter((item) => item.status === 'done').length,
    active: items.filter((item) => ACTIVE_STATUSES.has(item.status)).length,
    failed: items.filter((item) => FAILED_ITEM_STATUSES.has(item.status))
      .length,
    cancelled: items.filter((item) =>
      CANCELLED_CANDIDATE_STATUSES.has(item.status),
    ).length,
  };
}

function jobActive(job: PresetAssetJob): boolean {
  return (
    ACTIVE_STATUSES.has(job.status) ||
    jobItems(job).some((item) => ACTIVE_STATUSES.has(item.status))
  );
}

function jobRecoverable(job: PresetAssetJob): boolean {
  return (
    !jobActive(job) &&
    (RECOVERABLE_JOB_STATUSES.has(job.status) ||
      jobItems(job).some((item) => RECOVERABLE_ITEM_STATUSES.has(item.status)))
  );
}

function jobMatchesFilter(
  job: PresetAssetJob,
  filter: PresetAssetTaskFilter,
): boolean {
  if (filter === 'all') return true;
  if (filter === 'active') return jobActive(job);
  if (filter === 'recoverable') return jobRecoverable(job);
  return !jobActive(job) && !jobRecoverable(job);
}

function jobMatchesStatus(
  job: PresetAssetJob,
  status: PresetAssetTaskStatusFilter,
): boolean {
  if (!status) return true;
  return (
    job.status === status ||
    jobItems(job).some((item) => item.status === status)
  );
}

function formatSnapshot(params: Record<string, unknown>): string {
  try {
    return JSON.stringify(params || {}, null, 2);
  } catch {
    return '{}';
  }
}

function itemFailureReason(
  item: PresetAssetJobItem,
): FailureReason | null {
  if (!item.error && !FAILED_ITEM_STATUSES.has(item.status)) return null;
  const failureCode = String(item.last_error_code || '').trim();
  if (failureCode && FAILURE_REASON_BY_CODE[failureCode]) {
    return FAILURE_REASON_BY_CODE[failureCode];
  }
  if (item.status === 'interrupted') {
    return { label: '任务中断', color: 'orange' };
  }
  if (item.status === 'cancelled') {
    return { label: '已取消', color: 'default' };
  }
  const userAction = String(item.user_action || '').trim();
  if (userAction && FAILURE_REASON_BY_ACTION[userAction]) {
    return FAILURE_REASON_BY_ACTION[userAction];
  }
  const normalized = String(item.error || '').trim().toLowerCase();
  for (const rule of FAILURE_REASON_RULES) {
    if (rule.keywords.some((keyword) => normalized.includes(keyword))) {
      return rule.reason;
    }
  }
  return { label: '待分类', color: 'default' };
}

function itemRetryable(job: PresetAssetJob, item: PresetAssetJobItem): boolean {
  return (
    !jobActive(job) &&
    (typeof item.retryable === 'boolean'
      ? item.retryable
      : RECOVERABLE_ITEM_STATUSES.has(item.status))
  );
}

export default function PresetAssetTaskCenter({
  open,
  onClose,
  onViewPreset,
  filter,
  onFilterChange,
  statusFilter,
  onStatusFilterChange,
  scrollTop,
  onScrollTopChange,
}: {
  open: boolean;
  onClose: () => void;
  onViewPreset: (selection: PresetAssetSelection) => void;
  filter: PresetAssetTaskFilter;
  onFilterChange: (filter: PresetAssetTaskFilter) => void;
  statusFilter: PresetAssetTaskStatusFilter;
  onStatusFilterChange: (status: PresetAssetTaskStatusFilter) => void;
  scrollTop: number;
  onScrollTopChange: (scrollTop: number) => void;
}) {
  const { jobs, jobPollErrors, loadingJobs } = presetAssetStore;
  const [workingJobId, setWorkingJobId] = useState<string | null>(null);
  const [workingItemKey, setWorkingItemKey] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const restoredKeyRef = useRef('');

  useEffect(() => {
    const container = scrollRef.current;
    const viewKey = `${filter}:${statusFilter}`;
    if (!open || !container || restoredKeyRef.current === viewKey) return;
    container.scrollTop = scrollTop;
    restoredKeyRef.current = viewKey;
  }, [filter, open, scrollTop, statusFilter]);

  const counts = useMemo(
    () => ({
      active: jobs.filter(
        (job) =>
          jobMatchesFilter(job, 'active') &&
          jobMatchesStatus(job, statusFilter),
      ).length,
      recoverable: jobs.filter(
        (job) =>
          jobMatchesFilter(job, 'recoverable') &&
          jobMatchesStatus(job, statusFilter),
      ).length,
      history: jobs.filter(
        (job) =>
          jobMatchesFilter(job, 'history') &&
          jobMatchesStatus(job, statusFilter),
      ).length,
      all: jobs.filter((job) => jobMatchesStatus(job, statusFilter)).length,
    }),
    [jobs, statusFilter],
  );
  const visibleJobs = useMemo(
    () =>
      jobs.filter(
        (job) =>
          jobMatchesFilter(job, filter) &&
          jobMatchesStatus(job, statusFilter),
      ),
    [filter, jobs, statusFilter],
  );

  const runJobAction = async (
    jobId: string,
    action: () => Promise<unknown>,
    success: string,
  ) => {
    setWorkingJobId(jobId);
    try {
      await action();
      message.success(success);
    } catch (error) {
      message.error(apiErrorMessage(error, '任务操作失败'));
    } finally {
      setWorkingJobId(null);
    }
  };

  const runItemAction = async (
    jobId: string,
    itemIndex: number,
    action: () => Promise<unknown>,
  ) => {
    const actionKey = `${jobId}:${itemIndex}`;
    setWorkingItemKey(actionKey);
    try {
      await action();
      message.success('该任务项已重新排队');
    } catch (error) {
      message.error(apiErrorMessage(error, '任务项重试失败'));
    } finally {
      setWorkingItemKey(null);
    }
  };

  const viewPreset = (item: PresetAssetJobItem) => {
    onViewPreset({
      presetType: item.preset_type,
      presetId: item.preset_id,
      label: item.preset_label || item.preset_id,
    });
    onClose();
  };

  return (
    <Drawer
      className="preset-asset-task-center"
      title="跨预设任务中心"
      width="min(780px, 100vw)"
      open={open}
      onClose={onClose}
      extra={
        <Tooltip title="重新读取后端持久化任务">
          <Button
            icon={<ReloadOutlined aria-hidden="true" />}
            loading={loadingJobs}
            onClick={() => {
              void loadPresetAssetJobs().catch((error) =>
                  message.error(apiErrorMessage(error, '任务列表加载失败')),
              );
            }}
          >
            刷新
          </Button>
        </Tooltip>
      }
    >
      <Alert
        className="preset-asset-task-center-note"
        type="info"
        showIcon
        message="任务状态保存在后端，切换预设或关闭工坊不会丢失；候选仍需人工验收。"
      />
      <Segmented
        block
        value={filter}
        onChange={(value) =>
          onFilterChange(value as PresetAssetTaskFilter)
        }
        options={[
          { label: `当前任务 ${counts.active}`, value: 'active' },
          { label: `可恢复 ${counts.recoverable}`, value: 'recoverable' },
          { label: `历史 ${counts.history}`, value: 'history' },
          { label: `全部 ${counts.all}`, value: 'all' },
        ]}
      />
      <div className="preset-asset-task-filters">
        <Select
          allowClear
          value={statusFilter || undefined}
          placeholder="全部任务状态"
          options={STATUS_FILTER_OPTIONS}
          onChange={(value) => onStatusFilterChange(value || '')}
        />
      </div>
      <Spin spinning={loadingJobs}>
        <div
          ref={scrollRef}
          className="preset-asset-task-scroll"
          onScroll={(event) =>
            onScrollTopChange(event.currentTarget.scrollTop)
          }
        >
          <List
            className="preset-asset-task-list"
            dataSource={visibleJobs}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="当前筛选下没有任务"
                />
              ),
            }}
            renderItem={(job) => {
              const total = job.total || 0;
              const done = job.done || 0;
              const percent = total > 0 ? Math.round((done / total) * 100) : 0;
              const active = jobActive(job);
              const recoverable = jobRecoverable(job);
              const retryable = jobItems(job).some((item) =>
                itemRetryable(job, item),
              );
              const busy = workingJobId === job.job_id;
              const firstItem = jobItems(job)[0];
              const candidateSummary = summarizeCandidates(job.candidates || []);
              const itemSummary = summarizeJobItems(jobItems(job));
              return (
                <List.Item className="preset-asset-task-card">
                <div className="preset-asset-task-card-main">
                  <div className="preset-asset-task-card-heading">
                    <Space wrap size={6}>
                      <Tag color={STATUS_COLORS[job.status] || 'default'}>
                        {statusLabel(job.status)}
                      </Tag>
                      <strong>
                        {jobItems(job).length} 个预设 / {total} 张候选
                      </strong>
                      <span className="help">{job.job_id.slice(0, 10)}</span>
                    </Space>
                    <Space wrap size={6}>
                      {active ? (
                        <Button
                          size="small"
                          danger
                          icon={<StopOutlined aria-hidden="true" />}
                          loading={busy}
                          onClick={() =>
                            void runJobAction(
                              job.job_id,
                              () => cancelPresetAssetTask(job.job_id),
                              '已提交取消请求',
                            )
                          }
                        >
                          取消
                        </Button>
                      ) : null}
                      {recoverable && retryable ? (
                        <Button
                          size="small"
                          icon={<ReloadOutlined aria-hidden="true" />}
                          loading={busy}
                          onClick={() =>
                            void runJobAction(
                              job.job_id,
                              () => retryPresetAssetTask(job.job_id),
                              '失败项已重新排队',
                            )
                          }
                        >
                          重试失败项
                        </Button>
                      ) : null}
                      {firstItem ? (
                        <Button
                          size="small"
                          icon={<EyeOutlined aria-hidden="true" />}
                          onClick={() => viewPreset(firstItem)}
                        >
                          查看首个预设
                        </Button>
                      ) : null}
                    </Space>
                  </div>
                  <Progress
                    percent={percent}
                    size="small"
                    status={
                      active
                        ? 'active'
                        : job.status === 'done'
                          ? 'success'
                          : 'exception'
                    }
                  />
                  <div className="preset-asset-task-card-meta">
                    <span>
                      {done}/{total} · {job.current || statusLabel(job.status)}
                    </span>
                    <span>{job.updated_at || job.created_at || '-'}</span>
                  </div>
                  <div
                    aria-label="任务结果汇总"
                    className="preset-asset-task-result-summary"
                  >
                    <span>
                      任务项：完成 {itemSummary.done} / 处理中{' '}
                      {itemSummary.active} / 失败 {itemSummary.failed} / 取消{' '}
                      {itemSummary.cancelled}
                    </span>
                    <span>
                      候选：待验收 {candidateSummary.ready} / 生成中{' '}
                      {candidateSummary.active} / 失败{' '}
                      {candidateSummary.failed} / 已采纳{' '}
                      {candidateSummary.adopted}
                      {candidateSummary.cancelled > 0
                        ? ` / 已取消 ${candidateSummary.cancelled}`
                        : ''}
                    </span>
                  </div>
                  {job.error ? (
                    <div className="preset-asset-task-error">{job.error}</div>
                  ) : null}
                  {jobPollErrors[job.job_id] ? (
                    <div className="preset-asset-task-error">
                      轮询恢复：{jobPollErrors[job.job_id]}
                    </div>
                  ) : null}
                  <Collapse
                    size="small"
                    items={[
                      {
                        key: 'items',
                        label: `逐项结果与候选 (${jobItems(job).length})`,
                        children: (
                          <div className="preset-asset-task-items">
                            {jobItems(job).map((item) => {
                              const label =
                                item.preset_label || item.preset_id;
                              const itemCandidateSummary =
                                summarizeItemCandidates(job, item);
                              const itemActionKey = `${job.job_id}:${item.item_index}`;
                              const retryableItem = itemRetryable(job, item);
                              const failureReason = itemFailureReason(item);
                              const actionLabel =
                                itemCandidateSummary.ready > 0
                                  ? '查看并人工验收'
                                  : itemCandidateSummary.total > 0 ||
                                      item.candidate_id
                                    ? '查看候选'
                                    : '打开预设';
                              return (
                                <div
                                  className="preset-asset-task-item"
                                  key={`${job.job_id}:${item.item_index}`}
                                >
                                  <div className="preset-asset-task-item-heading">
                                    <Space wrap size={6}>
                                      <Tag
                                        color={
                                          STATUS_COLORS[item.status] || 'default'
                                        }
                                      >
                                        {statusLabel(item.status)}
                                      </Tag>
                                      <strong>{label}</strong>
                                      <span className="help">
                                        {item.preset_type}/{item.preset_id}
                                      </span>
                                    </Space>
                                    <Space wrap size={6}>
                                      {retryableItem ? (
                                        <Button
                                          size="small"
                                          icon={
                                            <ReloadOutlined aria-hidden="true" />
                                          }
                                          loading={
                                            workingItemKey === itemActionKey
                                          }
                                          aria-label={`重试此项 ${label}`}
                                          onClick={() =>
                                            void runItemAction(
                                              job.job_id,
                                              item.item_index,
                                              () =>
                                                retryPresetAssetTaskItem(
                                                  job.job_id,
                                                  item.item_index,
                                                ),
                                            )
                                          }
                                        >
                                          重试此项
                                        </Button>
                                      ) : null}
                                      <Button
                                        size="small"
                                        icon={
                                          <EyeOutlined aria-hidden="true" />
                                        }
                                        aria-label={`${actionLabel} ${label}`}
                                        onClick={() => viewPreset(item)}
                                      >
                                        {actionLabel}
                                      </Button>
                                    </Space>
                                  </div>
                                  <div
                                    aria-label={`${label} 结果汇总`}
                                    className="preset-asset-task-item-result"
                                  >
                                    <span>
                                      候选 {itemCandidateSummary.total}
                                    </span>
                                    {itemCandidateSummary.ready > 0 ? (
                                      <Tag color="blue">
                                        待人工验收{' '}
                                        {itemCandidateSummary.ready}
                                      </Tag>
                                    ) : null}
                                    {itemCandidateSummary.active > 0 ? (
                                      <Tag color="processing">
                                        生成中 {itemCandidateSummary.active}
                                      </Tag>
                                    ) : null}
                                    {itemCandidateSummary.failed > 0 ? (
                                      <Tag color="red">
                                        失败 {itemCandidateSummary.failed}
                                      </Tag>
                                    ) : null}
                                    {itemCandidateSummary.adopted > 0 ? (
                                      <Tag color="green">
                                        已采纳 {itemCandidateSummary.adopted}
                                      </Tag>
                                    ) : null}
                                    {itemCandidateSummary.cancelled > 0 ? (
                                      <Tag>
                                        已取消{' '}
                                        {itemCandidateSummary.cancelled}
                                      </Tag>
                                    ) : null}
                                    {item.candidate_summary_reliable === false ? (
                                      <Tooltip title="历史任务的候选归属存在歧义，当前使用预设级回退汇总">
                                        <Tag color="default">历史汇总</Tag>
                                      </Tooltip>
                                    ) : null}
                                    {failureReason ? (
                                      <Tag color={failureReason.color}>
                                        失败原因：{failureReason.label}
                                      </Tag>
                                    ) : null}
                                  </div>
                                  {item.error ? (
                                    <div className="preset-asset-task-error">
                                      {item.error}
                                    </div>
                                  ) : null}
                                  <details>
                                    <summary>保存的生成参数</summary>
                                    <pre>{formatSnapshot(item.params)}</pre>
                                  </details>
                                </div>
                              );
                            })}
                          </div>
                        ),
                      },
                    ]}
                  />
                </div>
                </List.Item>
              );
            }}
          />
        </div>
      </Spin>
    </Drawer>
  );
}
