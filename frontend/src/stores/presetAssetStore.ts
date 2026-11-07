// 预设缩略图工坊状态与后台任务轮询
import useStore from 'resso';
import {
  adoptPresetAssetCandidate,
  cancelPresetAssetJob,
  clearPresetAssetCandidates as clearPresetAssetCandidatesRequest,
  createPresetAssetAiCandidates,
  createPresetAssetCropCandidate,
  createPresetAssetJobs,
  discardPresetAssetCandidate,
  fetchPresetAssetCatalogQuery,
  fetchPresetAssetDetail,
  fetchPresetAssetJob,
  fetchPresetAssetJobs,
  fetchPresetAssetSettings,
  importPresetAssetSource,
  retryPresetAssetJob,
  retryPresetAssetJobItem,
  rollbackPresetAssetVersion,
  savePresetAssetSettings,
  type PresetAssetCandidate,
  type PresetAssetCatalogQuery,
  type PresetAssetCatalogQueryResponse,
  type PresetAssetCropInput,
  type PresetAssetDetail,
  type PresetAssetJob,
  type PresetAssetKind,
  type PresetAssetSettings,
  type PresetAssetSettingsPayload,
} from '../api';

export interface PresetAssetSelection {
  presetType: PresetAssetKind;
  presetId: string;
  label?: string;
}

interface PresetAssetState {
  catalog: PresetAssetCatalogQueryResponse | null;
  catalogQueryKey: string;
  settings: PresetAssetSettingsPayload | null;
  selection: PresetAssetSelection | null;
  detail: PresetAssetDetail | null;
  jobs: PresetAssetJob[];
  jobPollErrors: Record<string, string>;
  catalogError: string;
  loadingCatalog: boolean;
  loadingDetail: boolean;
  loadingJobs: boolean;
  submitting: boolean;
  [key: string]: unknown;
}

export interface PresetAssetQueueItem {
  presetType: PresetAssetKind;
  presetId: string;
  params?: Partial<PresetAssetSettings>;
}

const TERMINAL_JOB_STATUSES = new Set([
  'done',
  'error',
  'cancelled',
  'stopped',
  'interrupted',
]);

export const presetAssetStore = useStore<PresetAssetState>({
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

const JOB_LIST_LIMIT = 100;
const JOB_POLL_INTERVAL_MS = 1500;
const pollTokens = new Map<string, number>();
let nextPollToken = 0;
let catalogRequestToken = 0;
let detailRequestToken = 0;
const pendingSubmissionKeys = new Map<
  string,
  { fingerprint: string; key: string }
>();
let lastCatalogQuery: PresetAssetCatalogQuery = {
  kind: 'pose',
  page: 1,
  page_size: 40,
  sort: 'default',
};

export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: string } } }).response?.data
    ?.detail;
  return detail || (error instanceof Error ? error.message : fallback);
}

export function presetAssetCatalogQueryKey(
  query: PresetAssetCatalogQuery,
): string {
  return JSON.stringify({
    kind: query.kind,
    keyword: query.keyword || '',
    resource: query.resource || 'all',
    rating: query.rating || '',
    category_group: query.category_group || '',
    subcategory: query.subcategory || '',
    candidate_status: query.candidate_status || '',
    task_status: query.task_status || '',
    page: query.page || 1,
    page_size: query.page_size || 40,
    sort: query.sort || 'default',
  });
}

function stableSubmissionValue(value: unknown): string {
  if (value === undefined) return 'undefined';
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value) ?? 'null';
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableSubmissionValue).join(',')}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .filter((key) => record[key] !== undefined)
    .map(
      (key) =>
        `${JSON.stringify(key)}:${stableSubmissionValue(record[key])}`,
    )
    .join(',')}}`;
}

function createIdempotencyKey(): string {
  const randomUuid = globalThis.crypto?.randomUUID;
  if (randomUuid) return randomUuid.call(globalThis.crypto);
  return `preset-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function getSubmissionIdempotencyKey(
  scope: string,
  payload: unknown,
): string {
  const fingerprint = stableSubmissionValue(payload);
  const pending = pendingSubmissionKeys.get(scope);
  if (pending?.fingerprint === fingerprint) return pending.key;
  const key = createIdempotencyKey();
  pendingSubmissionKeys.set(scope, { fingerprint, key });
  return key;
}

function clearSubmissionIdempotencyKey(scope: string, key: string): void {
  if (pendingSubmissionKeys.get(scope)?.key === key) {
    pendingSubmissionKeys.delete(scope);
  }
}

export async function loadPresetAssetCatalog(
  query?: PresetAssetCatalogQuery,
): Promise<void> {
  if (query) {
    lastCatalogQuery = {
      page: 1,
      page_size: 40,
      sort: 'default',
      ...query,
    };
  }
  const requestQuery = { ...lastCatalogQuery };
  const requestQueryKey = presetAssetCatalogQueryKey(requestQuery);
  const token = ++catalogRequestToken;
  presetAssetStore.loadingCatalog = true;
  presetAssetStore.catalogError = '';
  try {
    const catalog = await fetchPresetAssetCatalogQuery(requestQuery);
    if (token === catalogRequestToken) {
      presetAssetStore.catalog = catalog;
      presetAssetStore.catalogQueryKey = requestQueryKey;
      lastCatalogQuery = {
        ...lastCatalogQuery,
        kind: catalog.items[0]?.kind || lastCatalogQuery.kind,
        page: catalog.page,
        page_size: catalog.page_size,
        sort: catalog.sort,
      };
    }
  } catch (error) {
    if (token === catalogRequestToken) {
      presetAssetStore.catalogError = apiErrorMessage(
        error,
        '预设目录加载失败',
      );
    }
    throw error;
  } finally {
    if (token === catalogRequestToken) {
      presetAssetStore.loadingCatalog = false;
    }
  }
}

export async function loadPresetAssetSettings(): Promise<void> {
  if (presetAssetStore.settings) return;
  presetAssetStore.settings = await fetchPresetAssetSettings();
}

export async function savePresetAssetDefaults(
  defaults: PresetAssetSettings,
): Promise<void> {
  presetAssetStore.settings = await savePresetAssetSettings(defaults);
}

export async function refreshPresetAssetDetail(): Promise<void> {
  const selection = presetAssetStore.selection;
  if (!selection) {
    setPresetAssetSelection(null);
    return;
  }
  const token = ++detailRequestToken;
  const selectionKey = `${selection.presetType}:${selection.presetId}`;
  presetAssetStore.loadingDetail = true;
  try {
    const detail = await fetchPresetAssetDetail(
      selection.presetType,
      selection.presetId,
    );
    const currentSelection = presetAssetStore.selection;
    const currentSelectionKey = currentSelection
      ? `${currentSelection.presetType}:${currentSelection.presetId}`
      : '';
    if (
      token === detailRequestToken &&
      currentSelectionKey === selectionKey
    ) {
      presetAssetStore.detail = detail;
    }
  } finally {
    if (token === detailRequestToken) {
      presetAssetStore.loadingDetail = false;
    }
  }
}

export async function selectPresetAsset(
  selection: PresetAssetSelection | null,
): Promise<void> {
  setPresetAssetSelection(selection);
  if (selection) await refreshPresetAssetDetail();
}

export function setPresetAssetSelection(
  selection: PresetAssetSelection | null,
): void {
  detailRequestToken += 1;
  presetAssetStore.selection = selection;
  presetAssetStore.detail = null;
  presetAssetStore.loadingDetail = false;
}

export async function importPresetAsset(
  dataUrl: string,
  mimeType?: string,
): Promise<void> {
  const selection = presetAssetStore.selection;
  if (!selection) throw new Error('请先选择预设');
  presetAssetStore.submitting = true;
  try {
    await importPresetAssetSource(
      selection.presetType,
      selection.presetId,
      dataUrl,
      mimeType,
    );
    await refreshPresetAssetDetail();
    await loadPresetAssetCatalog();
  } finally {
    presetAssetStore.submitting = false;
  }
}

export async function createPresetAssetCrop(
  crop: PresetAssetCropInput,
): Promise<PresetAssetCandidate> {
  const selection = presetAssetStore.selection;
  if (!selection) throw new Error('请先选择预设');
  presetAssetStore.submitting = true;
  try {
    const candidate = await createPresetAssetCropCandidate(
      selection.presetType,
      selection.presetId,
      {
        source_id: presetAssetStore.detail?.summary.source?.id ?? null,
        crop,
      },
    );
    await refreshPresetAssetDetail();
    return candidate;
  } finally {
    presetAssetStore.submitting = false;
  }
}

export async function createPresetAssetAi(
  settings: PresetAssetSettings,
): Promise<PresetAssetJob> {
  const selection = presetAssetStore.selection;
  if (!selection) throw new Error('请先选择预设');
  presetAssetStore.submitting = true;
  const submissionScope = `ai:${selection.presetType}:${selection.presetId}`;
  const submissionKey = getSubmissionIdempotencyKey(submissionScope, settings);
  try {
    const job = await createPresetAssetAiCandidates(
      selection.presetType,
      selection.presetId,
      settings,
      submissionKey,
    );
    clearSubmissionIdempotencyKey(submissionScope, submissionKey);
    upsertPresetAssetJob(job);
    startPresetAssetJobPolling(job.job_id);
    return job;
  } finally {
    presetAssetStore.submitting = false;
  }
}

function upsertPresetAssetJob(job: PresetAssetJob): void {
  const index = presetAssetStore.jobs.findIndex(
    (item) => item.job_id === job.job_id,
  );
  if (index < 0) {
    presetAssetStore.jobs = [job, ...presetAssetStore.jobs];
    return;
  }
  const jobs = [...presetAssetStore.jobs];
  jobs[index] = job;
  presetAssetStore.jobs = jobs;
}

function setJobPollError(jobId: string, error: string): void {
  presetAssetStore.jobPollErrors = {
    ...presetAssetStore.jobPollErrors,
    [jobId]: error,
  };
}

function clearJobPollError(jobId: string): void {
  if (!presetAssetStore.jobPollErrors[jobId]) return;
  const next = { ...presetAssetStore.jobPollErrors };
  delete next[jobId];
  presetAssetStore.jobPollErrors = next;
}

async function refreshTerminalJobResults(job: PresetAssetJob): Promise<void> {
  const selection = presetAssetStore.selection;
  if (
    selection &&
    job.items.some(
      (item) =>
        item.preset_type === selection.presetType &&
        item.preset_id === selection.presetId,
    )
  ) {
    await refreshPresetAssetDetail();
  }
  await loadPresetAssetCatalog();
}

async function runPresetAssetJobPolling(jobId: string, token: number) {
  while (pollTokens.get(jobId) === token) {
    try {
      const job = await fetchPresetAssetJob(jobId);
      if (pollTokens.get(jobId) !== token) return;
      clearJobPollError(jobId);
      upsertPresetAssetJob(job);
      if (TERMINAL_JOB_STATUSES.has(job.status)) {
        pollTokens.delete(jobId);
        try {
          await refreshTerminalJobResults(job);
        } catch (error) {
          setJobPollError(
            jobId,
            apiErrorMessage(error, '任务结果刷新失败，可手动刷新'),
          );
        }
        return;
      }
    } catch (error) {
      if (pollTokens.get(jobId) !== token) return;
      setJobPollError(
        jobId,
        apiErrorMessage(error, '任务状态轮询失败，正在继续重试'),
      );
      await new Promise((resolve) =>
        globalThis.setTimeout(resolve, JOB_POLL_INTERVAL_MS * 2),
      );
      continue;
    }
    await new Promise((resolve) =>
      globalThis.setTimeout(resolve, JOB_POLL_INTERVAL_MS),
    );
  }
}

export function startPresetAssetJobPolling(jobId: string): void {
  if (!jobId || pollTokens.has(jobId)) return;
  const token = ++nextPollToken;
  pollTokens.set(jobId, token);
  void runPresetAssetJobPolling(jobId, token);
}

export async function loadPresetAssetJobs(): Promise<void> {
  presetAssetStore.loadingJobs = true;
  try {
    const response = await fetchPresetAssetJobs({ limit: JOB_LIST_LIMIT });
    presetAssetStore.jobs = response.items;
    for (const job of response.items) {
      if (!TERMINAL_JOB_STATUSES.has(job.status)) {
        startPresetAssetJobPolling(job.job_id);
      }
    }
  } finally {
    presetAssetStore.loadingJobs = false;
  }
}

export async function createPresetAssetBatch(
  items: PresetAssetQueueItem[],
  settings: PresetAssetSettings,
): Promise<PresetAssetJob> {
  if (items.length === 0) throw new Error('请先选择需要补图的预设');
  presetAssetStore.submitting = true;
  const requestItems = items.map((item) => ({
    preset_type: item.presetType,
    preset_id: item.presetId,
    mode: 'ai' as const,
    params: item.params || settings,
  }));
  const submissionScope = 'batch';
  const submissionKey = getSubmissionIdempotencyKey(submissionScope, {
    items: requestItems,
  });
  try {
    const job = await createPresetAssetJobs(
      requestItems,
      submissionKey,
    );
    clearSubmissionIdempotencyKey(submissionScope, submissionKey);
    upsertPresetAssetJob(job);
    startPresetAssetJobPolling(job.job_id);
    return job;
  } finally {
    presetAssetStore.submitting = false;
  }
}

export async function cancelPresetAssetTask(jobId?: string): Promise<void> {
  const resolvedJobId =
    jobId ||
    presetAssetStore.jobs.find(
      (job) => !TERMINAL_JOB_STATUSES.has(job.status),
    )?.job_id;
  if (!resolvedJobId) return;
  upsertPresetAssetJob(await cancelPresetAssetJob(resolvedJobId));
}

export async function retryPresetAssetTask(jobId?: string): Promise<void> {
  const resolvedJobId =
    jobId ||
    presetAssetStore.jobs.find(
      (job) => !TERMINAL_JOB_STATUSES.has(job.status),
    )?.job_id;
  if (!resolvedJobId) return;
  const job = await retryPresetAssetJob(resolvedJobId);
  upsertPresetAssetJob(job);
  startPresetAssetJobPolling(job.job_id);
}

export async function retryPresetAssetTaskItem(
  jobId: string,
  itemIndex: number,
): Promise<void> {
  const job = await retryPresetAssetJobItem(jobId, itemIndex);
  upsertPresetAssetJob(job);
  startPresetAssetJobPolling(job.job_id);
}

export async function adoptPresetAsset(candidateId: number): Promise<void> {
  const selection = presetAssetStore.selection;
  if (!selection) throw new Error('请先选择预设');
  const expectedRevision = presetAssetStore.detail?.summary.active_version?.id ?? null;
  await adoptPresetAssetCandidate(candidateId, expectedRevision);
  await refreshPresetAssetDetail();
  await loadPresetAssetCatalog();
}

export async function discardPresetAsset(candidateId: number): Promise<void> {
  await discardPresetAssetCandidate(candidateId);
  await refreshPresetAssetDetail();
}

export async function clearPresetAssetCandidates(): Promise<number> {
  const selection = presetAssetStore.selection;
  if (!selection) throw new Error('请先选择预设');
  const result = await clearPresetAssetCandidatesRequest(
    selection.presetType,
    selection.presetId,
  );
  await refreshPresetAssetDetail();
  await loadPresetAssetCatalog();
  return result.cleared_count;
}

export async function rollbackPresetAsset(version: number): Promise<void> {
  const selection = presetAssetStore.selection;
  if (!selection) throw new Error('请先选择预设');
  const expectedRevision = presetAssetStore.detail?.summary.active_version?.id ?? null;
  await rollbackPresetAssetVersion(
    selection.presetType,
    selection.presetId,
    version,
    expectedRevision,
  );
  await refreshPresetAssetDetail();
  await loadPresetAssetCatalog();
}
