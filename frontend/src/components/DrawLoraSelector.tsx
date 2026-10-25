import {
  DeleteOutlined,
  DownOutlined,
  ReloadOutlined,
  SearchOutlined,
  StarOutlined,
  UpOutlined,
} from '@ant-design/icons';
import {
  Button,
  Checkbox,
  Dropdown,
  Input,
  Popconfirm,
  Select,
  Slider,
  Space,
  Switch,
  Tag,
  Tooltip,
} from 'antd';
import type { MenuProps } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { LoraItem } from '../api';
import {
  filterDrawLoraItems,
  loadDrawLoraSelectorState,
  saveDrawLoraSelectorState,
  type DrawLoraPurposeFilter,
} from '../drawLoraSelectorState';

interface DrawLoraSelectorProps {
  items: LoraItem[];
  selected: string[];
  strengths: Record<string, { model: number; clip: number }>;
  defaults: {
    model: number;
    clip: number;
    min: number;
    max: number;
    step: number;
  };
  loading: boolean;
  comboMenuItems: MenuProps['items'];
  onComboMenu: MenuProps['onClick'];
  onToggle: (item: LoraItem, checked: boolean) => void;
  onRemove: (name: string) => void;
  onClear: () => void;
  onStrengthChange: (name: string, key: 'model' | 'clip', value: number) => void;
  onRefresh: () => void;
  onDelete: (item: LoraItem) => void;
}

function formatStrength(value: number): string {
  return String(Number(value.toFixed(3)));
}

function purposeLabel(purpose: LoraItem['purpose']): string {
  if (purpose === 'drawing') return '绘画';
  if (purpose === 'video') return '视频';
  return '用途未知';
}

export default function DrawLoraSelector({
  items,
  selected,
  strengths,
  defaults,
  loading,
  comboMenuItems,
  onComboMenu,
  onToggle,
  onRemove,
  onClear,
  onStrengthChange,
  onRefresh,
  onDelete,
}: DrawLoraSelectorProps) {
  const [state, setState] = useState(loadDrawLoraSelectorState);
  const rootRef = useRef<HTMLElement | null>(null);
  const filteredItems = useMemo(() => filterDrawLoraItems(items, state), [items, state]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const itemsByName = useMemo(
    () => new Map(items.map((item) => [item.name, item])),
    [items],
  );
  const drawingItemCount = items.filter((item) => item.purpose !== 'video').length;

  useEffect(() => {
    saveDrawLoraSelectorState(state);
  }, [state]);

  useEffect(() => {
    if (!state.expanded) return;
    const node = rootRef.current;
    if (!node || typeof node.scrollIntoView !== 'function') return;
    node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [state.expanded]);

  const strengthFor = (name: string) =>
    strengths[name] || { model: defaults.model, clip: defaults.clip };

  return (
    <section
      ref={rootRef}
      className={`lora-selector${state.expanded ? ' is-expanded' : ''}`}
      aria-label="LoRA 选择器"
    >
      <div className="lora-toolbar">
        <div className="lora-title-block">
          <span className="lora-title-mark" aria-hidden="true">
            <StarOutlined />
          </span>
          <div>
            <strong>LoRA 资源台</strong>
            <span>
              {selected.length
                ? `${selected.length} 个模型已加入当前组合`
                : '按用途筛选，集中管理模型与权重'}
            </span>
          </div>
        </div>
        <Space size={4} wrap className="lora-toolbar-actions">
          <Dropdown
            menu={{ items: comboMenuItems, onClick: onComboMenu }}
            trigger={['click']}
          >
            <Button size="small">
              常用搭配
            </Button>
          </Dropdown>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={onRefresh}
          >
            刷新
          </Button>
          <Button
            size="small"
            type="text"
            icon={state.expanded ? <UpOutlined /> : <DownOutlined />}
            onClick={() =>
              setState((current) => ({ ...current, expanded: !current.expanded }))
            }
          >
            {state.expanded ? '收起' : '选择 LoRA'}
          </Button>
        </Space>
      </div>

      {!state.expanded ? (
        <div className="lora-selector-summary" aria-live="polite">
          {selected.length === 0 ? (
            <span className="lora-empty-summary">还没有选择 LoRA</span>
          ) : (
            selected.map((name) => {
              const strength = strengthFor(name);
              const label = `${name} · 模型 ${formatStrength(strength.model)} / CLIP ${formatStrength(strength.clip)}`;
              return (
                <Tooltip key={name} title={`点击展开调整：${label}`}>
                  <Tag
                    className="lora-summary-tag"
                    closable
                    onClick={() =>
                      setState((current) => ({ ...current, expanded: true }))
                    }
                    onClose={(event) => {
                      event.preventDefault();
                      onRemove(name);
                    }}
                  >
                    {label}
                  </Tag>
                </Tooltip>
              );
            })
          )}
        </div>
      ) : null}

      {state.expanded ? (
        <div className="lora-inspector">
          <section className="lora-selected-panel" aria-label="已选 LoRA">
            <div className="lora-panel-heading">
              <div>
                <span className="lora-panel-kicker">已选组合</span>
                <strong>{selected.length ? `${selected.length} 个 LoRA` : '尚未选择'}</strong>
              </div>
              <Button
                type="text"
                size="small"
                disabled={!selected.length}
                onClick={onClear}
              >
                清空
              </Button>
            </div>
            {selected.length === 0 ? (
              <div className="lora-panel-empty">
                从下方资源库选择模型，权重会集中显示在这里。
              </div>
            ) : (
              <div className="lora-selected-list">
                {selected.map((name, index) => {
                  const item = itemsByName.get(name);
                  const strength = strengthFor(name);
                  return (
                    <article className="lora-selected-item" key={name}>
                      <div className="lora-selected-heading">
                        <span className="lora-selected-index">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <div className="lora-selected-copy">
                          <Tooltip title={name}>
                            <strong>{name}</strong>
                          </Tooltip>
                          <span>
                            {item ? purposeLabel(item.purpose) : '历史组合'}
                            {item ? ` · ${item.size_mb}MB` : ''}
                          </span>
                        </div>
                        <Tooltip title="从当前组合移除">
                          <Button
                            type="text"
                            size="small"
                            aria-label={`移除 ${name}`}
                            onClick={() => onRemove(name)}
                          >
                            ×
                          </Button>
                        </Tooltip>
                      </div>
                      <div className="lora-strength-inline">
                        <Tooltip
                          title={`LoRA 对模型主干的影响强度，默认 ${defaults.model}。`}
                        >
                          <span>模型</span>
                        </Tooltip>
                        <Slider
                          min={defaults.min}
                          max={defaults.max}
                          step={defaults.step}
                          value={strength.model}
                          tooltip={{ formatter: (value) => formatStrength(value ?? 0) }}
                          onChange={(value) => onStrengthChange(name, 'model', value)}
                        />
                        <output>{formatStrength(strength.model)}</output>
                      </div>
                      <div className="lora-strength-inline">
                        <Tooltip
                          title={`LoRA 对文本编码器的影响强度，默认 ${defaults.clip}。`}
                        >
                          <span>CLIP</span>
                        </Tooltip>
                        <Slider
                          min={defaults.min}
                          max={defaults.max}
                          step={defaults.step}
                          value={strength.clip}
                          tooltip={{ formatter: (value) => formatStrength(value ?? 0) }}
                          onChange={(value) => onStrengthChange(name, 'clip', value)}
                        />
                        <output>{formatStrength(strength.clip)}</output>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="lora-browser" aria-label="LoRA 资源库">
            <div className="lora-panel-heading">
              <div>
                <span className="lora-panel-kicker">资源库</span>
                <strong>选择模型</strong>
              </div>
              <Tag className="lora-result-count">
                {filteredItems.length} / {drawingItemCount}
              </Tag>
            </div>
            <div className="lora-selector-controls">
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="搜索 LoRA"
                value={state.search}
                onChange={(event) =>
                  setState((current) => ({ ...current, search: event.target.value }))
                }
              />
              <div className="lora-filter-row">
                <Select
                  aria-label="LoRA 用途"
                  value={state.purpose}
                  options={[
                    { label: '全部用途', value: 'all' },
                    { label: '绘画', value: 'drawing' },
                    { label: '未分类', value: 'unknown' },
                  ]}
                  onChange={(purpose: DrawLoraPurposeFilter) =>
                    setState((current) => ({ ...current, purpose }))
                  }
                />
                <label className="lora-compatible-toggle">
                  <Switch
                    size="small"
                    checked={state.compatibleOnly}
                    onChange={(compatibleOnly) =>
                      setState((current) => ({ ...current, compatibleOnly }))
                    }
                  />
                  <span>仅兼容</span>
                </label>
                <Button
                  size="small"
                  type="text"
                  onClick={() =>
                    setState((current) => ({
                      ...current,
                      search: '',
                      purpose: 'all',
                      compatibleOnly: true,
                    }))
                  }
                >
                  重置
                </Button>
              </div>
            </div>

            <div className="lora-list" aria-live="polite">
              {filteredItems.length === 0 ? (
                <div className="lora-panel-empty">没有符合筛选条件的 LoRA</div>
              ) : null}
              {filteredItems.map((item) => {
                const checked = selectedSet.has(item.name);
                const unavailable = item.compatible === false;
                return (
                  <div
                    className={`lora-item${checked ? ' selected' : ''}${unavailable ? ' unavailable' : ''}`}
                    key={item.name}
                  >
                    <div className="lora-selector-item-head">
                      <Checkbox
                        className="lora-pick"
                        checked={checked}
                        disabled={unavailable}
                        onChange={(event) => onToggle(item, event.target.checked)}
                      >
                        <span className="lora-item-copy">
                          <Tooltip title={item.name}>
                            <strong>{item.name}</strong>
                          </Tooltip>
                          <span>
                            {item.size_mb}MB · {purposeLabel(item.purpose)}
                            {item.usage_count ? ` · 使用 ${item.usage_count} 次` : ''}
                          </span>
                        </span>
                      </Checkbox>
                      <div className="lora-item-status">
                        {item.incompatible_reason ? (
                          <Tooltip title={item.incompatible_reason}>
                            <Tag color="red">需切换底模</Tag>
                          </Tooltip>
                        ) : item.protected ? (
                          <Tag color="blue">已保护</Tag>
                        ) : null}
                        <Popconfirm
                          title={`确认删除 ${item.name}？`}
                          description={
                            item.usage_count
                              ? `该 LoRA 已使用 ${item.usage_count} 次，删除后历史记录中的组合将无法再次加载。`
                              : '删除文件后不可恢复，历史记录中的组合将无法再次加载。'
                          }
                          onConfirm={() => onDelete(item)}
                          okButtonProps={{ danger: true }}
                        >
                          <Tooltip
                            title={
                              item.protected
                                ? '该 LoRA 已保护，删除前请先取消保护'
                                : '删除该 LoRA 文件'
                            }
                          >
                            <Button
                              size="small"
                              type="text"
                              danger
                              aria-label={`删除 ${item.name}`}
                              icon={<DeleteOutlined />}
                              disabled={item.protected}
                            />
                          </Tooltip>
                        </Popconfirm>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
