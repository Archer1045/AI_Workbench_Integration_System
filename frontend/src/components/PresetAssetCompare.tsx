import {
  CheckOutlined,
  CompressOutlined,
  DeleteOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  LeftOutlined,
  PushpinFilled,
  PushpinOutlined,
  ReloadOutlined,
  RightOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Collapse,
  Descriptions,
  Empty,
  Image,
  Modal,
  Popconfirm,
  Space,
  Tag,
  Tooltip,
  message,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { PresetAssetCandidate } from '../api';
import {
  adoptPresetAsset,
  apiErrorMessage,
  clearPresetAssetCandidates,
  discardPresetAsset,
  presetAssetStore,
} from '../stores/presetAssetStore';

const STATUS_COLORS: Record<string, string> = {
  ready: 'green',
  adopted: 'blue',
  queued: 'gold',
  preparing: 'gold',
  running: 'processing',
  cancel_requested: 'orange',
  cancelled: 'default',
  stopped: 'default',
  interrupted: 'red',
  failed: 'red',
  discarded: 'default',
};

const STATUS_LABELS: Record<string, string> = {
  ready: '可采纳',
  adopted: '已采纳',
  queued: '排队中',
  preparing: '准备中',
  running: '生成中',
  cancel_requested: '取消中',
  cancelled: '已取消',
  stopped: '已停止',
  interrupted: '已中断',
  failed: '失败',
  discarded: '已丢弃',
};

const MIN_COMPARE_ITEMS = 2;
const MAX_COMPARE_ITEMS = 4;
const MIN_COMPARE_ZOOM = 0.5;
const MAX_COMPARE_ZOOM = 3;
const COMPARE_ZOOM_STEP = 0.1;
const COMPARE_DRAG_CLICK_THRESHOLD = 6;

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

function formatSize(candidate: PresetAssetCandidate): string {
  if (!candidate.output_width || !candidate.output_height) return '未记录';
  return `${candidate.output_width}×${candidate.output_height}`;
}

function formatParams(value: Record<string, unknown> | undefined): string {
  if (!value || Object.keys(value).length === 0) return '默认';
  try {
    return JSON.stringify(value);
  } catch {
    return '默认';
  }
}

interface CandidateActionButtonsProps {
  candidate: PresetAssetCandidate;
  workingId: number | null;
  disabled?: boolean;
  onAdopt: () => Promise<void>;
  onDiscard: () => Promise<void>;
}

function CandidateActionButtons({
  candidate,
  workingId,
  disabled = false,
  onAdopt,
  onDiscard,
}: CandidateActionButtonsProps) {
  const canAdopt = candidate.status === 'ready';
  const canDiscard = candidate.status !== 'adopted';
  const busy = disabled || workingId !== null;
  const isWorking = workingId === candidate.id;

  return (
    <Space wrap size={6}>
      <Popconfirm
        title="采纳后立即替换正式图和缩略图"
        description="请确认已人工检查候选内容。"
        disabled={!canAdopt || (busy && !isWorking)}
        onConfirm={onAdopt}
      >
        <Button
          type="primary"
          size="small"
          icon={<CheckOutlined aria-hidden="true" />}
          disabled={!canAdopt || (busy && !isWorking)}
          loading={isWorking}
        >
          人工采纳
        </Button>
      </Popconfirm>
      <Popconfirm
        title="丢弃该候选？"
        disabled={!canDiscard || (busy && !isWorking)}
        onConfirm={onDiscard}
      >
        <Button
          danger
          size="small"
          icon={<DeleteOutlined aria-hidden="true" />}
          disabled={!canDiscard || (busy && !isWorking)}
          loading={isWorking}
        >
          丢弃
        </Button>
      </Popconfirm>
      {candidate.status === 'failed' || candidate.status === 'interrupted' ? (
        <Tooltip title="可在任务进度区重试失败项">
          <ReloadOutlined className="preset-asset-hint-icon" />
        </Tooltip>
      ) : null}
    </Space>
  );
}

export default function PresetAssetCompare() {
  const { detail } = presetAssetStore;
  const [workingId, setWorkingId] = useState<number | null>(null);
  const [clearing, setClearing] = useState(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(
    null,
  );
  const [compareSelectedId, setCompareSelectedId] = useState<number | null>(
    null,
  );
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [pinnedIds, setPinnedIds] = useState<Set<number>>(() => new Set());
  const [hiddenIds, setHiddenIds] = useState<Set<number>>(() => new Set());
  const [compareZoom, setCompareZoom] = useState(1);
  const [comparePan, setComparePan] = useState({ x: 0, y: 0 });
  const dragStateRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const suppressNextPanelClickRef = useRef(false);

  const candidates = useMemo(
    () => (detail?.candidates || []).filter((item) => item.status !== 'discarded'),
    [detail?.candidates],
  );
  const candidateById = useMemo(
    () => new Map(candidates.map((candidate) => [candidate.id, candidate])),
    [candidates],
  );
  const compareCandidates = useMemo(
    () =>
      compareIds
        .map((candidateId) => candidateById.get(candidateId))
        .filter((candidate): candidate is PresetAssetCandidate =>
          Boolean(candidate),
        ),
    [candidateById, compareIds],
  );
  const visibleCompareCandidates = useMemo(
    () =>
      compareCandidates.filter((candidate) => !hiddenIds.has(candidate.id)),
    [compareCandidates, hiddenIds],
  );
  const compareIdSet = useMemo(() => new Set(compareIds), [compareIds]);
  const clearableCandidates = useMemo(
    () => candidates.filter((item) => item.status !== 'adopted'),
    [candidates],
  );
  const hasGeneratingCandidates = candidates.some((item) =>
    ['queued', 'preparing', 'running', 'cancel_requested'].includes(item.status),
  );
  const canClear =
    !clearing &&
    workingId === null &&
    clearableCandidates.length > 0 &&
    !hasGeneratingCandidates;
  const selectedIndex = candidates.findIndex(
    (candidate) => candidate.id === selectedCandidateId,
  );
  const selectedCandidate =
    selectedIndex >= 0 ? candidates[selectedIndex] : null;
  const compareSelectedCandidate =
    compareCandidates.find((candidate) => candidate.id === compareSelectedId) ||
    null;

  const run = async (
    candidateId: number,
    action: () => Promise<unknown>,
    done: string,
  ): Promise<boolean> => {
    setWorkingId(candidateId);
    try {
      await action();
      message.success(done);
      return true;
    } catch (error) {
      message.error(apiErrorMessage(error, '操作失败'));
      return false;
    } finally {
      setWorkingId(null);
    }
  };

  const execute = async (
    candidateId: number,
    action: () => Promise<unknown>,
    done: string,
    closeAfterSuccess = false,
  ) => {
    const succeeded = await run(candidateId, action, done);
    if (succeeded && closeAfterSuccess) {
      setSelectedCandidateId(null);
    }
  };

  const clearCandidates = async () => {
    setClearing(true);
    try {
      const clearedCount = await clearPresetAssetCandidates();
      setSelectedCandidateId(null);
      message.success(`已清空 ${clearedCount} 张候选`);
    } catch (error) {
      message.error(apiErrorMessage(error, '清空候选失败'));
    } finally {
      setClearing(false);
    }
  };

  const moveSelection = (offset: number) => {
    if (selectedIndex < 0) return;
    const nextIndex = selectedIndex + offset;
    if (nextIndex < 0 || nextIndex >= candidates.length) return;
    setSelectedCandidateId(candidates[nextIndex].id);
  };

  const toggleCompareCandidate = (candidateId: number) => {
    setCompareIds((current) => {
      if (current.includes(candidateId)) {
        if (compareOpen && current.length <= MIN_COMPARE_ITEMS) {
          message.warning(`对比区至少保留 ${MIN_COMPARE_ITEMS} 张图片`);
          return current;
        }
        return current.filter((item) => item !== candidateId);
      }
      if (current.length >= MAX_COMPARE_ITEMS) {
        message.warning(`多图对比最多选择 ${MAX_COMPARE_ITEMS} 张候选`);
        return current;
      }
      return [...current, candidateId];
    });
  };

  const openCompare = () => {
    if (candidates.length < MIN_COMPARE_ITEMS) {
      message.warning(`至少需要 ${MIN_COMPARE_ITEMS} 张候选才能对比`);
      return;
    }
    const liveIds = new Set(candidates.map((candidate) => candidate.id));
    const validIds = compareIds.filter((candidateId) => liveIds.has(candidateId));
    const nextIds =
      validIds.length >= MIN_COMPARE_ITEMS
        ? validIds
        : candidates.slice(0, MAX_COMPARE_ITEMS).map((candidate) => candidate.id);
    setCompareIds(nextIds);
    setCompareSelectedId(
      selectedCandidateId !== null && nextIds.includes(selectedCandidateId)
        ? selectedCandidateId
        : nextIds[0] || null,
    );
    setCompareZoom(1);
    setComparePan({ x: 0, y: 0 });
    setCompareOpen(true);
  };

  const togglePinned = (candidateId: number) => {
    setPinnedIds((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) {
        next.delete(candidateId);
      } else {
        next.add(candidateId);
      }
      return next;
    });
  };

  const toggleHidden = (candidateId: number) => {
    setHiddenIds((current) => {
      if (!current.has(candidateId) && visibleCompareCandidates.length <= MIN_COMPARE_ITEMS) {
        message.warning(`对比区至少保留 ${MIN_COMPARE_ITEMS} 张图片`);
        return current;
      }
      const next = new Set(current);
      if (next.has(candidateId)) {
        next.delete(candidateId);
      } else {
        next.add(candidateId);
      }
      return next;
    });
  };

  const quickSelectCandidate = (candidateId: number) => {
    setCompareIds((current) => {
      if (current.includes(candidateId)) {
        setHiddenIds((hidden) => {
          if (!hidden.has(candidateId)) return hidden;
          const next = new Set(hidden);
          next.delete(candidateId);
          return next;
        });
        return current;
      }
      if (current.length < MAX_COMPARE_ITEMS) {
        return [...current, candidateId];
      }
      const replaceIndex = current.findIndex(
        (selectedId) => !pinnedIds.has(selectedId),
      );
      if (replaceIndex < 0) {
        message.warning('四张候选均已固定，请先取消一个固定项');
        return current;
      }
      const next = [...current];
      next[replaceIndex] = candidateId;
      setHiddenIds((hidden) => {
        const updated = new Set(hidden);
        updated.delete(current[replaceIndex]);
        updated.delete(candidateId);
        return updated;
      });
      return next;
    });
  };

  const quickSelectButtonLabel = (candidateId: number): string => {
    if (compareIdSet.has(candidateId)) {
      return hiddenIds.has(candidateId)
        ? `恢复候选 ${candidateId} 到对比`
        : `候选 ${candidateId} 已在对比中`;
    }
    return `将候选 ${candidateId} 加入对比`;
  };

  const updateCompareZoom = (nextZoom: number) => {
    setCompareZoom(
      Math.min(
        MAX_COMPARE_ZOOM,
        Math.max(MIN_COMPARE_ZOOM, Number(nextZoom.toFixed(2))),
      ),
    );
  };

  const resetCompareView = () => {
    setCompareZoom(1);
    setComparePan({ x: 0, y: 0 });
  };

  const selectCompareCandidate = (candidateId: number) => {
    setCompareSelectedId(candidateId);
  };

  const handleComparePanelClick = (
    event: React.MouseEvent<HTMLElement>,
    candidateId: number,
  ) => {
    const target = event.target as HTMLElement;
    if (target.closest('button, a, input, textarea, select, [role="button"]')) {
      return;
    }
    if (suppressNextPanelClickRef.current) {
      suppressNextPanelClickRef.current = false;
      return;
    }
    selectCompareCandidate(candidateId);
  };

  const startCompareDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: comparePan.x,
      originY: comparePan.y,
      moved: false,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const moveCompareDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - dragState.startX;
    const deltaY = event.clientY - dragState.startY;
    if (
      !dragState.moved &&
      Math.hypot(deltaX, deltaY) > COMPARE_DRAG_CLICK_THRESHOLD
    ) {
      dragState.moved = true;
    }
    if (!dragState.moved) return;
    setComparePan({
      x: dragState.originX + deltaX,
      y: dragState.originY + deltaY,
    });
  };

  const endCompareDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    dragStateRef.current = null;
    if (dragState.moved) {
      suppressNextPanelClickRef.current = true;
      window.setTimeout(() => {
        suppressNextPanelClickRef.current = false;
      }, 250);
    }
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
  };

  useEffect(() => {
    if (selectedCandidateId !== null && selectedIndex < 0) {
      setSelectedCandidateId(null);
    }
  }, [selectedCandidateId, selectedIndex]);

  useEffect(() => {
    if (!selectedCandidate) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        moveSelection(-1);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        moveSelection(1);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [candidates, selectedCandidate, selectedIndex]);

  useEffect(() => {
    const liveIds = new Set(candidates.map((candidate) => candidate.id));
    setCompareIds((current) => {
      const next = current.filter((candidateId) => liveIds.has(candidateId));
      return next.length === current.length ? current : next;
    });
    setPinnedIds((current) => {
      const next = new Set(
        Array.from(current).filter((candidateId) => liveIds.has(candidateId)),
      );
      return next.size === current.size ? current : next;
    });
    setHiddenIds((current) => {
      const next = new Set(
        Array.from(current).filter((candidateId) => liveIds.has(candidateId)),
      );
      return next.size === current.size ? current : next;
    });
  }, [candidates]);

  useEffect(() => {
    if (compareOpen && compareCandidates.length < MIN_COMPARE_ITEMS) {
      setCompareOpen(false);
    }
  }, [compareCandidates.length, compareOpen]);

  useEffect(() => {
    if (!compareOpen) return;
    if (
      compareSelectedId !== null &&
      visibleCompareCandidates.some(
        (candidate) => candidate.id === compareSelectedId,
      )
    ) {
      return;
    }
    setCompareSelectedId(visibleCompareCandidates[0]?.id ?? null);
  }, [compareOpen, compareSelectedId, visibleCompareCandidates]);

  if (!detail) {
    return <Alert type="info" showIcon message="选择预设后可查看候选图" />;
  }

  if (candidates.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无候选，先在参数面板导入源图或发起 AI 生成"
      />
    );
  }

  return (
    <div className="preset-asset-compare">
      <div className="preset-asset-compare-toolbar">
        <Alert
          type="info"
          showIcon
          message="候选仅供人工验收；可勾选 2 至 4 张并排比较，只有状态为“可采纳”的候选可以替换正式图。"
        />
        <Space wrap className="preset-asset-compare-toolbar-actions">
          <Button
            type={compareIds.length >= MIN_COMPARE_ITEMS ? 'primary' : 'default'}
            icon={<CompressOutlined aria-hidden="true" />}
            disabled={candidates.length < MIN_COMPARE_ITEMS}
            onClick={openCompare}
          >
            多图对比
          </Button>
          <Tag color={compareIds.length > 0 ? 'blue' : 'default'}>
            已选 {compareIds.length}/{MAX_COMPARE_ITEMS}
          </Tag>
          <Popconfirm
            title="清空当前候选区？"
            description={`将丢弃 ${clearableCandidates.length} 张未采纳候选，已采纳候选不会撤销。`}
            okText="清空"
            okButtonProps={{ danger: true }}
            disabled={!canClear}
            onConfirm={clearCandidates}
          >
            <Button
              danger
              icon={<DeleteOutlined aria-hidden="true" />}
              loading={clearing}
              disabled={!canClear}
            >
              一键清空
            </Button>
          </Popconfirm>
        </Space>
      </div>
      <div className="preset-asset-candidate-grid">
        {candidates.map((candidate) => {
          const preview =
            candidate.thumbnail_url || candidate.preview_url || candidate.original_url;
          const inCompare = compareIdSet.has(candidate.id);
          return (
            <article
              className={`preset-asset-candidate-card${
                inCompare ? ' preset-asset-candidate-card-compare' : ''
              }`}
              key={candidate.id}
            >
              <button
                type="button"
                className="preset-asset-candidate-preview-button"
                aria-label={`查看候选 ${candidate.id} 详情`}
                onClick={() => setSelectedCandidateId(candidate.id)}
              >
                <div className="preset-asset-candidate-preview">
                  {preview ? (
                    <Image
                      src={preview}
                      alt={`候选 ${candidate.id}`}
                      width="100%"
                      height={210}
                      preview={false}
                      style={{ objectFit: 'contain', background: '#f8fafc' }}
                    />
                  ) : (
                    <div className="preset-asset-candidate-empty">无预览</div>
                  )}
                </div>
              </button>
              <div className="preset-asset-candidate-copy">
                <Space size={4} wrap>
                  <Tag color={candidate.generation_mode === 'ai' ? 'purple' : 'cyan'}>
                    {candidate.generation_mode === 'ai' ? 'AI' : '裁剪'}
                  </Tag>
                  <Tag color={STATUS_COLORS[candidate.status] || 'default'}>
                    {statusLabel(candidate.status)}
                  </Tag>
                  <Tag>#{candidate.id}</Tag>
                </Space>
                {candidate.error ? (
                  <div className="preset-asset-candidate-error">{candidate.error}</div>
                ) : null}
                <Button
                  size="small"
                  type={inCompare ? 'primary' : 'default'}
                  icon={<CompressOutlined aria-hidden="true" />}
                  aria-label={
                    inCompare
                      ? `将候选 ${candidate.id} 移出对比`
                      : `将候选 ${candidate.id} 加入对比`
                  }
                  disabled={
                    !inCompare && compareIds.length >= MAX_COMPARE_ITEMS
                  }
                  onClick={() => toggleCompareCandidate(candidate.id)}
                >
                  {inCompare ? '移出对比' : '加入对比'}
                </Button>
                <CandidateActionButtons
                  candidate={candidate}
                  workingId={workingId}
                  disabled={clearing}
                  onAdopt={() =>
                    execute(
                      candidate.id,
                      () => adoptPresetAsset(candidate.id),
                      '候选已采纳',
                    )
                  }
                  onDiscard={() =>
                    execute(
                      candidate.id,
                      () => discardPresetAsset(candidate.id),
                      '候选已丢弃',
                    )
                  }
                />
              </div>
            </article>
          );
        })}
      </div>
      <Modal
        className="preset-asset-compare-modal"
        title="候选多图对比"
        open={compareOpen}
        width={1240}
        footer={
          <div className="preset-asset-compare-modal-footer">
            <div className="preset-asset-compare-modal-selection">
              <strong>
                {compareSelectedCandidate
                  ? `已选择候选 #${compareSelectedCandidate.id}`
                  : '请选择一张候选图'}
              </strong>
              <span>
                {compareSelectedCandidate
                  ? `${statusLabel(compareSelectedCandidate.status)}，可直接进行人工采纳或丢弃`
                  : '先在上方图片面板中点击“选中此图”'}
              </span>
            </div>
            {compareSelectedCandidate ? (
              <CandidateActionButtons
                candidate={compareSelectedCandidate}
                workingId={workingId}
                disabled={clearing}
                onAdopt={() =>
                  execute(
                    compareSelectedCandidate.id,
                    () => adoptPresetAsset(compareSelectedCandidate.id),
                    '候选已采纳',
                  )
                }
                onDiscard={() =>
                  execute(
                    compareSelectedCandidate.id,
                    () => discardPresetAsset(compareSelectedCandidate.id),
                    '候选已丢弃',
                  )
                }
              />
            ) : null}
          </div>
        }
        onCancel={() => setCompareOpen(false)}
      >
        <div className="preset-asset-compare-modal-body">
          <div className="preset-asset-compare-modal-toolbar">
            <div>
              <div className="preset-asset-compare-modal-title">共享视图</div>
              <div className="preset-asset-compare-modal-hint">
                拖拽任意图片可同步移动，缩放比例同步应用到全部候选。
              </div>
            </div>
            <Space wrap>
              <Tooltip title="缩小">
                <Button
                  aria-label="缩小多图对比"
                  icon={<ZoomOutOutlined aria-hidden="true" />}
                  disabled={compareZoom <= MIN_COMPARE_ZOOM}
                  onClick={() =>
                    updateCompareZoom(compareZoom - COMPARE_ZOOM_STEP)
                  }
                />
              </Tooltip>
              <span className="preset-asset-compare-zoom-value">
                {Math.round(compareZoom * 100)}%
              </span>
              <Tooltip title="放大">
                <Button
                  aria-label="放大多图对比"
                  icon={<ZoomInOutlined aria-hidden="true" />}
                  disabled={compareZoom >= MAX_COMPARE_ZOOM}
                  onClick={() =>
                    updateCompareZoom(compareZoom + COMPARE_ZOOM_STEP)
                  }
                />
              </Tooltip>
              <Button
                icon={<CompressOutlined aria-hidden="true" />}
                onClick={resetCompareView}
              >
                重置视图
              </Button>
              <Button onClick={() => setCompareOpen(false)}>关闭</Button>
            </Space>
          </div>

          <div className="preset-asset-compare-quick-select">
            <span className="preset-asset-compare-quick-label">快捷选择</span>
            <Space size={[6, 6]} wrap>
              {candidates.map((candidate) => {
                const selected = compareIdSet.has(candidate.id);
                const hidden = hiddenIds.has(candidate.id);
                return (
                  <Tooltip
                    title={quickSelectButtonLabel(candidate.id)}
                    key={candidate.id}
                  >
                    <Button
                      size="small"
                      type={selected ? 'primary' : 'default'}
                      aria-label={quickSelectButtonLabel(candidate.id)}
                      disabled={selected && !hidden}
                      onClick={() => quickSelectCandidate(candidate.id)}
                    >
                      #{candidate.id}
                    </Button>
                  </Tooltip>
                );
              })}
            </Space>
          </div>

          {hiddenIds.size > 0 ? (
            <div className="preset-asset-compare-hidden">
              <span>已隐藏</span>
              <Space size={[6, 6]} wrap>
                {compareCandidates
                  .filter((candidate) => hiddenIds.has(candidate.id))
                  .map((candidate) => (
                    <Button
                      size="small"
                      icon={<EyeOutlined aria-hidden="true" />}
                      aria-label={`恢复候选 ${candidate.id}`}
                      key={candidate.id}
                      onClick={() => toggleHidden(candidate.id)}
                    >
                      恢复 #{candidate.id}
                    </Button>
                  ))}
              </Space>
            </div>
          ) : null}

          <div
            className={`preset-asset-compare-grid preset-asset-compare-grid-${visibleCompareCandidates.length}`}
          >
            {visibleCompareCandidates.map((candidate) => {
              const preview =
                candidate.original_url ||
                candidate.preview_url ||
                candidate.thumbnail_url;
              const pinned = pinnedIds.has(candidate.id);
              const selected = compareSelectedId === candidate.id;
              return (
                <article
                  className={`preset-asset-compare-panel${
                    selected ? ' preset-asset-compare-panel-selected' : ''
                  }`}
                  aria-label={`候选对比面板 ${candidate.id}`}
                  data-preset-candidate-id={candidate.id}
                  key={candidate.id}
                  onClick={(event) =>
                    handleComparePanelClick(event, candidate.id)
                  }
                >
                  <div className="preset-asset-compare-panel-heading">
                    <Space size={4} wrap>
                      <Tag>#{candidate.id}</Tag>
                      <Tag color={STATUS_COLORS[candidate.status] || 'default'}>
                        {statusLabel(candidate.status)}
                      </Tag>
                      {pinned ? <Tag color="gold">已固定</Tag> : null}
                    </Space>
                    <Space
                      size={4}
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Button
                        size="small"
                        type={selected ? 'primary' : 'default'}
                        aria-pressed={selected}
                        aria-label={
                          selected
                            ? `已选择对比候选 ${candidate.id}`
                            : `选择对比候选 ${candidate.id}`
                        }
                        icon={<CheckOutlined aria-hidden="true" />}
                        onClick={(event) => {
                          event.stopPropagation();
                          selectCompareCandidate(candidate.id);
                        }}
                      >
                        {selected ? '已选择' : '选中此图'}
                      </Button>
                      <Tooltip title={pinned ? '取消固定' : '固定，快捷选择不替换'}>
                        <Button
                          size="small"
                          type={pinned ? 'primary' : 'default'}
                          aria-label={
                            pinned
                              ? `取消固定候选 ${candidate.id}`
                              : `固定候选 ${candidate.id}`
                          }
                          icon={
                            pinned ? (
                              <PushpinFilled aria-hidden="true" />
                            ) : (
                              <PushpinOutlined aria-hidden="true" />
                            )
                          }
                          onClick={(event) => {
                            event.stopPropagation();
                            togglePinned(candidate.id);
                          }}
                        />
                      </Tooltip>
                      <Tooltip title="隐藏，快捷选择仍可替换非固定项">
                        <Button
                          size="small"
                          aria-label={`隐藏候选 ${candidate.id}`}
                          icon={<EyeInvisibleOutlined aria-hidden="true" />}
                          onClick={(event) => {
                            event.stopPropagation();
                            toggleHidden(candidate.id);
                          }}
                        />
                      </Tooltip>
                      <Button
                        size="small"
                        aria-label={`查看对比候选 ${candidate.id} 详情`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setCompareOpen(false);
                          setSelectedCandidateId(candidate.id);
                        }}
                      >
                        详情
                      </Button>
                    </Space>
                  </div>
                  <div
                    className="preset-asset-compare-viewport"
                    onPointerDown={startCompareDrag}
                    onPointerMove={moveCompareDrag}
                    onPointerUp={endCompareDrag}
                    onPointerCancel={endCompareDrag}
                  >
                    {preview ? (
                      <div
                        className="preset-asset-compare-canvas"
                        style={{
                          transform: `translate(${comparePan.x}px, ${comparePan.y}px) scale(${compareZoom})`,
                        }}
                      >
                        <Image
                          src={preview}
                          alt={`对比候选 ${candidate.id}`}
                          preview={false}
                          draggable={false}
                          width="100%"
                          height="100%"
                          style={{ objectFit: 'contain' }}
                        />
                      </div>
                    ) : (
                      <div className="preset-asset-candidate-empty">无预览</div>
                    )}
                  </div>
                  <div className="preset-asset-compare-panel-meta">
                    <span>{formatSize(candidate)}</span>
                    <span>Seed {candidate.seed ?? '-'}</span>
                    <span>{candidate.model || '未记录模型'}</span>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </Modal>
      <Modal
        className="preset-asset-candidate-modal"
        title={selectedCandidate ? `候选图 #${selectedCandidate.id}` : '候选图'}
        open={Boolean(selectedCandidate)}
        width={1080}
        onCancel={() => setSelectedCandidateId(null)}
        footer={
          selectedCandidate ? (
            <div className="preset-asset-candidate-modal-footer">
              <Space wrap>
                <Button
                  icon={<LeftOutlined aria-hidden="true" />}
                  disabled={selectedIndex <= 0}
                  onClick={() => moveSelection(-1)}
                >
                  上一张
                </Button>
                <span className="preset-asset-candidate-modal-index">
                  {selectedIndex + 1} / {candidates.length}
                </span>
                <Button
                  icon={<RightOutlined aria-hidden="true" />}
                  disabled={selectedIndex >= candidates.length - 1}
                  onClick={() => moveSelection(1)}
                >
                  下一张
                </Button>
              </Space>
              <Space wrap>
                <Button onClick={() => setSelectedCandidateId(null)}>关闭</Button>
                <CandidateActionButtons
                  candidate={selectedCandidate}
                  workingId={workingId}
                  disabled={clearing}
                  onAdopt={() =>
                    execute(
                      selectedCandidate.id,
                      () => adoptPresetAsset(selectedCandidate.id),
                      '候选已采纳',
                      true,
                    )
                  }
                  onDiscard={() =>
                    execute(
                      selectedCandidate.id,
                      () => discardPresetAsset(selectedCandidate.id),
                      '候选已丢弃',
                      true,
                    )
                  }
                />
              </Space>
            </div>
          ) : null
        }
      >
        {selectedCandidate ? (
          <div className="preset-asset-candidate-modal-layout">
            <div className="preset-asset-candidate-modal-preview">
              {selectedCandidate.thumbnail_url ||
              selectedCandidate.preview_url ||
              selectedCandidate.original_url ? (
                <Image
                  src={
                    selectedCandidate.original_url ||
                    selectedCandidate.preview_url ||
                    selectedCandidate.thumbnail_url ||
                    ''
                  }
                  alt={`候选 ${selectedCandidate.id}`}
                  width="100%"
                  preview={false}
                />
              ) : (
                <div className="preset-asset-candidate-empty">无预览</div>
              )}
            </div>
            <div className="preset-asset-candidate-modal-details">
              <Space size={4} wrap>
                <Tag
                  color={
                    selectedCandidate.generation_mode === 'ai' ? 'purple' : 'cyan'
                  }
                >
                  {selectedCandidate.generation_mode === 'ai' ? 'AI' : '裁剪'}
                </Tag>
                <Tag color={STATUS_COLORS[selectedCandidate.status] || 'default'}>
                  {statusLabel(selectedCandidate.status)}
                </Tag>
                <Tag>#{selectedCandidate.id}</Tag>
              </Space>
              <Descriptions
                size="small"
                column={1}
                colon={false}
                items={[
                  {
                    key: 'size',
                    label: '输出尺寸',
                    children: formatSize(selectedCandidate),
                  },
                  {
                    key: 'generation-size',
                    label: '生成尺寸',
                    children:
                      selectedCandidate.generation_width &&
                      selectedCandidate.generation_height
                        ? `${selectedCandidate.generation_width}×${selectedCandidate.generation_height}`
                        : '-',
                  },
                  {
                    key: 'seed',
                    label: 'Seed',
                    children: selectedCandidate.seed ?? '-',
                  },
                  {
                    key: 'model',
                    label: '模型',
                    children: selectedCandidate.model || '-',
                  },
                  {
                    key: 'loras',
                    label: 'LoRA',
                    children: selectedCandidate.loras?.join(', ') || '-',
                  },
                  {
                    key: 'template',
                    label: '模板版本',
                    children: selectedCandidate.template_version || '-',
                  },
                  {
                    key: 'created',
                    label: '创建时间',
                    children: selectedCandidate.created_at || '-',
                  },
                ]}
              />
              <Collapse
                ghost
                size="small"
                items={[
                  {
                    key: 'parameters',
                    label: '参数详情',
                    children: (
                      <Descriptions
                        size="small"
                        column={1}
                        colon={false}
                        items={[
                          {
                            key: 'crop',
                            label: '裁剪',
                            children: (
                              <pre className="preset-asset-candidate-json">
                                {formatParams(selectedCandidate.crop)}
                              </pre>
                            ),
                          },
                          {
                            key: 'params',
                            label: '参数',
                            children: (
                              <pre className="preset-asset-candidate-json">
                                {formatParams(selectedCandidate.params)}
                              </pre>
                            ),
                          },
                        ]}
                      />
                    ),
                  },
                ]}
              />
              {selectedCandidate.prompt_positive ? (
                <div className="preset-asset-candidate-prompt-block">
                  <div className="preset-asset-candidate-prompt-label">正向提示词</div>
                  <div className="preset-asset-candidate-prompt-value">
                    {selectedCandidate.prompt_positive}
                  </div>
                </div>
              ) : null}
              {selectedCandidate.prompt_negative ? (
                <div className="preset-asset-candidate-prompt-block">
                  <div className="preset-asset-candidate-prompt-label">负向提示词</div>
                  <div className="preset-asset-candidate-prompt-value">
                    {selectedCandidate.prompt_negative}
                  </div>
                </div>
              ) : null}
              {selectedCandidate.error ? (
                <div className="preset-asset-candidate-error">
                  {selectedCandidate.error}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
