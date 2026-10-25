import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PresetAssetCatalogQueryResponse,
  PresetAssetDetail,
  PresetAssetJob,
  PresetAssetSettings,
} from '../api';

const apiMocks = vi.hoisted(() => ({
  adoptPresetAssetCandidate: vi.fn(),
  cancelPresetAssetJob: vi.fn(),
  clearPresetAssetCandidates: vi.fn(),
  createPresetAssetAiCandidates: vi.fn(),
  createPresetAssetCropCandidate: vi.fn(),
  createPresetAssetJobs: vi.fn(),
  discardPresetAssetCandidate: vi.fn(),
  fetchPresetAssetCatalogQuery: vi.fn(),
  fetchPresetAssetDetail: vi.fn(),
  fetchPresetAssetJob: vi.fn(),
  fetchPresetAssetJobs: vi.fn(),
  fetchPresetAssetSettings: vi.fn(),
  importPresetAssetSource: vi.fn(),
  retryPresetAssetJob: vi.fn(),
  retryPresetAssetJobItem: vi.fn(),
  rollbackPresetAssetVersion: vi.fn(),
  savePresetAssetSettings: vi.fn(),
}));

vi.mock('resso', () => ({
  default: (state: Record<string, unknown>) => state,
}));

vi.mock('../api', () => apiMocks);

import {
  createPresetAssetAi,
  createPresetAssetBatch,
  loadPresetAssetCatalog,
  loadPresetAssetJobs,
  presetAssetCatalogQueryKey,
  presetAssetStore,
  refreshPresetAssetDetail,
  retryPresetAssetTaskItem,
  setPresetAssetSelection,
} from './presetAssetStore';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function catalogResponse(
  kind: 'pose' | 'clothing',
  presetId: string,
): PresetAssetCatalogQueryResponse {
  return {
    items: [
      {
        kind,
        label: kind,
        order: 1,
        items: [
          {
            preset_type: kind,
            preset_id: presetId,
            label: presetId,
            category: '测试',
            category_group: '测试',
            subcategory: '',
            rating: '普通',
            restricted: false,
            image: null,
            has_image: false,
            active_version: null,
            source: null,
            ready_count: 0,
            running_count: 0,
            failed_count: 0,
            candidate_count: 0,
            updated_at: '2026-09-19T00:00:00Z',
            order: 1,
            kind_label: kind,
          },
        ],
      },
    ],
    total: 1,
    page: 1,
    page_size: 40,
    sort: 'default',
    facets: {
      kinds: [{ value: kind, label: kind, count: 1 }],
      category_groups: [{ value: '测试', label: '测试', count: 1 }],
      subcategories: [],
      task_statuses: [],
    },
  };
}

function job(
  jobId: string,
  status: string,
  overrides: Partial<PresetAssetJob> = {},
): PresetAssetJob {
  return {
    job_id: jobId,
    kind: 'preset_asset',
    status,
    total: 1,
    done: status === 'done' ? 1 : 0,
    current: status,
    error: null,
    stop_requested: false,
    created_at: '2026-09-19T00:00:00Z',
    updated_at: '2026-09-19T00:00:01Z',
    finished_at: status === 'done' ? '2026-09-19T00:00:01Z' : null,
    items: [
      {
        job_id: jobId,
        item_index: 0,
        preset_type: 'pose',
        preset_id: 'pose-a',
        preset_label: '测试体位',
        candidate_id: 1,
        status: status === 'queued' ? 'queued' : 'done',
        params: { mode: 'ai', candidate_count: 1 },
        error: null,
        created_at: '2026-09-19T00:00:00Z',
        updated_at: '2026-09-19T00:00:01Z',
      },
    ],
    candidates: [],
    ...overrides,
  };
}

function detail(presetId: string): PresetAssetDetail {
  return {
    preset: {},
    summary: {
      preset_type: 'pose',
      preset_id: presetId,
      label: presetId,
      category: '测试',
      category_group: '测试',
      subcategory: '',
      rating: '普通',
      restricted: false,
      image: null,
      has_image: false,
      active_version: null,
      source: null,
      ready_count: 0,
      running_count: 0,
      failed_count: 0,
      candidate_count: 0,
    },
    sources: [],
    candidates: [],
    versions: [],
  };
}

const settings: PresetAssetSettings = {
  version: 1,
  style_positive: '',
  style_negative: '',
  user_positive: '',
  user_negative: '',
  seed_strategy: 'random',
  seed: 1,
  candidate_count: 1,
  model: 'mock.safetensors',
  loras: [],
  lora_strengths: {},
  lora_strength_model: 1,
  lora_strength_clip: 1,
  steps: 20,
  cfg: 6,
  crop_mode: 'cover',
  focus_x: 0.5,
  focus_y: 0.5,
  zoom: 1,
};

describe('presetAssetStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    Object.assign(presetAssetStore, {
      catalog: null,
      catalogQueryKey: '',
      settings: null,
      selection: null,
      detail: null,
      jobs: [],
      jobPollErrors: {},
      catalogError: '',
      loadingCatalog: false,
      loadingDetail: false,
      loadingJobs: false,
      submitting: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('keeps the newest catalog response when an older request resolves later', async () => {
    const first = deferred<PresetAssetCatalogQueryResponse>();
    const second = deferred<PresetAssetCatalogQueryResponse>();
    apiMocks.fetchPresetAssetCatalogQuery
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const firstQuery = { kind: 'pose' as const, page: 1 };
    const secondQuery = { kind: 'clothing' as const, page: 1 };

    const firstLoad = loadPresetAssetCatalog(firstQuery);
    const secondLoad = loadPresetAssetCatalog(secondQuery);
    second.resolve(catalogResponse('clothing', 'clothing-a'));
    await secondLoad;
    first.resolve(catalogResponse('pose', 'pose-a'));
    await firstLoad;

    expect(presetAssetStore.catalog?.items[0].kind).toBe('clothing');
    expect(presetAssetStore.catalogQueryKey).toBe(
      presetAssetCatalogQueryKey(secondQuery),
    );
  });

  it('sends directory task status and includes it in the catalog query key', async () => {
    apiMocks.fetchPresetAssetCatalogQuery.mockResolvedValue(
      catalogResponse('pose', 'pose-a'),
    );
    const query = {
      kind: 'pose' as const,
      task_status: 'failed' as const,
      page: 1,
      page_size: 40,
    };

    await loadPresetAssetCatalog(query);

    expect(apiMocks.fetchPresetAssetCatalogQuery).toHaveBeenCalledWith({
      ...query,
      sort: 'default',
    });
    expect(presetAssetStore.catalogQueryKey).toBe(
      presetAssetCatalogQueryKey(query),
    );
  });

  it('does not let an obsolete detail response replace the current selection', async () => {
    const first = deferred<PresetAssetDetail>();
    const second = deferred<PresetAssetDetail>();
    apiMocks.fetchPresetAssetDetail
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    setPresetAssetSelection({ presetType: 'pose', presetId: 'pose-a' });
    const firstLoad = refreshPresetAssetDetail();
    setPresetAssetSelection({ presetType: 'pose', presetId: 'pose-b' });
    const secondLoad = refreshPresetAssetDetail();

    second.resolve(detail('pose-b'));
    await secondLoad;
    first.resolve(detail('pose-a'));
    await firstLoad;

    expect(presetAssetStore.selection?.presetId).toBe('pose-b');
    expect(presetAssetStore.detail?.summary.preset_id).toBe('pose-b');
  });

  it('restores polling for active jobs and refreshes results at terminal state', async () => {
    vi.useFakeTimers();
    const queued = job('job-restore', 'queued');
    const finished = job('job-restore', 'done');
    apiMocks.fetchPresetAssetJobs.mockResolvedValue({ items: [queued] });
    apiMocks.fetchPresetAssetJob
      .mockResolvedValueOnce(queued)
      .mockResolvedValueOnce(finished);
    apiMocks.fetchPresetAssetDetail.mockResolvedValue(detail('pose-a'));
    apiMocks.fetchPresetAssetCatalogQuery.mockResolvedValue(
      catalogResponse('pose', 'pose-a'),
    );
    presetAssetStore.selection = { presetType: 'pose', presetId: 'pose-a' };

    await loadPresetAssetJobs();
    await vi.advanceTimersByTimeAsync(1500);

    expect(apiMocks.fetchPresetAssetJob).toHaveBeenCalledTimes(2);
    expect(presetAssetStore.jobs[0].status).toBe('done');
    expect(apiMocks.fetchPresetAssetDetail).toHaveBeenCalledWith(
      'pose',
      'pose-a',
    );
    expect(apiMocks.fetchPresetAssetCatalogQuery).toHaveBeenCalled();
  });

  it('submits every selected batch item and opens one queued task', async () => {
    const finished = job('job-batch', 'done');
    apiMocks.createPresetAssetJobs.mockResolvedValue(finished);
    apiMocks.fetchPresetAssetJob.mockResolvedValue(finished);
    apiMocks.fetchPresetAssetCatalogQuery.mockResolvedValue(
      catalogResponse('pose', 'pose-a'),
    );

    await createPresetAssetBatch(
      [
        { presetType: 'pose', presetId: 'pose-a' },
        { presetType: 'clothing', presetId: 'clothing-a' },
      ],
      settings,
    );

    expect(apiMocks.createPresetAssetJobs).toHaveBeenCalledWith(
      [
        {
          preset_type: 'pose',
          preset_id: 'pose-a',
          mode: 'ai',
          params: settings,
        },
        {
          preset_type: 'clothing',
          preset_id: 'clothing-a',
          mode: 'ai',
          params: settings,
        },
      ],
      expect.any(String),
    );
    expect(presetAssetStore.jobs[0].job_id).toBe('job-batch');
  });

  it('reuses a failed batch idempotency key and replaces it when the request changes', async () => {
    apiMocks.createPresetAssetJobs
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(job('job-batch-retry', 'done'));

    const firstItems = [
      { presetType: 'pose' as const, presetId: 'batch-key-pose-a' },
    ];
    const changedItems = [
      { presetType: 'pose' as const, presetId: 'batch-key-pose-b' },
    ];

    await expect(
      createPresetAssetBatch(firstItems, settings),
    ).rejects.toThrow('offline');
    const firstKey = apiMocks.createPresetAssetJobs.mock.calls[0][1];

    await expect(
      createPresetAssetBatch(changedItems, settings),
    ).rejects.toThrow('offline');
    const changedKey = apiMocks.createPresetAssetJobs.mock.calls[1][1];
    expect(changedKey).not.toBe(firstKey);

    await createPresetAssetBatch(changedItems, settings);
    expect(apiMocks.createPresetAssetJobs.mock.calls[2][1]).toBe(changedKey);
  });

  it('clears the pending batch key after a successful submission', async () => {
    const finished = job('job-batch-clear', 'done');
    apiMocks.createPresetAssetJobs.mockResolvedValue(finished);
    apiMocks.fetchPresetAssetJob.mockResolvedValue(finished);
    const items = [
      { presetType: 'pose' as const, presetId: 'batch-key-clear' },
    ];

    await createPresetAssetBatch(items, settings);
    const firstKey = apiMocks.createPresetAssetJobs.mock.calls[0][1];
    await createPresetAssetBatch(items, settings);
    const secondKey = apiMocks.createPresetAssetJobs.mock.calls[1][1];

    expect(secondKey).not.toBe(firstKey);
  });

  it('reuses the same single-item idempotency key after failure', async () => {
    const finished = job('job-ai-retry', 'done');
    apiMocks.createPresetAssetAiCandidates
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(finished);
    apiMocks.fetchPresetAssetJob.mockResolvedValue(finished);
    presetAssetStore.selection = {
      presetType: 'pose',
      presetId: 'ai-key-pose',
    };

    await expect(createPresetAssetAi(settings)).rejects.toThrow('offline');
    const firstKey =
      apiMocks.createPresetAssetAiCandidates.mock.calls[0][3];
    await createPresetAssetAi(settings);
    const retryKey =
      apiMocks.createPresetAssetAiCandidates.mock.calls[1][3];

    expect(firstKey).toEqual(expect.any(String));
    expect(retryKey).toBe(firstKey);
  });

  it('uses a new single-item idempotency key after settings change', async () => {
    apiMocks.createPresetAssetAiCandidates
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'));
    presetAssetStore.selection = {
      presetType: 'pose',
      presetId: 'ai-key-settings',
    };

    await expect(createPresetAssetAi(settings)).rejects.toThrow('offline');
    const firstKey =
      apiMocks.createPresetAssetAiCandidates.mock.calls[0][3];
    await expect(
      createPresetAssetAi({ ...settings, steps: settings.steps + 1 }),
    ).rejects.toThrow('offline');
    const changedKey =
      apiMocks.createPresetAssetAiCandidates.mock.calls[1][3];

    expect(changedKey).not.toBe(firstKey);
  });

  it('retries one task item and resumes polling for its job', async () => {
    vi.useFakeTimers();
    const queued = job('job-retry-item', 'queued');
    const finished = job('job-retry-item', 'done');
    apiMocks.retryPresetAssetJobItem.mockResolvedValue(queued);
    apiMocks.fetchPresetAssetJob
      .mockResolvedValueOnce(queued)
      .mockResolvedValueOnce(finished);

    await retryPresetAssetTaskItem('job-retry-item', 2);

    expect(apiMocks.retryPresetAssetJobItem).toHaveBeenCalledWith(
      'job-retry-item',
      2,
    );
    expect(presetAssetStore.jobs[0].status).toBe('queued');

    await vi.advanceTimersByTimeAsync(1500);

    expect(apiMocks.fetchPresetAssetJob).toHaveBeenCalledWith(
      'job-retry-item',
    );
    expect(presetAssetStore.jobs[0].status).toBe('done');
  });
});
