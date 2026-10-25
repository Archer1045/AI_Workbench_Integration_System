import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  PictureOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Badge,
  Button,
  Empty,
  Space,
  Spin,
  Tabs,
  Tag,
  message,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  apiErrorMessage,
  createPresetAssetBatch,
  loadPresetAssetCatalog,
  loadPresetAssetJobs,
  loadPresetAssetSettings,
  presetAssetStore,
  presetAssetCatalogQueryKey,
  refreshPresetAssetDetail,
  selectPresetAsset,
  setPresetAssetSelection,
} from '../stores/presetAssetStore';
import type {
  PresetAssetCatalogItem,
  PresetAssetCatalogQuery,
} from '../api';
import {
  DEFAULT_PRESET_ASSET_FILTERS,
  savePresetAssetFilters,
  type PresetAssetFilters,
} from '../presetAssetFilters';
import { loadPresetAssetSettingsWithDefaults } from '../presetAssetSettingsPersistence';
import {
  firstPresetAssetSettingsError,
  validatePresetAssetSettings,
} from '../presetAssetSettingsValidation';
import {
  isPresetAssetSelectionVisible,
  loadPresetAssetPageState,
  presetAssetSelectionKey,
  savePresetAssetPageState,
  type PresetAssetPageState,
  type PresetAssetTaskFilter,
  type PresetAssetTaskStatusFilter,
} from '../presetAssetPageState';
import PresetAssetCompare from './PresetAssetCompare';
import PresetAssetFilterBar from './PresetAssetFilterBar';
import PresetAssetHistory from './PresetAssetHistory';
import PresetAssetList from './PresetAssetList';
import PresetAssetParamsPanel from './PresetAssetParamsPanel';
import PresetAssetTaskCenter from './PresetAssetTaskCenter';

const ACTIVE_JOB_STATUSES = new Set([
  'queued',
  'preparing',
  'running',
  'cancel_requested',
]);
const PAGE_SIZE = 40;
const QUERY_DEBOUNCE_MS = 250;
const SCROLL_SAVE_DEBOUNCE_MS = 250;

function itemKey(item: PresetAssetCatalogItem): string {
  return `${item.preset_type}:${item.preset_id}`;
}

export default function PresetAssetWorkshopPanel() {
  const {
    catalog,
    catalogQueryKey: loadedCatalogQueryKey,
    detail,
    jobs,
    settings: settingsPayload,
    loadingCatalog,
    loadingDetail,
    loadingJobs,
    selection,
    submitting,
  } = presetAssetStore;
  const [initialPageState] = useState<PresetAssetPageState>(() =>
    loadPresetAssetPageState(),
  );
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [taskCenterOpen, setTaskCenterOpen] = useState(
    initialPageState.taskCenterOpen,
  );
  const [taskFilter, setTaskFilter] = useState<PresetAssetTaskFilter>(
    initialPageState.taskFilter,
  );
  const [taskStatus, setTaskStatus] = useState<PresetAssetTaskStatusFilter>(
    initialPageState.taskStatus,
  );
  const [batchMode, setBatchMode] = useState(false);
  const [activeDetailTab, setActiveDetailTab] = useState('candidates');
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => new Set());
  const [selectionRevealToken, setSelectionRevealToken] = useState(0);
  const [filters, setFilters] = useState<PresetAssetFilters>(
    initialPageState.filters,
  );
  const [page, setPage] = useState(initialPageState.page);
  const pageStateRef = useRef<PresetAssetPageState>(initialPageState);
  const listScrollTopRef = useRef(initialPageState.listScrollTop);
  const taskScrollTopRef = useRef(initialPageState.taskScrollTop);
  const initializedDetailKeyRef = useRef('');
  const scrollSaveTimerRef = useRef<ReturnType<typeof globalThis.setTimeout>>();
  const catalogQuery = useMemo<PresetAssetCatalogQuery>(
    () => ({
      kind: filters.kind,
      keyword: filters.keyword,
      resource: filters.resource,
      rating: filters.rating,
      category_group: filters.categoryGroup,
      subcategory: filters.subcategory,
      candidate_status: filters.candidateStatus || undefined,
      task_status: filters.taskStatus || undefined,
      page,
      page_size: PAGE_SIZE,
      sort: filters.sort,
    }),
    [filters, page],
  );
  const catalogQueryKey = presetAssetCatalogQueryKey(catalogQuery);
  const selectionKey = presetAssetSelectionKey(selection);
  const visibleItems = useMemo(() => catalog?.items[0]?.items || [], [catalog]);
  const catalogResponseCurrent =
    Boolean(catalog) && loadedCatalogQueryKey === catalogQueryKey;
  const selectionVisible = isPresetAssetSelectionVisible(
    selection,
    visibleItems,
    loadedCatalogQueryKey,
    catalogQueryKey,
  );
  const totalCount = catalog?.total || 0;
  const batchLimit = settingsPayload?.limits.batch_max_items || 0;
  const selectedVisibleIndex = selection
    ? visibleItems.findIndex(
        (item) =>
          item.preset_type === selection.presetType &&
          item.preset_id === selection.presetId,
      )
    : -1;
  const activeTaskCount = jobs.filter((job) =>
    ACTIVE_JOB_STATUSES.has(job.status),
  ).length;
  const filterKey = useMemo(() => JSON.stringify(filters), [filters]);

  useEffect(() => {
    if (!selectionKey) {
      initializedDetailKeyRef.current = '';
      return;
    }
    if (!detail || initializedDetailKeyRef.current === selectionKey) return;
    initializedDetailKeyRef.current = selectionKey;
    const hasCandidates = detail.candidates.some(
      (candidate) => candidate.status !== 'discarded',
    );
    setActiveDetailTab(hasCandidates ? 'candidates' : 'params');
  }, [detail, selectionKey]);

  const schedulePageStateSave = () => {
    if (scrollSaveTimerRef.current !== undefined) {
      globalThis.clearTimeout(scrollSaveTimerRef.current);
    }
    scrollSaveTimerRef.current = globalThis.setTimeout(() => {
      savePresetAssetPageState(pageStateRef.current);
      scrollSaveTimerRef.current = undefined;
    }, SCROLL_SAVE_DEBOUNCE_MS);
  };

  const handleScrollTopChange = (
    field: 'listScrollTop' | 'taskScrollTop',
    value: number,
  ) => {
    const next = Math.max(0, value);
    if (field === 'listScrollTop') {
      listScrollTopRef.current = next;
    } else {
      taskScrollTopRef.current = next;
    }
    pageStateRef.current = {
      ...pageStateRef.current,
      [field]: next,
    };
    schedulePageStateSave();
  };

  const handleFilterChange = (patch: Partial<PresetAssetFilters>) => {
    if (patch.kind && patch.kind !== filters.kind) {
      setPresetAssetSelection(null);
      setSelectedKeys(new Set());
    }
    if (patch.resource && patch.resource !== 'without-image') {
      setBatchMode(false);
      setSelectedKeys(new Set());
    }
    setFilters((current) => ({ ...current, ...patch }));
    setPage(1);
    listScrollTopRef.current = 0;
  };

  useEffect(() => {
    if (!presetAssetStore.selection && initialPageState.selection) {
      setPresetAssetSelection(initialPageState.selection);
    }
  }, [initialPageState.selection]);

  useEffect(() => {
    const nextState: PresetAssetPageState = {
      version: 1,
      filters,
      page,
      selection: selection
        ? {
            presetType: selection.presetType,
            presetId: selection.presetId,
            label: selection.label,
          }
        : null,
      taskCenterOpen,
      taskFilter,
      taskStatus,
      listScrollTop: listScrollTopRef.current,
      taskScrollTop: taskScrollTopRef.current,
    };
    pageStateRef.current = nextState;
    savePresetAssetFilters(filters);
    savePresetAssetPageState(nextState);
  }, [filters, page, selection, taskCenterOpen, taskFilter, taskStatus]);

  useEffect(() => {
    const flush = () => savePresetAssetPageState(pageStateRef.current);
    window.addEventListener('beforeunload', flush);
    return () => {
      window.removeEventListener('beforeunload', flush);
      if (scrollSaveTimerRef.current !== undefined) {
        globalThis.clearTimeout(scrollSaveTimerRef.current);
      }
      flush();
    };
  }, []);

  useEffect(() => {
    const timer = globalThis.setTimeout(() => {
      void loadPresetAssetCatalog(catalogQuery).catch((error) => {
        setLoadError(apiErrorMessage(error, '预设目录加载失败'));
      });
    }, QUERY_DEBOUNCE_MS);
    return () => globalThis.clearTimeout(timer);
  }, [catalogQueryKey]);

  useEffect(() => {
    if (!catalogResponseCurrent) return;
    if (selection && !selectionVisible) {
      setPresetAssetSelection(null);
    }
  }, [catalogResponseCurrent, selection, selectionVisible]);

  useEffect(() => {
    if (catalogResponseCurrent && catalog && catalog.page !== page) {
      setPage(catalog.page);
    }
  }, [catalog, catalogResponseCurrent, page]);

  useEffect(() => {
    const visibleKeys = new Set(visibleItems.map(itemKey));
    setSelectedKeys((current) => {
      if (!batchMode) {
        return current.size > 0 ? new Set() : current;
      }
      const next = new Set(
        Array.from(current).filter((key) => visibleKeys.has(key)),
      );
      return next.size === current.size ? current : next;
    });
  }, [batchMode, visibleItems]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError('');
    const tasks: Promise<unknown>[] = [
      loadPresetAssetSettings(),
      loadPresetAssetJobs(),
    ];
    Promise.allSettled(tasks)
      .then((results) => {
        const failed = results.find((result) => result.status === 'rejected');
        if (failed?.status === 'rejected') {
          const error = apiErrorMessage(failed.reason, '工坊数据加载失败');
          if (active) setLoadError(error);
          message.error(error);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (
      !catalogResponseCurrent ||
      !selectionVisible ||
      !selectionKey ||
      presetAssetStore.detail ||
      presetAssetStore.loadingDetail
    ) {
      return;
    }
    setLoadError('');
    void refreshPresetAssetDetail().catch((error) => {
      const detailError = apiErrorMessage(error, '预设详情加载失败');
      setLoadError(detailError);
      message.error(detailError);
    });
  }, [catalogResponseCurrent, selectionKey, selectionVisible]);

  const handleSelect = (selection: Parameters<typeof selectPresetAsset>[0]) => {
    setLoadError('');
    void selectPresetAsset(selection).catch((error) => {
      const detailError = apiErrorMessage(error, '预设详情加载失败');
      setLoadError(detailError);
      message.error(detailError);
    });
  };

  const moveVisibleSelection = (offset: number) => {
    if (selectedVisibleIndex < 0) return;
    const target = visibleItems[selectedVisibleIndex + offset];
    if (!target) return;
    handleSelect({
      presetType: target.preset_type,
      presetId: target.preset_id,
      label: target.label,
    });
    setSelectionRevealToken((current) => current + 1);
  };

  const revealSelectedPreset = () => {
    if (selectedVisibleIndex < 0) return;
    setSelectionRevealToken((current) => current + 1);
  };

  const toggleBatchMode = () => {
    setBatchMode((current) => !current);
    setSelectedKeys(new Set());
  };

  const handleToggleSelection = (
    item: PresetAssetCatalogItem,
    checked: boolean,
  ) => {
    const key = itemKey(item);
    if (!checked) {
      setSelectedKeys((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
      return;
    }
    if (selectedKeys.has(key)) return;
    if (batchLimit <= 0 || selectedKeys.size >= batchLimit) {
      message.warning(`单次批量补图最多选择 ${batchLimit} 项`);
      return;
    }
    setSelectedKeys((current) => new Set(current).add(key));
  };

  const submitBatch = async () => {
    if (!settingsPayload) {
      message.error('生成设置尚未加载完成');
      return;
    }
    const selectedItems = visibleItems.filter((item) =>
      selectedKeys.has(itemKey(item)),
    );
    if (selectedItems.length === 0) {
      message.warning('请先选择需要补图的预设');
      return;
    }
    const settings = loadPresetAssetSettingsWithDefaults(
      filters.kind,
      settingsPayload.defaults,
    );
    const settingsErrors = validatePresetAssetSettings(
      settings,
      settingsPayload.limits,
      settingsPayload.targets[filters.kind],
    );
    const firstError = firstPresetAssetSettingsError(settingsErrors);
    if (firstError) {
      message.error(firstError);
      return;
    }
    try {
      await createPresetAssetBatch(
        selectedItems.map((item) => ({
          presetType: item.preset_type,
          presetId: item.preset_id,
          params: settings,
        })),
        settings,
      );
      setSelectedKeys(new Set());
      setTaskCenterOpen(true);
      message.success('已加入补图队列，候选生成后仍需人工验收');
    } catch (error) {
      message.error(apiErrorMessage(error, '批量补图任务创建失败'));
    }
  };

  const handleViewTaskPreset = (
    selection: Parameters<typeof selectPresetAsset>[0],
  ) => {
    if (!selection) return;
    setBatchMode(false);
    setPresetAssetSelection(null);
    setSelectedKeys(new Set());
    setFilters((current) => ({
      ...current,
      kind: selection.presetType,
      keyword: '',
      resource: 'all',
      candidateStatus: '',
      taskStatus: '',
      rating: '',
      categoryGroup: '',
      subcategory: '',
    }));
    setPage(1);
    listScrollTopRef.current = 0;
    setLoadError('');
    setPresetAssetSelection(selection);
  };

  const items = useMemo(
    () => [
      {
        key: 'candidates',
        label: `候选图 (${detail?.candidates.filter((item) => item.status !== 'discarded').length || 0})`,
        children: <PresetAssetCompare />,
      },
      {
        key: 'history',
        label: `版本与审计 (${detail?.versions.length || 0})`,
        children: <PresetAssetHistory />,
      },
    ],
    [detail?.candidates, detail?.versions.length],
  );

  return (
    <div className="preset-asset-workshop-panel">
      <div className="preset-asset-workshop-page-header">
        <div className="train-section-title">预设缩略图工坊</div>
        <Space wrap>
          <Tag color="blue">
            {totalCount} 项
          </Tag>
          <Badge count={activeTaskCount} size="small">
            <Button
              icon={<UnorderedListOutlined />}
              onClick={() => {
                setTaskCenterOpen(true);
                void loadPresetAssetJobs().catch((error) =>
                  message.error(apiErrorMessage(error, '任务列表加载失败')),
                );
              }}
            >
              任务中心
            </Button>
          </Badge>
          {filters.resource === 'without-image' ? (
            <Button
              icon={<PictureOutlined />}
              type={batchMode ? 'default' : 'primary'}
              onClick={toggleBatchMode}
            >
              {batchMode ? '退出批量' : '批量补图'}
            </Button>
          ) : null}
          <Button
            icon={<ReloadOutlined />}
            loading={loading || loadingCatalog || loadingDetail || loadingJobs}
            onClick={() => {
              setLoadError('');
              void Promise.allSettled([
                loadPresetAssetCatalog(catalogQuery),
                loadPresetAssetJobs(),
              ]).then((results) => {
                const failed = results.find((result) => result.status === 'rejected');
                if (failed?.status === 'rejected') {
                  message.error(apiErrorMessage(failed.reason, '工坊数据刷新失败'));
                }
              });
              if (presetAssetStore.selection) {
                void refreshPresetAssetDetail().catch((error) => {
                  const detailError = apiErrorMessage(error, '详情加载失败');
                  setLoadError(detailError);
                  message.error(detailError);
                });
              }
            }}
          >
            刷新
          </Button>
        </Space>
      </div>
      <PresetAssetFilterBar
        catalog={catalog}
        filters={filters}
        visibleCount={visibleItems.length}
        onChange={handleFilterChange}
        onReset={() => {
          handleFilterChange({
            keyword: '',
            resource: 'all',
            candidateStatus: '',
            taskStatus: '',
            rating: '',
            categoryGroup: '',
            subcategory: '',
            sort: 'default',
          });
        }}
      />
      {batchMode ? (
        <section className="preset-asset-batch-bar">
          <div className="preset-asset-batch-copy">
            <strong>批量补图队列</strong>
            <span>
              已选 {selectedKeys.size}/{batchLimit} 项，候选串行排队，仍需人工验收。
            </span>
          </div>
          <Space wrap size={6}>
            <Button
              size="small"
              disabled={batchLimit <= 0 || visibleItems.length === 0}
              onClick={() =>
                setSelectedKeys(
                  new Set(
                    visibleItems
                      .slice(0, batchLimit)
                      .map((item) => itemKey(item)),
                  ),
                )
              }
            >
              选择前 {Math.min(batchLimit, visibleItems.length)} 项
            </Button>
            <Button
              size="small"
              disabled={selectedKeys.size === 0}
              onClick={() => setSelectedKeys(new Set())}
            >
              清空选择
            </Button>
            <Button
              size="small"
              type="primary"
              icon={<PictureOutlined />}
              loading={submitting}
              disabled={selectedKeys.size === 0 || batchLimit <= 0}
              onClick={() => void submitBatch()}
            >
              加入补图队列
            </Button>
          </Space>
        </section>
      ) : null}
      <div className="preset-asset-workshop-layout">
        <section className="preset-asset-workshop-sidebar">
          <PresetAssetList
            items={visibleItems}
            loading={loadingCatalog}
            filterKey={filterKey}
            page={page}
            pageSize={catalog?.page_size || PAGE_SIZE}
            total={totalCount}
            emptyText={totalCount === 0 ? '暂无预设' : '无匹配项'}
            onSelect={handleSelect}
            onPageChange={(nextPage) => {
              setPage(nextPage);
              listScrollTopRef.current = 0;
            }}
            scrollTop={listScrollTopRef.current}
            onScrollTopChange={(value) =>
              handleScrollTopChange('listScrollTop', value)
            }
            selectable={batchMode}
            selectedKeys={selectedKeys}
            selectionLimit={batchLimit}
            onToggle={handleToggleSelection}
            onMoveSelection={moveVisibleSelection}
            onRevealSelection={revealSelectedPreset}
            revealToken={selectionRevealToken}
          />
        </section>
        <section className="preset-asset-workshop-main">
          {batchMode ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="请在右侧设置批量生成参数，并在左侧选择要补图的预设"
            />
          ) : !selection ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="从左侧选择体位、服装、场景或身体改造预设"
            />
          ) : (
            <Spin spinning={loadingDetail}>
              {detail ? (
                <>
                  <div className="preset-asset-workshop-heading">
                    <div>
                      <div className="train-section-title">{detail.summary.label}</div>
                      <div className="help">
                        {detail.summary.preset_type} / {detail.summary.preset_id}
                      </div>
                    </div>
                    <Space wrap size={4}>
                      <Button
                        size="small"
                        icon={<ArrowUpOutlined aria-hidden="true" />}
                        disabled={selectedVisibleIndex <= 0}
                        onClick={() => moveVisibleSelection(-1)}
                      >
                        上一项
                      </Button>
                      <Button
                        size="small"
                        icon={<ArrowDownOutlined aria-hidden="true" />}
                        disabled={
                          selectedVisibleIndex < 0 ||
                          selectedVisibleIndex >= visibleItems.length - 1
                        }
                        onClick={() => moveVisibleSelection(1)}
                      >
                        下一项
                      </Button>
                      {detail.summary.active_version ? (
                        <Tag color="green">正式版本 {detail.summary.active_version.version}</Tag>
                      ) : (
                        <Tag>暂无正式版本</Tag>
                      )}
                      {detail.summary.ready_count > 0 ? (
                        <Tag color="blue">{detail.summary.ready_count} 个可采纳</Tag>
                      ) : null}
                      {detail.summary.failed_count > 0 ? (
                        <Tag color="red">{detail.summary.failed_count} 个失败</Tag>
                      ) : null}
                    </Space>
                  </div>
                  <Tabs
                    activeKey={activeDetailTab}
                    items={items}
                    onChange={setActiveDetailTab}
                  />
                </>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={loadError || '正在加载预设详情'}
                />
              )}
            </Spin>
          )}
        </section>
        <aside className="preset-asset-workshop-params">
          <div className="preset-asset-workshop-heading">
            <div>
              <div className="train-section-title">生成参数</div>
              <div className="help">参数草稿会自动持久化</div>
            </div>
          </div>
          {batchMode || selection ? (
            <PresetAssetParamsPanel
              presetType={batchMode ? filters.kind : undefined}
              batchMode={batchMode}
            />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="选择预设后可编辑生成参数"
            />
          )}
        </aside>
      </div>
      <PresetAssetTaskCenter
        open={taskCenterOpen}
        onClose={() => setTaskCenterOpen(false)}
        onViewPreset={handleViewTaskPreset}
        filter={taskFilter}
        onFilterChange={setTaskFilter}
        statusFilter={taskStatus}
        onStatusFilterChange={setTaskStatus}
        scrollTop={taskScrollTopRef.current}
        onScrollTopChange={(value) =>
          handleScrollTopChange('taskScrollTop', value)
        }
      />
    </div>
  );
}
