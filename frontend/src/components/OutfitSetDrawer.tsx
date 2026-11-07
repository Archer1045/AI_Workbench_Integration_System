import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CopyOutlined,
  DeleteOutlined,
  HistoryOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Image,
  Input,
  List,
  message,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  api,
  type ClothingPreset,
  type OutfitItemDraft,
  type OutfitSetCatalog,
  type OutfitSetDefinition,
  type OutfitSetPreset,
  type OutfitSlot,
  type OutfitSetVersionCatalog,
} from '../api';
import {
  defaultOutfitCovers,
  OUTFIT_SLOTS,
  outfitDraftItem,
} from '../outfitSets';
import { isPresetHidden } from '../presetComposition';
import { settingsStore } from '../stores/settings';

type OutfitApplyScope = 'current' | 'all';

interface OutfitDraft {
  preset_id?: string;
  version?: number;
  source?: string;
  name: string;
  description: string;
  category: string;
  items: OutfitItemDraft[];
}

function errorDetail(error: unknown): string {
  return (
    (error as { response?: { data?: { detail?: string } } }).response?.data
      ?.detail || '请求失败'
  );
}

function draftFromPreset(preset: OutfitSetPreset): OutfitDraft {
  return {
    preset_id: preset.preset_id,
    version: preset.version,
    source: preset.source,
    name: preset.name,
    description: preset.description,
    category: preset.category,
    items: preset.items.map((item) => ({
      clothing_id: item.clothing_id,
      slot: item.slot,
      colors: { ...item.colors },
      layer_state: item.layer_state,
      order: item.order,
      enabled: item.enabled,
      covers: [...item.covers],
    })),
  };
}

function composePayload(draft: OutfitDraft) {
  return {
    name: draft.name.trim() || '未命名套装',
    description: draft.description,
    category: draft.category || '用户套装',
    gender_scope: '女',
    items: draft.items.map((item, index) => ({
      ...item,
      order: index,
    })),
  };
}

export default function OutfitSetDrawer({
  open,
  onClose,
  onApply,
  onManagePreview,
}: {
  open: boolean;
  onClose: () => void;
  onApply: (
    outfit: OutfitSetDefinition & {
      preset_id?: string;
      version?: number;
      content_hash: string;
    },
    scope: OutfitApplyScope,
  ) => boolean;
  onManagePreview?: (selection: {
    presetType: 'outfit';
    presetId: string;
    label: string;
  }) => void;
}) {
  const { restrictionEnabled } = settingsStore;
  const [outfits, setOutfits] = useState<OutfitSetPreset[]>([]);
  const [clothing, setClothing] = useState<ClothingPreset[]>([]);
  const [loading, setLoading] = useState(false);
  const [composing, setComposing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState<OutfitDraft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [outfitKeyword, setOutfitKeyword] = useState('');
  const [category, setCategory] = useState('');
  const [pickedClothingId, setPickedClothingId] = useState('');
  const [validation, setValidation] = useState<
    (OutfitSetDefinition & {
      content_hash: string;
      warnings: string[];
    }) | null
  >(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [applyScope, setApplyScope] = useState<OutfitApplyScope>('current');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [versions, setVersions] = useState<OutfitSetPreset[]>([]);
  const [rollingBackVersion, setRollingBackVersion] = useState(0);

  const clothingMap = useMemo(
    () => new Map(clothing.map((item) => [item.id, item])),
    [clothing],
  );
  const selected = outfits.find((item) => item.preset_id === selectedId);
  const categories = Array.from(
    new Set(clothing.map((item) => item.category).filter(Boolean)),
  );
  const filteredClothing = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return clothing
      .filter((item) => !isPresetHidden(item, restrictionEnabled))
      .filter((item) => !category || item.category === category)
      .filter((item) => {
        if (!query) return true;
        return (
          `${item.label} ${item.translation} ${item.category} ${item.part} ` +
          `${(item.aliases || []).join(' ')} ${item.tags.join(' ')}`
        )
          .toLowerCase()
          .includes(query);
      })
      .slice(0, 80);
  }, [category, clothing, keyword, restrictionEnabled]);
  const filteredOutfits = useMemo(() => {
    const query = outfitKeyword.trim().toLowerCase();
    if (!query) return outfits;
    return outfits.filter((item) =>
      `${item.name} ${item.description} ${item.category}`
        .toLowerCase()
        .includes(query),
    );
  }, [outfitKeyword, outfits]);

  const selectDraft = useCallback((preset: OutfitSetPreset) => {
    setSelectedId(preset.preset_id);
    setDraft(draftFromPreset(preset));
    setDirty(false);
    setValidation(null);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [outfitResult, clothingResult] = await Promise.allSettled([
        api.get<OutfitSetCatalog>('/prompt-agent/outfit-presets'),
        api.get<{ items: ClothingPreset[] }>('/prompt-agent/clothing-presets'),
      ]);
      if (outfitResult.status === 'rejected') {
        message.error(errorDetail(outfitResult.reason));
        setOutfits([]);
      } else {
        const items = outfitResult.value.data.items || [];
        setOutfits(items);
        if (draft?.preset_id) {
          const refreshed = items.find(
            (item) => item.preset_id === draft.preset_id,
          );
          if (refreshed) setDraft(draftFromPreset(refreshed));
        } else if (!draft && items[0]) {
          selectDraft(items[0]);
        }
      }
      if (clothingResult.status === 'fulfilled') {
        setClothing(clothingResult.value.data.items || []);
      } else {
        message.error(errorDetail(clothingResult.reason));
        setClothing([]);
      }
    } finally {
      setLoading(false);
    }
  }, [draft?.preset_id, selectDraft]);

  useEffect(() => {
    if (!open) return;
    void load();
    // Only refresh when the drawer opens; draft changes must not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const updateDraft = (update: (current: OutfitDraft) => OutfitDraft) => {
    setDraft((current) => (current ? update(current) : current));
    setDirty(true);
    setValidation(null);
  };

  const updateItem = (
    index: number,
    update: (item: OutfitItemDraft) => OutfitItemDraft,
  ) => {
    updateDraft((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) =>
        itemIndex === index ? update(item) : item,
      ),
    }));
  };

  const moveItem = (index: number, delta: number) => {
    updateDraft((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.items.length) return current;
      const items = [...current.items];
      const [item] = items.splice(index, 1);
      items.splice(target, 0, item);
      return {
        ...current,
        items: items.map((entry, order) => ({ ...entry, order })),
      };
    });
  };

  const removeItem = (index: number) => {
    updateDraft((current) => ({
      ...current,
      items: current.items
        .filter((_, itemIndex) => itemIndex !== index)
        .map((item, order) => ({ ...item, order })),
    }));
  };

  const addClothing = () => {
    if (!draft || !pickedClothingId) return;
    if (draft.items.some((item) => item.clothing_id === pickedClothingId)) {
      message.info('该服装已在这个套装中');
      return;
    }
    const preset = clothingMap.get(pickedClothingId);
    if (!preset) return;
    updateDraft((current) => ({
      ...current,
      items: [
        ...current.items,
        { ...outfitDraftItem(preset), order: current.items.length },
      ],
    }));
    setPickedClothingId('');
  };

  const compose = async (): Promise<
    (OutfitSetDefinition & { content_hash: string; warnings: string[] }) | null
  > => {
    if (!draft) return null;
    if (draft.items.length === 0) {
      message.warning('请先加入至少一件服装');
      return null;
    }
    setComposing(true);
    try {
      const { data } = await api.post<
        OutfitSetDefinition & {
          content_hash: string;
          warnings: string[];
        }
      >('/prompt-agent/outfit-presets/compose', composePayload(draft));
      setValidation(data);
      return data;
    } catch (error: unknown) {
      setValidation(null);
      message.error(errorDetail(error));
      return null;
    } finally {
      setComposing(false);
    }
  };

  const apply = async () => {
    const result = await compose();
    if (!result) return;
    const applied = onApply(
      {
        ...result,
        preset_id: dirty ? undefined : draft?.preset_id,
        version: dirty ? 1 : draft?.version || 1,
      },
      applyScope,
    );
    if (!applied) return;
    message.success(
      applyScope === 'current'
        ? `已把「${draft?.name}」应用到当前角色服装块`
        : `已把「${draft?.name}」应用到全部角色服装块`,
    );
    onClose();
  };

  const save = async () => {
    const name = saveName.trim();
    if (!name || !draft) {
      message.warning('请输入套装名称');
      return;
    }
    const result = await compose();
    if (!result) return;
    setSaving(true);
    try {
      const payload = {
        ...composePayload(draft),
        name,
      };
      const response =
        selected?.source === 'user' && draft.preset_id
          ? await api.put<{ item: OutfitSetPreset }>(
              `/prompt-agent/outfit-presets/${draft.preset_id}`,
              payload,
            )
          : await api.post<{ item: OutfitSetPreset }>(
              '/prompt-agent/outfit-presets',
              payload,
            );
      const saved = response.data.item;
      setOutfits((current) => [
        saved,
        ...current.filter((item) => item.preset_id !== saved.preset_id),
      ]);
      selectDraft(saved);
      setSaveOpen(false);
      setSaveName('');
      message.success(
        selected?.source === 'builtin'
          ? '已从内置套装另存为用户副本'
          : `已保存套装 v${saved.version}`,
      );
    } catch (error: unknown) {
      message.error(errorDetail(error));
    } finally {
      setSaving(false);
    }
  };

  const duplicate = async () => {
    if (!draft?.preset_id) return;
    setSaving(true);
    try {
      const { data } = await api.post<{ item: OutfitSetPreset }>(
        `/prompt-agent/outfit-presets/${draft.preset_id}/duplicate`,
        { name: `${draft.name} 副本` },
      );
      setOutfits((current) => [
        data.item,
        ...current.filter((item) => item.preset_id !== data.item.preset_id),
      ]);
      selectDraft(data.item);
      message.success('已创建用户副本');
    } catch (error: unknown) {
      message.error(errorDetail(error));
    } finally {
      setSaving(false);
    }
  };

  const removeOutfit = async () => {
    if (!selected || selected.source !== 'user') return;
    setSaving(true);
    try {
      await api.delete(`/prompt-agent/outfit-presets/${selected.preset_id}`);
      const remaining = outfits.filter(
        (item) => item.preset_id !== selected.preset_id,
      );
      setOutfits(remaining);
      if (remaining[0]) selectDraft(remaining[0]);
      else {
        setDraft(null);
        setSelectedId('');
      }
      message.success('已删除用户套装');
    } catch (error: unknown) {
      message.error(errorDetail(error));
    } finally {
      setSaving(false);
    }
  };

  const requestPreview = async () => {
    if (!selected || dirty) {
      message.warning('请先保存当前组合，再生成与该 content hash 对应的预览');
      return;
    }
    setPreviewing(true);
    try {
      const { data } = await api.post<{ job_id?: string; status?: string }>(
        `/preset-assets/presets/outfit/${selected.preset_id}/candidates/ai`,
        {
          params: {
            candidate_count: 4,
          },
        },
        {
          headers: {
            'Idempotency-Key': `outfit-preview:${selected.preset_id}:${selected.content_hash}`,
          },
        },
      );
      message.success(
        `已提交最终组合的 4 张候选图${data.job_id ? ` · ${data.job_id}` : ''}`,
      );
    } catch (error: unknown) {
      message.error(errorDetail(error));
    } finally {
      setPreviewing(false);
    }
  };

  const loadVersions = async () => {
    if (!selected) return;
    setHistoryLoading(true);
    try {
      const { data } = await api.get<OutfitSetVersionCatalog>(
        `/prompt-agent/outfit-presets/${encodeURIComponent(selected.preset_id)}/versions`,
      );
      setVersions(data.items || []);
    } catch (error: unknown) {
      setVersions([]);
      message.error(errorDetail(error));
    } finally {
      setHistoryLoading(false);
    }
  };

  const openHistory = () => {
    if (!selected || selected.source !== 'user') return;
    if (dirty) {
      message.warning('请先保存或放弃当前修改，再查看历史版本');
      return;
    }
    setHistoryOpen(true);
    void loadVersions();
  };

  const rollback = async (version: number) => {
    if (!selected) return;
    setRollingBackVersion(version);
    try {
      const { data } = await api.post<{ item: OutfitSetPreset }>(
        `/prompt-agent/outfit-presets/${encodeURIComponent(selected.preset_id)}/rollback`,
        { version },
      );
      const restored = data.item;
      setOutfits((current) => [
        restored,
        ...current.filter((item) => item.preset_id !== restored.preset_id),
      ]);
      selectDraft(restored);
      await loadVersions();
      message.success(`已从 v${version} 恢复为新的 v${restored.version}`);
    } catch (error: unknown) {
      message.error(errorDetail(error));
    } finally {
      setRollingBackVersion(0);
    }
  };

  const startNew = () => {
    setSelectedId('');
    setDraft({
      name: '新套装',
      description: '',
      category: '用户套装',
      items: [],
    });
    setDirty(true);
    setValidation(null);
  };

  const slotOptions = OUTFIT_SLOTS.map((item) => ({
    label: item.label,
    value: item.value,
  }));
  const clothingOptions = filteredClothing.map((item) => ({
    label: `${item.label} · ${item.part}`,
    value: item.id,
  }));
  const layerStates = Array.from(
    new Set(clothing.map((item) => item.layer_state).filter(Boolean)),
  );

  return (
    <>
      <Drawer
        title="服装套装"
        width={
          typeof window !== 'undefined' && window.innerWidth < 1180
            ? '100vw'
            : 1240
        }
        open={open}
        onClose={onClose}
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
              刷新
            </Button>
            <Button icon={<PlusOutlined />} onClick={startNew}>
              新建套装
            </Button>
          </Space>
        }
      >
        <div
          className="outfit-set-layout"
          style={{
            display: 'grid',
            gridTemplateColumns:
              typeof window !== 'undefined' && window.innerWidth < 1180
                ? 'minmax(0, 1fr)'
                : 'minmax(210px, 0.65fr) minmax(390px, 1.25fr) minmax(300px, 0.85fr)',
            gap: 14,
            alignItems: 'start',
          }}
        >
          <section className="panel-box outfit-set-library">
            <div className="train-section-title">套装库</div>
            <Input.Search
              allowClear
              value={outfitKeyword}
              onChange={(event) => setOutfitKeyword(event.target.value)}
              placeholder="搜索套装"
            />
            <List
              size="small"
              loading={loading}
              dataSource={filteredOutfits}
              style={{ marginTop: 8, maxHeight: 590, overflowY: 'auto' }}
              renderItem={(item) => (
                <List.Item
                  className={
                    item.preset_id === selectedId
                      ? 'outfit-set-list-item is-active'
                      : 'outfit-set-list-item'
                  }
                  onClick={() => selectDraft(item)}
                  style={{ cursor: 'pointer' }}
                >
                  <List.Item.Meta
                    title={
                      <Space size={4} wrap>
                        <span>{item.name}</span>
                        <Tag color={item.source === 'builtin' ? 'blue' : 'green'}>
                          {item.source === 'builtin' ? '内置' : '用户'}
                        </Tag>
                      </Space>
                    }
                    description={
                      <div>
                        <div>{item.items.length} 件 · v{item.version}</div>
                        <div className="help">{item.category}</div>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
            {outfits.length === 0 && !loading ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无套装；服务重启后会载入内置目录"
              />
            ) : null}
          </section>

          <section className="panel-box outfit-set-editor">
            {draft ? (
              <>
                <div className="train-section-title">
                  {draft.name}
                  {dirty ? <Tag color="orange">未保存修改</Tag> : null}
                </div>
                <div className="outfit-set-fields">
                  <label className="outfit-set-field">
                    <span>名称</span>
                    <Input
                      value={draft.name}
                      onChange={(event) =>
                        updateDraft((current) => ({
                          ...current,
                          name: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <label className="outfit-set-field">
                    <span>说明</span>
                    <Input
                      value={draft.description}
                      onChange={(event) =>
                        updateDraft((current) => ({
                          ...current,
                          description: event.target.value,
                        }))
                      }
                    />
                  </label>
                </div>

                <div className="outfit-set-add-row">
                  <Select
                    showSearch
                    allowClear
                    value={pickedClothingId || undefined}
                    placeholder="搜索服装库"
                    optionFilterProp="label"
                    options={clothingOptions}
                    onSearch={setKeyword}
                    onChange={(value) => setPickedClothingId(value || '')}
                    style={{ minWidth: 200, flex: 1 }}
                  />
                  <Select
                    allowClear
                    value={category || undefined}
                    placeholder="分类"
                    options={categories.map((value) => ({
                      label: value,
                      value,
                    }))}
                    onChange={(value) => setCategory(value || '')}
                    style={{ width: 150 }}
                  />
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    disabled={!pickedClothingId}
                    onClick={addClothing}
                  >
                    加入
                  </Button>
                </div>
                <div className="help" style={{ marginBottom: 8 }}>
                  先设置叠穿顺序；全身装会覆盖上装和下装，鞋与袜各自占用槽位。
                </div>

                <List
                  dataSource={draft.items}
                  locale={{ emptyText: '尚未加入服装' }}
                  renderItem={(item, index) => {
                    const preset = clothingMap.get(item.clothing_id);
                    return (
                      <List.Item className="outfit-set-item">
                        <div className="outfit-set-item-main">
                          {preset?.image ? (
                            <Image
                              src={preset.image}
                              width={54}
                              height={82}
                              style={{ objectFit: 'cover', borderRadius: 4 }}
                              preview={{ mask: false }}
                            />
                          ) : (
                            <div className="outfit-set-image-placeholder">
                              {index + 1}
                            </div>
                          )}
                          <div className="outfit-set-item-body">
                            <div className="outfit-set-item-title">
                              <strong>{preset?.label || item.clothing_id}</strong>
                              <Tag>{preset?.part || item.slot}</Tag>
                              <Tag color={item.enabled === false ? 'default' : 'green'}>
                                {item.enabled === false ? '停用' : `第 ${index + 1} 层`}
                              </Tag>
                            </div>
                            <div className="outfit-set-item-controls">
                              <Tooltip title="上移一层">
                                <Button
                                  size="small"
                                  icon={<ArrowUpOutlined />}
                                  disabled={index === 0}
                                  onClick={() => moveItem(index, -1)}
                                />
                              </Tooltip>
                              <Tooltip title="下移一层">
                                <Button
                                  size="small"
                                  icon={<ArrowDownOutlined />}
                                  disabled={index === draft.items.length - 1}
                                  onClick={() => moveItem(index, 1)}
                                />
                              </Tooltip>
                              <Select
                                size="small"
                                value={item.slot}
                                options={slotOptions}
                                onChange={(slot: OutfitSlot) =>
                                  updateItem(index, (current) => ({
                                    ...current,
                                    slot,
                                    covers: defaultOutfitCovers(slot, preset),
                                  }))
                                }
                                style={{ minWidth: 94 }}
                              />
                              <Select
                                size="small"
                                mode="multiple"
                                maxTagCount="responsive"
                                value={item.covers || []}
                                options={slotOptions.filter(
                                  (option) => option.value !== item.slot,
                                )}
                                placeholder="覆盖槽位"
                                onChange={(covers: OutfitSlot[]) =>
                                  updateItem(index, (current) => ({
                                    ...current,
                                    covers,
                                  }))
                                }
                                style={{ minWidth: 150, flex: 1 }}
                              />
                              <Select
                                size="small"
                                value={item.layer_state || '完整'}
                                options={layerStates.map((value) => ({
                                  label: value,
                                  value,
                                }))}
                                onChange={(layerState: string) =>
                                  updateItem(index, (current) => ({
                                    ...current,
                                    layer_state: layerState,
                                  }))
                                }
                                style={{ width: 92 }}
                              />
                              <Input
                                size="small"
                                value={item.colors?.primary || ''}
                                placeholder="主色，可留空"
                                onChange={(event) =>
                                  updateItem(index, (current) => ({
                                    ...current,
                                    colors: {
                                      ...(current.colors || {}),
                                      primary: event.target.value,
                                    },
                                  }))
                                }
                                style={{ minWidth: 110, flex: 1 }}
                              />
                              <Switch
                                size="small"
                                checked={item.enabled !== false}
                                checkedChildren="启用"
                                unCheckedChildren="停用"
                                onChange={(enabled) =>
                                  updateItem(index, (current) => ({
                                    ...current,
                                    enabled,
                                  }))
                                }
                              />
                              <Button
                                size="small"
                                type="text"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={() => removeItem(index)}
                              />
                            </div>
                            {preset ? (
                              <div className="help">
                                {preset.translation} · {preset.tags.join(', ')}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      </List.Item>
                    );
                  }}
                />
              </>
            ) : (
              <Empty description="从左侧选择套装，或新建一个套装" />
            )}
          </section>

          <section className="panel-box outfit-set-summary">
            <div className="train-section-title">检查与应用</div>
            {draft ? (
              <>
                <Space wrap style={{ marginBottom: 8 }}>
                  <Tag color="blue">{draft.items.length} 件</Tag>
                  <Tag>{draft.items.filter((item) => item.enabled !== false).length} 件启用</Tag>
                  <Tag color={selected?.source === 'builtin' ? 'purple' : 'green'}>
                    {selected?.source === 'builtin' ? '编辑将另存副本' : '用户套装'}
                  </Tag>
                </Space>
                {validation?.warnings?.map((warning) => (
                  <Alert
                    key={warning}
                    type="warning"
                    showIcon
                    message={warning}
                    style={{ marginBottom: 8 }}
                  />
                ))}
                <div className="setting-label">最终服装提示词</div>
                <Input.TextArea
                  rows={9}
                  readOnly
                  value={validation?.prompt || '点击“检查组合”验证槽位并生成最终提示词'}
                />
                <Space wrap style={{ marginTop: 8 }}>
                  <Button loading={composing} onClick={() => void compose()}>
                    检查组合
                  </Button>
                  <Button
                    icon={<SaveOutlined />}
                    onClick={() => {
                      if (!draft.name.trim()) {
                        message.warning('请先填写套装名称');
                        return;
                      }
                      setSaveName(
                        selected?.source === 'builtin'
                          ? `${draft.name} 副本`
                          : draft.name,
                      );
                      setSaveOpen(true);
                    }}
                  >
                    {selected?.source === 'builtin' ? '另存副本' : '保存套装'}
                  </Button>
                  <Button
                    icon={<CopyOutlined />}
                    disabled={!draft.preset_id}
                    loading={saving}
                    onClick={() => void duplicate()}
                  >
                    复制
                  </Button>
                  <Button
                    icon={<HistoryOutlined />}
                    disabled={selected?.source !== 'user' || dirty}
                    onClick={openHistory}
                  >
                    历史版本
                  </Button>
                  <Popconfirm
                    title="删除这个用户套装？"
                    description="历史版本和逐件快照会一并删除，但不会改动已写入提示词的角色。"
                    disabled={selected?.source !== 'user'}
                    onConfirm={() => void removeOutfit()}
                  >
                    <Button
                      danger
                      disabled={selected?.source !== 'user'}
                      loading={saving}
                    >
                      删除
                    </Button>
                  </Popconfirm>
                  <Button
                    loading={previewing}
                    disabled={!selected || dirty}
                    onClick={() => void requestPreview()}
                  >
                    生成 4 张预览
                  </Button>
                  <Button
                    disabled={!selected || dirty || !onManagePreview}
                    onClick={() => {
                      if (!selected || !onManagePreview) return;
                      onManagePreview({
                        presetType: 'outfit',
                        presetId: selected.preset_id,
                        label: selected.name,
                      });
                    }}
                  >
                    查看预览候选
                  </Button>
                </Space>
                <div className="setting-label" style={{ marginTop: 12 }}>
                  应用到角色服装块
                </div>
                <Select
                  value={applyScope}
                  options={[
                    { value: 'current', label: '当前角色' },
                    { value: 'all', label: '全部角色' },
                  ]}
                  onChange={setApplyScope}
                  style={{ width: '100%', marginBottom: 8 }}
                />
                <Button
                  block
                  type="primary"
                  loading={composing}
                  disabled={draft.items.length === 0}
                  onClick={() => void apply()}
                >
                  校验并应用
                </Button>
                <div className="help" style={{ marginTop: 8 }}>
                  套装只替换目标角色的服装块，不影响外貌、动作、表情、场景和道具。
                  组合变化后，基于旧 content hash 的预览会失效；预览候选必须由用户在预设工坊中手动采纳。
                </div>
              </>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未选择套装" />
            )}
          </section>
        </div>
      </Drawer>
      <Modal
        title={selected?.source === 'builtin' ? '另存用户副本' : '保存服装套装'}
        open={saveOpen}
        confirmLoading={saving}
        onOk={() => void save()}
        onCancel={() => setSaveOpen(false)}
        okText={selected?.source === 'builtin' ? '保存副本' : '保存'}
      >
        <Input
          value={saveName}
          onChange={(event) => setSaveName(event.target.value)}
          placeholder="套装名称"
          onPressEnter={() => void save()}
        />
      </Modal>
      <Modal
        title={`历史版本 · ${selected?.name || ''}`}
        open={historyOpen}
        footer={null}
        width={760}
        onCancel={() => setHistoryOpen(false)}
      >
        <Alert
          type="info"
          showIcon
          message="回滚不会删除历史版本"
          description="恢复操作会把所选旧版本复制为新的最新版本；角色预设仍固定引用各自保存时选择的版本。"
          style={{ marginBottom: 12 }}
        />
        <List
          loading={historyLoading}
          dataSource={versions}
          locale={{ emptyText: '暂无历史版本' }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Popconfirm
                  key={`rollback-${item.version}`}
                  title={`从 v${item.version} 恢复？`}
                  description="将追加一个新的最新版本，历史记录保留。"
                  disabled={item.version === selected?.version}
                  onConfirm={() => void rollback(item.version)}
                >
                  <Button
                    size="small"
                    disabled={item.version === selected?.version}
                    loading={rollingBackVersion === item.version}
                  >
                    {item.version === selected?.version ? '当前版本' : '恢复此版本'}
                  </Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space wrap>
                    <Tag color={item.version === selected?.version ? 'green' : 'default'}>
                      v{item.version}
                    </Tag>
                    <strong>{item.name}</strong>
                    <Tag>{item.items.length} 件</Tag>
                  </Space>
                }
                description={
                  <div>
                    <div>{item.prompt}</div>
                    <div className="help">
                      {item.updated_at} · hash {item.content_hash.slice(0, 12)}
                    </div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      </Modal>
    </>
  );
}
