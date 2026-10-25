import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PresetAssetDetail,
  PresetAssetCatalogQueryResponse,
  PresetAssetSettingsPayload,
} from '../api';
import {
  PRESET_ASSET_PAGE_STATE_STORAGE_KEY,
} from '../presetAssetPageState';
import { savePresetAssetSettingsDraft } from '../presetAssetSettingsPersistence';
import type { PresetAssetSelection } from '../stores/presetAssetStore';

const mocks = vi.hoisted(() => ({
  createPresetAssetBatch: vi.fn(),
  loadPresetAssetCatalog: vi.fn(),
  loadPresetAssetJobs: vi.fn(),
  loadPresetAssetSettings: vi.fn(),
  selectPresetAsset: vi.fn(),
  store: {
    catalog: null as PresetAssetCatalogQueryResponse | null,
    catalogQueryKey: 'catalog-key',
    detail: null as PresetAssetDetail | null,
    jobs: [],
    settings: null as PresetAssetSettingsPayload | null,
    loadingCatalog: false,
    loadingDetail: false,
    loadingJobs: false,
    selection: null as PresetAssetSelection | null,
    submitting: false,
  },
}));

vi.mock('../stores/presetAssetStore', () => ({
  apiErrorMessage: (_error: unknown, fallback: string) => fallback,
  createPresetAssetBatch: mocks.createPresetAssetBatch,
  loadPresetAssetCatalog: mocks.loadPresetAssetCatalog,
  loadPresetAssetJobs: mocks.loadPresetAssetJobs,
  loadPresetAssetSettings: mocks.loadPresetAssetSettings,
  presetAssetCatalogQueryKey: (query: Record<string, any>) =>
    JSON.stringify({
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
    }),
  presetAssetStore: mocks.store,
  refreshPresetAssetDetail: vi.fn(),
  selectPresetAsset: mocks.selectPresetAsset,
  setPresetAssetSelection: vi.fn(),
}));

vi.mock('./PresetAssetCompare', () => ({
  default: () => <div />,
}));
vi.mock('./PresetAssetFilterBar', () => ({
  default: () => <div />,
}));
vi.mock('./PresetAssetHistory', () => ({
  default: () => <div />,
}));
vi.mock('./PresetAssetList', () => ({
  default: ({
    items,
    page,
    onSelect,
    onPageChange,
    onToggle,
    selectable,
  }: {
    items: Array<{ preset_id: string }>;
    page?: number;
    onSelect?: (selection: PresetAssetSelection) => void;
    onPageChange?: (page: number) => void;
    onToggle?: (item: unknown, checked: boolean) => void;
    selectable?: boolean;
  }) => (
    <div>
      <span>{selectable ? 'batch-list' : 'single-list'}</span>
      <span data-testid="list-page">{page}</span>
      <button
        type="button"
        onClick={() =>
          onSelect?.({
            presetType: 'pose',
            presetId: items[0]?.preset_id || '',
            label: '测试体位',
          })
        }
      >
        select {items[0]?.preset_id}
      </button>
      <button type="button" onClick={() => onPageChange?.(2)}>
        page 2
      </button>
      <button
        type="button"
        onClick={() => onToggle?.(items[0], true)}
      >
        toggle {items[0]?.preset_id}
      </button>
    </div>
  ),
}));
vi.mock('./PresetAssetParamsPanel', () => ({
  default: ({ batchMode }: { batchMode?: boolean }) => (
    <div>{batchMode ? '批量生成参数' : '单项生成参数'}</div>
  ),
}));
vi.mock('./PresetAssetTaskCenter', () => ({
  default: ({
    onViewPreset,
  }: {
    onViewPreset?: (selection: PresetAssetSelection) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onViewPreset?.({
          presetType: 'pose',
          presetId: 'pose-a',
          label: '测试体位',
        })
      }
    >
      task-view-preset
    </button>
  ),
}));

import PresetAssetWorkshopPanel from './PresetAssetWorkshopPanel';

const settingsPayload: PresetAssetSettingsPayload = {
  defaults: {
    version: 1,
    model: 'model.safetensors',
    loras: [],
    lora_strengths: {},
    lora_strength_model: 1,
    lora_strength_clip: 1,
    steps: 28,
    cfg: 7,
    seed_strategy: 'random',
    seed: null,
    crop_mode: 'cover',
    focus_x: 0.5,
    focus_y: 0.5,
    zoom: 1,
    candidate_count: 2,
    style_positive: '',
    style_negative: '',
    user_positive: '',
    user_negative: '',
  },
  targets: {
    pose: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'WEBP',
      quality: 90,
    },
    clothing: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'WEBP',
      quality: 90,
    },
    scene: {
      generation_size: [960, 540],
      output_size: [480, 270],
      format: 'WEBP',
      quality: 90,
    },
    body: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'WEBP',
      quality: 90,
    },
    expansion: {
      generation_size: [768, 768],
      output_size: [384, 384],
      format: 'WEBP',
      quality: 90,
    },
    toy: {
      generation_size: [768, 768],
      output_size: [384, 384],
      format: 'WEBP',
      quality: 90,
    },
    character: {
      generation_size: [540, 960],
      output_size: [270, 480],
      format: 'WEBP',
      quality: 90,
    },
  },
  limits: {
    candidate_min: 1,
    candidate_max: 4,
    batch_max_items: 20,
    upload_max_bytes: 20 * 1024 * 1024,
    upload_max_pixels: 40_000_000,
    width_min: 64,
    width_max: 2048,
    height_min: 64,
    height_max: 2048,
    steps_min: 1,
    steps_max: 80,
    cfg_min: 0.5,
    cfg_max: 20,
    cfg_step: 0.5,
    seed_min: 0,
    seed_max: 4_294_967_295,
    focus_min: 0,
    focus_max: 1,
    focus_step: 0.01,
    zoom_min: 0.05,
    zoom_max: 3,
    zoom_step: 0.05,
    lora_strength_min: 0,
    lora_strength_max: 2,
    lora_strength_step: 0.05,
  },
  template_version: '1',
};

describe('PresetAssetWorkshopPanel', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    mocks.createPresetAssetBatch.mockResolvedValue({
      job_id: 'job-batch',
    });
    mocks.loadPresetAssetCatalog.mockResolvedValue(undefined);
    mocks.selectPresetAsset.mockResolvedValue(undefined);
    mocks.store.detail = null;
    mocks.store.loadingDetail = false;
    mocks.store.selection = null;
    mocks.store.submitting = false;
    mocks.store.catalog = {
      items: [
        {
          kind: 'pose',
          label: '体位',
          order: 1,
          items: [
            {
              preset_type: 'pose',
              preset_id: 'pose-a',
              label: '测试体位',
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
              order: 1,
              kind_label: '体位',
            },
          ],
        },
      ],
      total: 1,
      page: 1,
      page_size: 40,
      sort: 'default',
      facets: {
        kinds: [{ value: 'pose', label: '体位', count: 1 }],
        category_groups: [],
        subcategories: [],
        task_statuses: [],
      },
    };
    mocks.store.catalogQueryKey = JSON.stringify({
      kind: 'pose',
      keyword: '',
      resource: 'without-image',
      rating: '',
      category_group: '',
      subcategory: '',
      candidate_status: '',
      task_status: '',
      page: 1,
      page_size: 40,
      sort: 'default',
    });
    mocks.store.settings = settingsPayload;
    localStorage.setItem(
      PRESET_ASSET_PAGE_STATE_STORAGE_KEY,
      JSON.stringify({
        version: 1,
        filters: {
          kind: 'pose',
          keyword: '',
          resource: 'without-image',
          candidateStatus: '',
          rating: '',
          categoryGroup: '',
          subcategory: '',
          sort: 'default',
        },
        page: 1,
        selection: null,
        taskCenterOpen: false,
        taskFilter: 'active',
        taskStatus: '',
        listScrollTop: 0,
        taskScrollTop: 0,
      }),
    );
  });

  it('submits the current material draft in batch mode', async () => {
    const user = userEvent.setup();
    savePresetAssetSettingsDraft(
      { ...settingsPayload.defaults, steps: 37 },
      'pose',
    );

    render(<PresetAssetWorkshopPanel />);
    expect(screen.queryByText('批量生成参数')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /批量补图/ }));
    expect(screen.getByText('批量生成参数')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'toggle pose-a' }));
    await user.click(screen.getByRole('button', { name: /加入补图队列/ }));

    expect(mocks.createPresetAssetBatch).toHaveBeenCalledWith(
      [
        {
          presetType: 'pose',
          presetId: 'pose-a',
          params: expect.objectContaining({ steps: 37 }),
        },
      ],
      expect.objectContaining({ steps: 37 }),
    );
  });

  it('keeps missing-image items selectable as a single preset', async () => {
    const user = userEvent.setup();

    render(<PresetAssetWorkshopPanel />);

    expect(screen.getByText('single-list')).toBeInTheDocument();
    expect(screen.queryByText('批量生成参数')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'select pose-a' }));

    expect(mocks.selectPresetAsset).toHaveBeenCalledWith({
      presetType: 'pose',
      presetId: 'pose-a',
      label: '测试体位',
    });
  });

  it('restores directory task status independently from task center status', async () => {
    localStorage.setItem(
      PRESET_ASSET_PAGE_STATE_STORAGE_KEY,
      JSON.stringify({
        version: 1,
        filters: {
          taskStatus: 'failed',
        },
        page: 1,
        selection: null,
        taskCenterOpen: false,
        taskFilter: 'active',
        taskStatus: 'interrupted',
        listScrollTop: 0,
        taskScrollTop: 0,
      }),
    );

    render(<PresetAssetWorkshopPanel />);

    await waitFor(() => {
      expect(mocks.loadPresetAssetCatalog).toHaveBeenCalledWith(
        expect.objectContaining({
          task_status: 'failed',
        }),
      );
    });
    expect(
      JSON.parse(
        localStorage.getItem(PRESET_ASSET_PAGE_STATE_STORAGE_KEY) || '{}',
      ),
    ).toMatchObject({
      filters: { taskStatus: 'failed' },
      taskStatus: 'interrupted',
    });
  });

  it('keeps the selected page until the matching catalog response arrives', async () => {
    const user = userEvent.setup();

    render(<PresetAssetWorkshopPanel />);
    expect(screen.getByTestId('list-page')).toHaveTextContent('1');

    await user.click(screen.getByRole('button', { name: 'page 2' }));

    expect(screen.getByTestId('list-page')).toHaveTextContent('2');
    await waitFor(() => {
      expect(mocks.loadPresetAssetCatalog).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2, page_size: 40 }),
      );
    });
    expect(screen.getByTestId('list-page')).toHaveTextContent('2');
  });

  it('leaves batch mode when the task center opens a preset', async () => {
    const user = userEvent.setup();

    render(<PresetAssetWorkshopPanel />);
    await user.click(screen.getByRole('button', { name: /批量补图/ }));
    expect(screen.getByText('batch-list')).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'task-view-preset' }),
    );

    expect(screen.getByText('single-list')).toBeInTheDocument();
    expect(screen.queryByText('batch-list')).not.toBeInTheDocument();
  });

  it('shows the single-item generation and candidate workspace for a selected missing-image preset', async () => {
    const user = userEvent.setup();
    const summary = mocks.store.catalog?.items[0]?.items[0];
    if (!summary) throw new Error('test catalog item missing');
    mocks.store.selection = {
      presetType: 'pose',
      presetId: 'pose-a',
      label: '测试体位',
    };
    mocks.store.detail = {
      preset: {},
      summary,
      sources: [],
      candidates: [],
      versions: [],
    };

    render(<PresetAssetWorkshopPanel />);

    expect(screen.getByText('测试体位')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '候选图 (0)' })).toBeInTheDocument();
    const paramsPanel = screen.getByRole('complementary');
    expect(within(paramsPanel).getByText('生成参数')).toBeInTheDocument();
    expect(screen.getByText('单项生成参数')).toBeInTheDocument();
  });
});
