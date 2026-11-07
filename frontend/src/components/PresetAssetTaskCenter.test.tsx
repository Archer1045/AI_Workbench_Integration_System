import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PresetAssetCandidate, PresetAssetJob } from '../api';
import type { PresetAssetTaskFilter } from '../presetAssetPageState';
import type { PresetAssetTaskStatusFilter } from '../presetAssetPageState';

const storeState = vi.hoisted(() => ({
  jobs: [] as PresetAssetJob[],
  jobPollErrors: {} as Record<string, string>,
  loadingJobs: false,
}));

const actionMocks = vi.hoisted(() => ({
  cancel: vi.fn(),
  retry: vi.fn(),
  retryItem: vi.fn(),
  load: vi.fn(),
}));

vi.mock('../stores/presetAssetStore', () => ({
  apiErrorMessage: (_error: unknown, fallback: string) => fallback,
  cancelPresetAssetTask: actionMocks.cancel,
  loadPresetAssetJobs: actionMocks.load,
  presetAssetStore: storeState,
  retryPresetAssetTask: actionMocks.retry,
  retryPresetAssetTaskItem: actionMocks.retryItem,
}));

import PresetAssetTaskCenter from './PresetAssetTaskCenter';

function TaskCenterHarness() {
  const [filter, setFilter] = useState<PresetAssetTaskFilter>('active');
  const [statusFilter, setStatusFilter] =
    useState<PresetAssetTaskStatusFilter>('');
  return (
    <PresetAssetTaskCenter
      open
      onClose={vi.fn()}
      onViewPreset={vi.fn()}
      filter={filter}
      onFilterChange={setFilter}
      statusFilter={statusFilter}
      onStatusFilterChange={setStatusFilter}
      scrollTop={0}
      onScrollTopChange={vi.fn()}
    />
  );
}

function job(
  jobId: string,
  status: string,
  itemStatus: string,
  presetLabel?: string,
): PresetAssetJob {
  return {
    job_id: jobId,
    kind: 'preset_asset',
    status,
    total: 1,
    done: status === 'done' ? 1 : 0,
    current: status,
    error: status === 'error' ? '测试失败原因' : null,
    stop_requested: false,
    created_at: '2026-09-19T00:00:00Z',
    updated_at: '2026-09-19T00:00:01Z',
    finished_at: null,
    items: [
      {
        job_id: jobId,
        item_index: 0,
        preset_type: 'pose',
        preset_id: `${jobId}-preset`,
        preset_label: presetLabel,
        candidate_id: 1,
        status: itemStatus,
        params: { mode: 'ai', candidate_count: 1 },
        error: itemStatus === 'failed' ? '测试失败原因' : null,
        created_at: '2026-09-19T00:00:00Z',
        updated_at: '2026-09-19T00:00:01Z',
      },
    ],
    candidates: [],
  };
}

function candidate(
  jobId: string,
  presetId: string,
  candidateId: number,
  status: string,
): PresetAssetCandidate {
  return {
    id: candidateId,
    job_id: jobId,
    preset_type: 'pose',
    preset_id: presetId,
    generation_mode: 'ai',
    status,
    created_at: '2026-09-19T00:00:00Z',
    updated_at: '2026-09-19T00:00:01Z',
  };
}

describe('PresetAssetTaskCenter', () => {
  beforeEach(() => {
    actionMocks.cancel.mockReset().mockResolvedValue(undefined);
    actionMocks.retry.mockReset().mockResolvedValue(undefined);
    actionMocks.retryItem.mockReset().mockResolvedValue(undefined);
    actionMocks.load.mockReset().mockResolvedValue(undefined);
    storeState.jobs = [
      job('job-running', 'running', 'failed'),
      job('job-failed', 'error', 'failed', '恢复测试体位'),
      job('job-done', 'done', 'done'),
    ];
    storeState.jobPollErrors = {};
    storeState.loadingJobs = false;
  });

  it('shows persisted task categories and routes recovery to the exact job', async () => {
    const activeView = render(
      <PresetAssetTaskCenter
        open
        onClose={vi.fn()}
        onViewPreset={vi.fn()}
        filter="active"
        onFilterChange={vi.fn()}
        statusFilter=""
        onStatusFilterChange={vi.fn()}
        scrollTop={0}
        onScrollTopChange={vi.fn()}
      />,
    );

    expect(screen.getByText('1 个预设 / 1 张候选')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /取消/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /重试失败项/ }),
    ).not.toBeInTheDocument();
    activeView.unmount();

    const onViewPreset = vi.fn();
    render(
      <PresetAssetTaskCenter
        open
        onClose={vi.fn()}
        onViewPreset={onViewPreset}
        filter="recoverable"
        onFilterChange={vi.fn()}
        statusFilter=""
        onStatusFilterChange={vi.fn()}
        scrollTop={0}
        onScrollTopChange={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: /查看首个预设/ }),
    );
    expect(onViewPreset).toHaveBeenCalledWith({
      presetType: 'pose',
      presetId: 'job-failed-preset',
      label: '恢复测试体位',
    });
  });

  it('switches to recoverable jobs through the segmented control and retries them', async () => {
    render(<TaskCenterHarness />);

    fireEvent.click(screen.getByText('可恢复 1'));

    const retryButton = await screen.findByRole('button', {
      name: /重试失败项/,
    });
    fireEvent.click(retryButton);
    await waitFor(() =>
      expect(actionMocks.retry).toHaveBeenCalledWith('job-failed'),
    );
  });

  it('filters jobs by exact task status', () => {
    const onViewPreset = vi.fn();
    render(
      <PresetAssetTaskCenter
        open
        onClose={vi.fn()}
        onViewPreset={onViewPreset}
        filter="all"
        onFilterChange={vi.fn()}
        statusFilter="error"
        onStatusFilterChange={vi.fn()}
        scrollTop={0}
        onScrollTopChange={vi.fn()}
      />,
    );

    expect(
      screen.getAllByRole('button', { name: /查看首个预设/ }),
    ).toHaveLength(1);
    fireEvent.click(
      screen.getByRole('button', { name: /查看首个预设/ }),
    );
    expect(onViewPreset).toHaveBeenCalledWith({
      presetType: 'pose',
      presetId: 'job-failed-preset',
      label: '恢复测试体位',
    });
  });

  it('opens the exact preset for every item in a batch', () => {
    const onViewPreset = vi.fn();
    const batch = job('job-batch', 'done', 'done', '第一项');
    batch.total = 2;
    batch.done = 2;
    batch.items = [
      batch.items[0],
      {
        ...batch.items[0],
        item_index: 1,
        preset_id: 'batch-second-preset',
        preset_label: '第二项',
        candidate_id: 2,
      },
    ];
    batch.candidates = [
      candidate('job-batch', 'job-batch-preset', 1, 'ready'),
      candidate('job-batch', 'batch-second-preset', 2, 'ready'),
    ];
    storeState.jobs = [batch];

    render(
      <PresetAssetTaskCenter
        open
        onClose={vi.fn()}
        onViewPreset={onViewPreset}
        filter="all"
        onFilterChange={vi.fn()}
        statusFilter=""
        onStatusFilterChange={vi.fn()}
        scrollTop={0}
        onScrollTopChange={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /逐项结果与候选 \(2\)/ }),
    );

    expect(screen.getByLabelText('任务结果汇总')).toHaveTextContent(
      '任务项：完成 2 / 处理中 0 / 失败 0 / 取消 0',
    );
    expect(screen.getByLabelText('任务结果汇总')).toHaveTextContent(
      '候选：待验收 2 / 生成中 0 / 失败 0 / 已采纳 0',
    );
    expect(screen.getByLabelText('第一项 结果汇总')).toHaveTextContent(
      '候选 1',
    );
    expect(screen.getByLabelText('第一项 结果汇总')).toHaveTextContent(
      '待人工验收 1',
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: '查看并人工验收 第一项',
      }),
    );
    expect(onViewPreset).toHaveBeenLastCalledWith({
      presetType: 'pose',
      presetId: 'job-batch-preset',
      label: '第一项',
    });

    fireEvent.click(
      screen.getByRole('button', {
        name: '查看并人工验收 第二项',
      }),
    );
    expect(onViewPreset).toHaveBeenLastCalledWith({
      presetType: 'pose',
      presetId: 'batch-second-preset',
      label: '第二项',
    });
  });

  it('uses backend summaries for duplicate preset items before candidate matching', () => {
    const batch = job('job-duplicate-preset', 'done', 'done', '重复项一');
    batch.total = 3;
    batch.done = 3;
    batch.items = [
      {
        ...batch.items[0],
        preset_id: 'duplicate-preset',
        preset_label: '重复项一',
        candidate_count: 1,
        ready_count: 1,
        adopted_count: 0,
        active_count: 0,
        failed_count: 0,
        cancelled_count: 0,
        candidate_summary_reliable: true,
        candidate_summary_source: 'job_item',
      },
      {
        ...batch.items[0],
        item_index: 1,
        preset_id: 'duplicate-preset',
        preset_label: '重复项二',
        candidate_id: 3,
        candidate_count: 2,
        ready_count: 0,
        adopted_count: 0,
        active_count: 0,
        failed_count: 2,
        cancelled_count: 0,
        candidate_summary_reliable: true,
        candidate_summary_source: 'job_item',
      },
    ];
    batch.candidates = [
      candidate('job-duplicate-preset', 'duplicate-preset', 1, 'ready'),
      candidate('job-duplicate-preset', 'duplicate-preset', 2, 'failed'),
      candidate('job-duplicate-preset', 'duplicate-preset', 3, 'failed'),
    ];
    storeState.jobs = [batch];

    render(
      <PresetAssetTaskCenter
        open
        onClose={vi.fn()}
        onViewPreset={vi.fn()}
        filter="all"
        onFilterChange={vi.fn()}
        statusFilter=""
        onStatusFilterChange={vi.fn()}
        scrollTop={0}
        onScrollTopChange={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /逐项结果与候选 \(2\)/ }),
    );

    const firstSummary = screen.getByLabelText('重复项一 结果汇总');
    expect(firstSummary).toHaveTextContent('候选 1');
    expect(firstSummary).toHaveTextContent('待人工验收 1');
    expect(firstSummary).not.toHaveTextContent('候选 3');

    const secondSummary = screen.getByLabelText('重复项二 结果汇总');
    expect(secondSummary).toHaveTextContent('候选 2');
    expect(secondSummary).toHaveTextContent('失败 2');
    expect(secondSummary).not.toHaveTextContent('候选 3');
  });

  it('classifies failed items, retries one item, and opens its own preset', async () => {
    const onViewPreset = vi.fn();
    const batch = job('job-failed-batch', 'error', 'failed', '服务错误项');
    batch.total = 2;
    batch.items = [
      {
        ...batch.items[0],
        error: '参数错误',
        last_error_code: 'generation_service_unavailable',
        retryable: true,
        user_action: 'start_service',
      },
      {
        ...batch.items[0],
        item_index: 1,
        preset_id: 'timeout-preset',
        preset_label: '参数错误项',
        candidate_id: null,
        error: 'ComfyUI connection refused',
        last_error_code: 'invalid_parameters',
        retryable: false,
        user_action: 'fix_parameters',
      },
    ];
    storeState.jobs = [batch];

    render(
      <PresetAssetTaskCenter
        open
        onClose={vi.fn()}
        onViewPreset={onViewPreset}
        filter="all"
        onFilterChange={vi.fn()}
        statusFilter=""
        onStatusFilterChange={vi.fn()}
        scrollTop={0}
        onScrollTopChange={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /逐项结果与候选 \(2\)/ }),
    );

    expect(screen.getByText('失败原因：生成服务不可用')).toBeInTheDocument();
    expect(screen.getByText('失败原因：参数问题')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '重试此项 参数错误项' }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: '重试此项 服务错误项' }),
    );
    await waitFor(() =>
      expect(actionMocks.retryItem).toHaveBeenCalledWith(
        'job-failed-batch',
        0,
      ),
    );

    fireEvent.click(
      screen.getByRole('button', { name: '打开预设 参数错误项' }),
    );
    expect(onViewPreset).toHaveBeenCalledWith({
      presetType: 'pose',
      presetId: 'timeout-preset',
      label: '参数错误项',
    });
  });

  it('hides job retry when every failed item needs correction first', () => {
    const batch = job('job-needs-fix', 'error', 'failed');
    batch.items[0] = {
      ...batch.items[0],
      error: 'ComfyUI connection refused',
      last_error_code: 'invalid_parameters',
      retryable: false,
      user_action: 'fix_parameters',
    };
    storeState.jobs = [batch];

    render(
      <PresetAssetTaskCenter
        open
        onClose={vi.fn()}
        onViewPreset={vi.fn()}
        filter="all"
        onFilterChange={vi.fn()}
        statusFilter=""
        onStatusFilterChange={vi.fn()}
        scrollTop={0}
        onScrollTopChange={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole('button', { name: /重试失败项/ }),
    ).not.toBeInTheDocument();
  });
});
