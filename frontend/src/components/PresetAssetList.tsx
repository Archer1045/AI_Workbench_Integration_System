import {
  AimOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
} from '@ant-design/icons';
import {
  Button,
  Checkbox,
  Image,
  List,
  Pagination,
  Space,
  Spin,
  Tag,
  Tooltip,
} from 'antd';
import { useEffect, useRef } from 'react';
import type { PresetAssetCatalogItem } from '../api';
import {
  presetAssetStore,
  type PresetAssetSelection,
} from '../stores/presetAssetStore';

function itemState(item: PresetAssetCatalogItem): {
  label: string;
  tone: 'ready' | 'running' | 'failed' | 'candidate' | 'ready-image' | 'empty';
} {
  if (item.ready_count > 0) {
    return { label: `待验收 ${item.ready_count}`, tone: 'ready' };
  }
  if (item.running_count > 0) {
    return { label: `生成中 ${item.running_count}`, tone: 'running' };
  }
  if (item.failed_count > 0) {
    return { label: `失败 ${item.failed_count}`, tone: 'failed' };
  }
  if (item.candidate_count > 0) {
    return { label: `候选 ${item.candidate_count}`, tone: 'candidate' };
  }
  if (item.has_image) {
    return { label: '正式图', tone: 'ready-image' };
  }
  return { label: '未生成', tone: 'empty' };
}

function itemNextAction(item: PresetAssetCatalogItem): string {
  const tone = itemState(item).tone;
  if (tone === 'ready') return '查看并人工采纳';
  if (tone === 'running') return '查看生成进度';
  if (tone === 'failed') return '查看失败结果';
  if (tone === 'candidate') return '查看候选';
  if (tone === 'ready-image') return '查看正式图';
  return '单独生成';
}

export default function PresetAssetList({
  items,
  loading,
  filterKey,
  page,
  pageSize,
  total,
  emptyText,
  onSelect,
  onPageChange,
  scrollTop,
  onScrollTopChange,
  selectable = false,
  selectedKeys,
  selectionLimit,
  onToggle,
  onMoveSelection,
  onRevealSelection,
  revealToken = 0,
}: {
  items: PresetAssetCatalogItem[];
  loading: boolean;
  filterKey: string;
  page: number;
  pageSize: number;
  total: number;
  emptyText: string;
  onSelect: (selection: PresetAssetSelection) => void;
  onPageChange: (page: number) => void;
  scrollTop: number;
  onScrollTopChange: (scrollTop: number) => void;
  selectable?: boolean;
  selectedKeys?: Set<string>;
  selectionLimit?: number;
  onToggle?: (item: PresetAssetCatalogItem, checked: boolean) => void;
  onMoveSelection?: (offset: number) => void;
  onRevealSelection?: () => void;
  revealToken?: number;
}) {
  const { selection } = presetAssetStore;
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const restoredKeyRef = useRef('');
  const restorationKey = `${filterKey}:${page}`;
  const selectionKey = selection
    ? `${selection.presetType}:${selection.presetId}`
    : '';
  const activeIndex = selection
    ? items.findIndex(
        (item) =>
          item.preset_type === selection.presetType &&
          item.preset_id === selection.presetId,
      )
    : -1;
  const activeItem = activeIndex >= 0 ? items[activeIndex] : null;
  const pageStatus = {
    withImage: items.filter((item) => item.has_image).length,
    ready: items.filter((item) => item.ready_count > 0).length,
    running: items.filter((item) => item.running_count > 0).length,
    failed: items.filter((item) => item.failed_count > 0).length,
    ungenerated: items.filter(
      (item) =>
        !item.has_image &&
        item.candidate_count === 0 &&
        item.running_count === 0,
    ).length,
  };

  useEffect(() => {
    const container = scrollRef.current;
    if (
      !container ||
      loading ||
      restoredKeyRef.current === restorationKey
    ) {
      return;
    }
    container.scrollTop = scrollTop;
    restoredKeyRef.current = restorationKey;
  }, [loading, restorationKey, scrollTop]);

  useEffect(() => {
    if (!revealToken || !selectionKey || loading) return undefined;
    const frame = globalThis.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (!container) return;
      const target = Array.from(
        container.querySelectorAll<HTMLElement>('[data-preset-key]'),
      ).find((element) => element.dataset.presetKey === selectionKey);
      if (!target) return;
      const containerRect = container.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      if (targetRect.top < containerRect.top) {
        container.scrollTop -= containerRect.top - targetRect.top;
      } else if (targetRect.bottom > containerRect.bottom) {
        container.scrollTop += targetRect.bottom - containerRect.bottom;
      }
      onScrollTopChange(container.scrollTop);
    });
    return () => globalThis.cancelAnimationFrame(frame);
  }, [loading, onScrollTopChange, revealToken, selectionKey]);

  return (
    <div className="preset-asset-list">
      <div className="preset-asset-list-current">
        <div className="preset-asset-list-current-copy">
          <span>
            {activeIndex >= 0
              ? `当前预设 · 本页 ${activeIndex + 1}/${items.length}`
              : '当前预设'}
          </span>
          <strong title={activeItem?.label || ''}>
            {activeItem?.label || '尚未选择'}
          </strong>
        </div>
        <Space size={4}>
          <Tooltip title="上一项">
            <Button
              size="small"
              aria-label="选择上一个预设"
              icon={<ArrowUpOutlined aria-hidden="true" />}
              disabled={activeIndex <= 0}
              onClick={() => onMoveSelection?.(-1)}
            />
          </Tooltip>
          <Tooltip title="下一项">
            <Button
              size="small"
              aria-label="选择下一个预设"
              icon={<ArrowDownOutlined aria-hidden="true" />}
              disabled={activeIndex < 0 || activeIndex >= items.length - 1}
              onClick={() => onMoveSelection?.(1)}
            />
          </Tooltip>
          <Tooltip title="定位当前项">
            <Button
              size="small"
              aria-label="在列表中定位当前预设"
              icon={<AimOutlined aria-hidden="true" />}
              disabled={activeIndex < 0}
              onClick={() => onRevealSelection?.()}
            />
          </Tooltip>
        </Space>
      </div>
      <div className="preset-asset-list-summary">
        <span>本页 {items.length} 项</span>
        <span>共 {total} 项</span>
      </div>
      <div
        aria-label="本页资源状态汇总"
        className="preset-asset-list-status-summary"
      >
        <span>正式图 {pageStatus.withImage}</span>
        <span>待验收 {pageStatus.ready}</span>
        <span>生成中 {pageStatus.running}</span>
        <span>失败 {pageStatus.failed}</span>
        <span>未生成 {pageStatus.ungenerated}</span>
      </div>
      <Spin spinning={loading}>
        <div
          ref={scrollRef}
          className="preset-asset-list-scroll"
          onScroll={(event) =>
            onScrollTopChange(event.currentTarget.scrollTop)
          }
        >
          <List
            size="small"
            dataSource={items}
            locale={{ emptyText }}
            renderItem={(item) => {
              const itemKey = `${item.preset_type}:${item.preset_id}`;
              const selected = Boolean(selectedKeys?.has(itemKey));
              const active =
                selection?.presetType === item.preset_type &&
                selection.presetId === item.preset_id;
              const version = item.active_version
                ? `正式 v${item.active_version.version}`
                : '无正式图';
              const state = itemState(item);
              return (
                <List.Item
                  className={
                    active
                      ? 'preset-asset-list-item active'
                      : 'preset-asset-list-item'
                  }
                  data-preset-key={itemKey}
                  {...(selectable ? { selectable: false } : {})}
                  onClick={() => {
                    if (selectable) {
                      onToggle?.(item, !selected);
                      return;
                    }
                    onSelect({
                      presetType: item.preset_type,
                      presetId: item.preset_id,
                      label: item.label,
                    });
                  }}
                >
                  {selectable ? (
                    <Checkbox
                      aria-label={`选择 ${item.label}`}
                      checked={selected}
                      disabled={
                        !selected &&
                        typeof selectionLimit === 'number' &&
                        (selectedKeys?.size || 0) >= selectionLimit
                      }
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => onToggle?.(item, event.target.checked)}
                    />
                  ) : null}
                  {item.image ? (
                    <Image
                      src={item.image}
                      alt={item.label}
                      width={42}
                      height={42}
                      style={{ objectFit: 'cover', borderRadius: 4 }}
                      preview={false}
                    />
                  ) : (
                    <div className="preset-asset-list-placeholder">无图</div>
                  )}
                  <div className="preset-asset-list-copy">
                    <div className="preset-asset-list-name">
                      <span title={item.label}>{item.label}</span>
                      {item.rating === 'R18' ? (
                        <Tag color="red">R18</Tag>
                      ) : null}
                    </div>
                    <div className="preset-asset-list-meta">
                      <span className={item.has_image ? 'ok' : 'muted'}>
                        {version}
                      </span>
                      <span
                        className={`preset-asset-list-state ${state.tone}`}
                        aria-label={`${item.label} 下一步：${itemNextAction(item)}`}
                      >
                        {state.label}
                      </span>
                    </div>
                    <div className="help preset-asset-list-path">
                      {item.source ? '有源图' : '无源图'} ·{' '}
                      {item.category_group}/{item.subcategory} · {item.preset_id}
                    </div>
                  </div>
                </List.Item>
              );
            }}
          />
        </div>
      </Spin>
      {total > pageSize ? (
        <div className="preset-asset-list-pagination">
          <Pagination
            size="small"
            current={page}
            pageSize={pageSize}
            total={total}
            showSizeChanger={false}
            onChange={onPageChange}
          />
        </div>
      ) : null}
    </div>
  );
}
