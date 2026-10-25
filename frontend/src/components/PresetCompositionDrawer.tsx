import {
  DeleteOutlined,
  PictureOutlined,
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
  Select,
  Space,
  Tabs,
  Tag,
  Tooltip,
} from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  api,
  fetchPresetTypes,
  type PresetAssetKind,
  type BodyModificationPreset,
  type ClothingPreset,
  type ExpansionPreset,
  type PoseCatalogItem,
  type PresetCatalog,
  type PresetComposition,
  type PresetCompositionResult,
  type PresetColorSlot,
  type PresetKindMetadata,
  type PresetScope,
  type PresetSelection,
  type PresetTypeCatalog,
  type ScenePreset,
  type ToyPreset,
} from '../api';
import {
  isPresetHidden,
  normalizeSelectionsForSinglePerson,
  PRESET_SCOPE_OPTIONS,
} from '../presetComposition';
import type { PresetAssetSelection } from '../stores/presetAssetStore';
import { getRuntimeConfig } from '../stores/runtimeConfig';
import { settingsStore } from '../stores/settings';
import PresetCategoryFilter, {
  matchesPresetCategory,
  presetCategoryGroup,
  presetCategoryPath,
  presetSubcategory,
  sortPresetItems,
} from './PresetCategoryFilter';

export type PresetCompositionApplyMode = 'replace' | 'append';
export interface PresetCompositionInitialSelection {
  kind: string;
  id: string;
  label: string;
  token: number;
}

type PresetItem =
  | PoseCatalogItem
  | ClothingPreset
  | ScenePreset
  | BodyModificationPreset
  | ExpansionPreset
  | ToyPreset;
type SelectionMap = Record<string, PresetSelection[]>;
type SingleSelectionMap = Record<string, string>;

const FALLBACK_PRESET_TYPES: PresetTypeCatalog = {
  items: [
    {
      kind: 'pose',
      label: '体位',
      order: 0,
      catalog_key: 'poses',
      api_path: '/api/prompt-agent/pose-presets',
      image_directory: 'pose-presets',
      image_extension: 'png',
      taxonomy_key: 'pose',
      composition_field: 'pose_id',
      scope_capable: false,
      max_per_scope: null,
      selection_type: 'single',
      supports_colors: false,
      supports_thumbnail: true,
    },
    {
      kind: 'clothing',
      label: '服装',
      order: 1,
      catalog_key: 'clothing',
      api_path: '/api/prompt-agent/clothing-presets',
      image_directory: 'clothing-presets',
      image_extension: 'webp',
      taxonomy_key: 'clothing',
      composition_field: 'clothing',
      scope_capable: true,
      max_per_scope: 3,
      selection_type: 'multiple',
      supports_colors: true,
      supports_thumbnail: true,
    },
    {
      kind: 'scene',
      label: '场景',
      order: 2,
      catalog_key: 'scenes',
      api_path: '/api/prompt-agent/scene-presets',
      image_directory: 'scene-presets',
      image_extension: 'webp',
      taxonomy_key: 'scene',
      composition_field: 'scene_id',
      scope_capable: false,
      max_per_scope: null,
      selection_type: 'single',
      supports_colors: false,
      supports_thumbnail: true,
    },
    {
      kind: 'body',
      label: '身体改造',
      order: 3,
      catalog_key: 'body_modifications',
      api_path: '/api/prompt-agent/body-modification-presets',
      image_directory: 'body-modification-presets',
      image_extension: 'webp',
      taxonomy_key: 'body',
      composition_field: 'body_modifications',
      scope_capable: true,
      max_per_scope: 2,
      selection_type: 'multiple',
      supports_colors: false,
      supports_thumbnail: true,
    },
    {
      kind: 'expansion',
      label: '扩张',
      order: 4,
      catalog_key: 'expansions',
      api_path: '/api/prompt-agent/expansion-presets',
      image_directory: 'expansion-presets',
      image_extension: 'webp',
      taxonomy_key: 'expansion',
      composition_field: 'expansions',
      scope_capable: true,
      max_per_scope: 2,
      selection_type: 'multiple',
      supports_colors: false,
      supports_thumbnail: true,
    },
    {
      kind: 'toy',
      label: '性玩具',
      order: 5,
      catalog_key: 'toys',
      api_path: '/api/prompt-agent/toy-presets',
      image_directory: 'toy-presets',
      image_extension: 'webp',
      taxonomy_key: 'toy',
      composition_field: 'toys',
      scope_capable: true,
      max_per_scope: 3,
      selection_type: 'multiple',
      supports_colors: true,
      supports_thumbnail: true,
    },
  ],
  composition: {
    max_items: 12,
  },
};

function catalogItems(catalog: PresetCatalog | null, catalogKey: string): PresetItem[] {
  if (!catalog) return [];
  const value = (catalog as unknown as Record<string, unknown>)[catalogKey];
  return Array.isArray(value) ? (value as PresetItem[]) : [];
}

function collectText(value: unknown): string[] {
  if (typeof value === 'string' || typeof value === 'number') return [String(value)];
  if (Array.isArray(value)) return value.flatMap(collectText);
  if (!value || typeof value !== 'object') return [];
  return Object.entries(value as Record<string, unknown>)
    .filter(([key]) => key !== 'image' && key !== 'has_image')
    .flatMap(([, child]) => collectText(child));
}

function itemSearchText(item: PresetItem): string {
  return collectText(item).join(' ');
}

function itemString(item: PresetItem, field: string): string {
  const value = (item as unknown as Record<string, unknown>)[field];
  return typeof value === 'string' ? value : '';
}

function itemStrings(item: PresetItem, field: string): string[] {
  const value = (item as unknown as Record<string, unknown>)[field];
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === 'string')
    : [];
}

function extraValues(kind: PresetKindMetadata, item: PresetItem): string[] {
  if (kind.kind === 'pose') return [itemString(item, 'people')].filter(Boolean);
  if (kind.kind === 'scene') return [itemString(item, 'setting')].filter(Boolean);
  if (kind.kind === 'clothing') return itemStrings(item, 'materials');
  if (kind.kind === 'body') {
    return [
      itemString(item, 'modification_type'),
      itemString(item, 'location'),
    ].filter(Boolean);
  }
  if (kind.kind === 'toy') {
    return [
      itemString(item, 'form_factor'),
      itemString(item, 'material_appearance'),
    ].filter(Boolean);
  }
  if (kind.kind === 'expansion') {
    return [
      itemString(item, 'state'),
      (item as ExpansionPreset).visual_material?.label || '',
    ].filter(Boolean);
  }
  return [];
}

function extraPlaceholder(kind: PresetKindMetadata): string {
  if (kind.kind === 'pose') return '人数';
  if (kind.kind === 'scene') return '场景设定';
  if (kind.kind === 'clothing') return '材质';
  if (kind.kind === 'toy') return '形态或材质';
  if (kind.kind === 'expansion') return '扩张状态或视觉材质';
  return '附加筛选';
}

function itemTitleTags(item: PresetItem) {
  const rating = itemString(item, 'rating');
  const intensity = itemString(item, 'intensity');
  const people = itemString(item, 'people');
  const modificationType = itemString(item, 'modification_type');
  const formFactor = itemString(item, 'form_factor');
  const materialAppearance = itemString(item, 'material_appearance');
  const expansionState = itemString(item, 'state');
  return (
    <Space size={4} wrap>
      <span>{item.label}</span>
      {rating === 'R18' ? <Tag color="red">R18</Tag> : null}
      <Tag color="blue">{presetCategoryGroup(item)}</Tag>
      <Tag>{presetSubcategory(item)}</Tag>
      {'layer_state' in item && item.layer_state ? <Tag>{item.layer_state}</Tag> : null}
      {intensity ? <Tag>{intensity}</Tag> : null}
      {people ? <Tag>{people}</Tag> : null}
      {modificationType ? <Tag>{modificationType}</Tag> : null}
      {formFactor ? <Tag>{formFactor}</Tag> : null}
      {materialAppearance ? <Tag>{materialAppearance}</Tag> : null}
      {expansionState ? <Tag>{expansionState}</Tag> : null}
    </Space>
  );
}

export default function PresetCompositionDrawer({
  open,
  onClose,
  onApply,
  onManageThumbnail,
  initialSelection,
}: {
  open: boolean;
  onClose: () => void;
  onApply: (
    result: PresetCompositionResult,
    composition: PresetComposition,
    mode: PresetCompositionApplyMode,
  ) => void;
  onManageThumbnail?: (selection: PresetAssetSelection) => void;
  initialSelection?: PresetCompositionInitialSelection | null;
}) {
  const { restrictionEnabled } = settingsStore;
  const runtimeConfig = getRuntimeConfig();
  const [presetTypes, setPresetTypes] = useState<PresetTypeCatalog>(() => ({
    ...FALLBACK_PRESET_TYPES,
    composition: {
      max_items: runtimeConfig.preset_composition.max_items,
    },
  }));
  const [catalog, setCatalog] = useState<PresetCatalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [composing, setComposing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [activeKind, setActiveKind] = useState('pose');
  const [keyword, setKeyword] = useState('');
  const [categoryGroup, setCategoryGroup] = useState('');
  const [subcategory, setSubcategory] = useState('');
  const [intensity, setIntensity] = useState('');
  const [extraFilter, setExtraFilter] = useState('');
  const [scope, setScope] = useState<PresetScope>('all');
  const [singleSelections, setSingleSelections] = useState<SingleSelectionMap>({});
  const [multiSelections, setMultiSelections] = useState<SelectionMap>({});
  const [result, setResult] = useState<PresetCompositionResult | null>(null);
  const handledInitialSelectionRef = useRef<number | null>(null);

  const presetKinds = useMemo(
    () =>
      presetTypes.items
        .filter((item) => item.composition_enabled !== false)
        .sort((left, right) => left.order - right.order),
    [presetTypes.items],
  );
  const activeMetadata =
    presetKinds.find((item) => item.kind === activeKind) || presetKinds[0];
  const maxItems = presetTypes.composition.max_items;

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    const [catalogResult, typesResult] = await Promise.allSettled([
      api.get<PresetCatalog>('/prompt-agent/preset-catalog'),
      fetchPresetTypes(),
    ]);
    if (catalogResult.status === 'fulfilled') {
      setCatalog(catalogResult.value.data);
    } else {
      setCatalog(null);
      message.error('预设目录加载失败');
    }
    if (typesResult.status === 'fulfilled') {
      setPresetTypes(typesResult.value);
    } else {
      setPresetTypes({
        ...FALLBACK_PRESET_TYPES,
        composition: {
          max_items: runtimeConfig.preset_composition.max_items,
        },
      });
    }
    setLoading(false);
  }, [runtimeConfig.preset_composition.max_items]);

  useEffect(() => {
    if (!open) return;
    void loadCatalog();
  }, [loadCatalog, open]);

  useEffect(() => {
    if (presetKinds.length === 0) return;
    if (!presetKinds.some((item) => item.kind === activeKind)) {
      setActiveKind(presetKinds[0].kind);
    }
  }, [activeKind, presetKinds]);

  useEffect(() => {
    setResult(null);
  }, [singleSelections, multiSelections]);

  const visibleByKind = useMemo(() => {
    const values: Record<string, PresetItem[]> = {};
    for (const kind of presetKinds) {
      values[kind.kind] = sortPresetItems(
        catalogItems(catalog, kind.catalog_key).filter(
          (item) => !isPresetHidden(item, restrictionEnabled),
        ),
      );
    }
    return values;
  }, [catalog, presetKinds, restrictionEnabled]);

  const presetMaps = useMemo(() => {
    const values: Record<string, Map<string, PresetItem>> = {};
    for (const kind of presetKinds) {
      values[kind.kind] = new Map(
        (visibleByKind[kind.kind] || []).map((item) => [item.id, item]),
      );
    }
    return values;
  }, [presetKinds, visibleByKind]);

  useEffect(() => {
    if (!open || !initialSelection) return;
    if (handledInitialSelectionRef.current === initialSelection.token) return;
    const kind = presetKinds.find((item) => item.kind === initialSelection.kind);
    if (!kind) return;
    const item = presetMaps[kind.kind]?.get(initialSelection.id);
    if (!item) return;
    handledInitialSelectionRef.current = initialSelection.token;
    setActiveKind(kind.kind);
    if (kind.selection_type === 'single') {
      setSingleSelections((current) => ({
        ...current,
        [kind.kind]: item.id,
      }));
      return;
    }
    setMultiSelections((current) => {
      const selected = current[kind.kind] || [];
      if (selected.some((entry) => entry.id === item.id)) return current;
      return {
        ...current,
        [kind.kind]: [...selected, { id: item.id, scope: 'all' }],
      };
    });
  }, [initialSelection, open, presetKinds, presetMaps]);

  const selectedSingleRows = presetKinds
    .filter((kind) => kind.selection_type === 'single')
    .map((kind) => ({
      kind,
      item: presetMaps[kind.kind]?.get(singleSelections[kind.kind] || ''),
    }))
    .filter((row): row is { kind: PresetKindMetadata; item: PresetItem } => Boolean(row.item));
  const hasSinglePerson = selectedSingleRows.some(
    (row) => itemString(row.item, 'people') === '单人',
  );
  const scopeOptions = hasSinglePerson
    ? PRESET_SCOPE_OPTIONS.filter((item) => item.value === 'all')
    : PRESET_SCOPE_OPTIONS;

  useEffect(() => {
    if (!hasSinglePerson) return;
    setScope('all');
    setMultiSelections((current) => {
      let changed = false;
      const next: SelectionMap = { ...current };
      for (const kind of presetKinds) {
        if (kind.selection_type !== 'multiple') continue;
        const items = current[kind.kind] || [];
        const normalized = normalizeSelectionsForSinglePerson(
          items,
          kind.max_per_scope ?? maxItems,
        );
        if (normalized !== items) {
          next[kind.kind] = normalized;
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [hasSinglePerson, maxItems, presetKinds]);

  const keywordLower = keyword.trim().toLowerCase();
  const matches = (text: string) => !keywordLower || text.toLowerCase().includes(keywordLower);

  const filteredItemsForKind = (kind: PresetKindMetadata): PresetItem[] =>
    (visibleByKind[kind.kind] || []).filter(
      (item) =>
        matchesPresetCategory(item, categoryGroup, subcategory) &&
        (!intensity || itemString(item, 'intensity') === intensity) &&
        (!extraFilter || extraValues(kind, item).includes(extraFilter)) &&
        matches(itemSearchText(item)),
    );

  const activeItems = activeMetadata ? visibleByKind[activeMetadata.kind] || [] : [];
  const intensityOptions = activeItems
    .map((item) => itemString(item, 'intensity'))
    .filter(Boolean);
  const extraOptions = activeMetadata
    ? activeItems.flatMap((item) => extraValues(activeMetadata, item))
    : [];
  const totalItems =
    selectedSingleRows.length +
    presetKinds
      .filter((kind) => kind.selection_type === 'multiple')
      .reduce((count, kind) => count + (multiSelections[kind.kind]?.length || 0), 0);

  const updateMultiSelections = (
    field: string,
    update: (items: PresetSelection[]) => PresetSelection[],
  ) => {
    setMultiSelections((current) => ({
      ...current,
      [field]: update(current[field] || []),
    }));
  };

  const addSelection = (kind: PresetKindMetadata, id: string) => {
    if (kind.selection_type === 'single') {
      setSingleSelections((current) => ({ ...current, [kind.kind]: id }));
      return;
    }
    const items = multiSelections[kind.kind] || [];
    if (items.some((item) => item.id === id)) {
      message.info('该预设已在组合中');
      return;
    }
    if (totalItems >= maxItems) {
      message.warning(`单个组合最多包含 ${maxItems} 个预设`);
      return;
    }
    const nextScope = kind.scope_capable ? scope : 'all';
    const limit = kind.max_per_scope ?? maxItems;
    if (items.filter((item) => item.scope === nextScope).length >= limit) {
      message.warning(`${kind.label}的 ${nextScope} 范围最多 ${limit} 项`);
      return;
    }
    if (hasSinglePerson && nextScope !== 'all') {
      message.warning('单人构图不能给具体角色添加预设范围');
      return;
    }
    updateMultiSelections(kind.kind, (current) => [
      ...current,
      { id, scope: nextScope },
    ]);
  };

  const updateScope = (
    kind: PresetKindMetadata,
    id: string,
    nextScope: PresetScope,
  ) => {
    if (!kind.scope_capable) return;
    if (hasSinglePerson && nextScope !== 'all') {
      message.warning('单人构图不能给具体角色添加预设范围');
      return;
    }
    const items = multiSelections[kind.kind] || [];
    const limit = kind.max_per_scope ?? maxItems;
    if (
      nextScope !== scope &&
      items.filter((item) => item.id !== id && item.scope === nextScope).length >= limit
    ) {
      message.warning(`${kind.label}的 ${nextScope} 范围最多 ${limit} 项`);
      return;
    }
    updateMultiSelections(kind.kind, (current) =>
      current.map((item) => (item.id === id ? { ...item, scope: nextScope } : item)),
    );
  };

  const updateColor = (
    kind: PresetKindMetadata,
    id: string,
    slot: PresetColorSlot,
    value: string,
  ) => {
    updateMultiSelections(kind.kind, (current) =>
      current.map((item) =>
        item.id === id
          ? {
              ...item,
              colors: {
                ...(item.colors || {}),
                [slot]: value,
              },
            }
          : item,
      ),
    );
  };

  const removeSelection = (kind: PresetKindMetadata, id: string) => {
    if (kind.selection_type === 'single') {
      setSingleSelections((current) => {
        const next = { ...current };
        delete next[kind.kind];
        return next;
      });
      return;
    }
    updateMultiSelections(kind.kind, (current) =>
      current.filter((item) => item.id !== id),
    );
  };

  const buildPayload = (): PresetComposition => {
    const payload: Record<string, unknown> = {};
    for (const kind of presetKinds) {
      payload[kind.composition_field] =
        kind.selection_type === 'single'
          ? singleSelections[kind.kind] || null
          : multiSelections[kind.kind] || [];
    }
    return payload as unknown as PresetComposition;
  };

  const compose = async (): Promise<PresetCompositionResult | null> => {
    setComposing(true);
    try {
      const { data } = await api.post<PresetCompositionResult>(
        '/prompt-agent/compose-presets',
        buildPayload(),
      );
      setResult(data);
      return data;
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data
        ?.detail;
      message.error(detail || '组合生成失败');
      return null;
    } finally {
      setComposing(false);
    }
  };

  const handleApply = async (mode: PresetCompositionApplyMode) => {
    const data = result || (await compose());
    if (!data) return;
    onApply(data, buildPayload(), mode);
    onClose();
  };

  const handleSave = async () => {
    if (!saveName.trim()) {
      message.warning('请输入组合名称');
      return;
    }
    const data = result || (await compose());
    if (!data) return;
    setSaving(true);
    try {
      const composition = buildPayload();
      await api.post('/prompt-sets', {
        name: saveName.trim(),
        type: '组合',
        content: data.prompt,
        translation: '按预设 ID 重算的组合提示词',
        description: `预设组合：${data.used_ids.join(', ')}`,
        tags: data.rating === 'R18' ? 'R18,组合' : '组合',
        composition_json: JSON.stringify(composition),
      });
      message.success(`已保存组合：${saveName.trim()}`);
      setSaveOpen(false);
      setSaveName('');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data
        ?.detail;
      message.error(detail || '保存组合失败');
    } finally {
      setSaving(false);
    }
  };

  const resetFilters = () => {
    setKeyword('');
    setCategoryGroup('');
    setSubcategory('');
    setIntensity('');
    setExtraFilter('');
  };

  const renderSingleItem = (kind: PresetKindMetadata, item: PresetItem) => {
    const selected = singleSelections[kind.kind] === item.id;
    return (
      <List.Item
        actions={[
          <Button
            key="select"
            size="small"
            type={selected ? 'primary' : 'link'}
            onClick={() => addSelection(kind, item.id)}
          >
            {selected ? '已选择' : '选择'}
          </Button>,
          ...(onManageThumbnail
            ? [
                <Tooltip key="thumbnail" title="管理缩略图">
                  <Button
                    size="small"
                    type="link"
                    icon={<PictureOutlined />}
                    onClick={() =>
                      onManageThumbnail({
                        presetType: kind.kind as PresetAssetKind,
                        presetId: item.id,
                        label: item.label,
                      })
                    }
                  />
                </Tooltip>,
              ]
            : []),
        ]}
      >
        <List.Item.Meta
          avatar={
            item.image ? (
              <Image
                src={item.image}
                alt={item.label}
                width={96}
                height={54}
                style={{ objectFit: 'cover', borderRadius: 4 }}
                preview={{ mask: false }}
              />
            ) : undefined
          }
          title={itemTitleTags(item)}
          description={
            <div>
              <div>{item.translation}</div>
              <div className="help">{itemStrings(item, 'tags').join(', ')}</div>
            </div>
          }
        />
      </List.Item>
    );
  };

  const renderMultipleItem = (kind: PresetKindMetadata, item: PresetItem) => (
    <List.Item
      actions={[
        <Tooltip key="add" title={`按当前角色范围加入${kind.label}`}>
          <Button size="small" type="link" onClick={() => addSelection(kind, item.id)}>
            加入
          </Button>
        </Tooltip>,
        ...(onManageThumbnail
          ? [
              <Tooltip key="thumbnail" title="管理缩略图">
                <Button
                  size="small"
                  type="link"
                  icon={<PictureOutlined />}
                  onClick={() =>
                    onManageThumbnail({
                      presetType: kind.kind as PresetAssetKind,
                      presetId: item.id,
                      label: item.label,
                    })
                  }
                />
              </Tooltip>,
            ]
          : []),
      ]}
    >
      <List.Item.Meta
        avatar={
          item.image ? (
            <Image
              src={item.image}
              alt={item.label}
              width={54}
              height={86}
              style={{ objectFit: 'cover', borderRadius: 4 }}
              preview={{ mask: false }}
            />
          ) : undefined
        }
        title={itemTitleTags(item)}
        description={
          <div>
            <div>{item.translation}</div>
            <div className="help">{itemStrings(item, 'tags').join(', ')}</div>
          </div>
        }
      />
    </List.Item>
  );

  const renderTab = (kind: PresetKindMetadata) => {
    const items = filteredItemsForKind(kind);
    if (kind.selection_type === 'single') {
      const selected = selectedSingleRows.find((row) => row.kind.kind === kind.kind);
      return (
        <div className="preset-composition-list">
          <Select
            showSearch
            allowClear
            value={singleSelections[kind.kind] || undefined}
            placeholder={`选择${kind.label}`}
            optionFilterProp="label"
            style={{ width: '100%', marginBottom: 8 }}
            options={items.map((item) => ({
              label: `${item.label}（${presetCategoryPath(item)}${itemString(item, 'people') ? ` / ${itemString(item, 'people')}` : ''}）`,
              value: item.id,
            }))}
            onChange={(value) => {
              setSingleSelections((current) => {
                const next = { ...current };
                if (value) next[kind.kind] = value;
                else delete next[kind.kind];
                return next;
              });
            }}
          />
          {selected ? (
            <Alert
              type="info"
              showIcon
              message={`${selected.item.label}：${selected.item.translation || ''}`}
              description={
                itemStrings(selected.item, 'role_slots').length > 0
                  ? `角色槽位：${itemStrings(selected.item, 'role_slots').join(' → ')}`
                  : '无角色槽位'
              }
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`尚未选择${kind.label}`} />
          )}
          <List
            loading={loading}
            dataSource={items}
            style={{ marginTop: 8 }}
            renderItem={(item) => renderSingleItem(kind, item)}
          />
        </div>
      );
    }
    return (
      <List
        className="preset-composition-list"
        loading={loading}
        dataSource={items}
        renderItem={(item) => renderMultipleItem(kind, item)}
      />
    );
  };

  return (
    <>
      <Drawer
        title="预设组合"
        width={typeof window !== 'undefined' && window.innerWidth < 900 ? '100vw' : 1180}
        open={open}
        onClose={onClose}
        extra={
          <Space>
            <Tag color="blue">已选 {totalItems} / {maxItems}</Tag>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadCatalog()}>
              刷新
            </Button>
          </Space>
        }
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1.6fr) minmax(340px, 0.9fr)',
            gap: 14,
          }}
        >
          <div>
            {activeMetadata ? (
              <>
                <Space wrap style={{ marginBottom: 8 }}>
                  <Input.Search
                    allowClear
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    placeholder="搜索当前分类"
                    style={{ width: 210 }}
                  />
                  <PresetCategoryFilter
                    items={activeItems}
                    categoryGroup={categoryGroup}
                    subcategory={subcategory}
                    onCategoryGroupChange={(value) => {
                      setCategoryGroup(value);
                      setSubcategory('');
                    }}
                    onSubcategoryChange={setSubcategory}
                  />
                  {intensityOptions.length > 0 ? (
                    <Select
                      allowClear
                      value={intensity || undefined}
                      onChange={(value) => setIntensity(value || '')}
                      placeholder="强度"
                      style={{ width: 100 }}
                      options={Array.from(new Set(intensityOptions)).map((value) => ({
                        label: value,
                        value,
                      }))}
                    />
                  ) : null}
                  {extraOptions.length > 0 ? (
                    <Select
                      allowClear
                      value={extraFilter || undefined}
                      onChange={(value) => setExtraFilter(value || '')}
                      placeholder={extraPlaceholder(activeMetadata)}
                      style={{ width: 130 }}
                      options={Array.from(new Set(extraOptions)).map((value) => ({
                        label: value,
                        value,
                      }))}
                    />
                  ) : null}
                  {activeMetadata.selection_type === 'multiple' &&
                  activeMetadata.scope_capable ? (
                    <Select
                      value={scope}
                      onChange={setScope}
                      options={scopeOptions}
                      style={{ width: 112 }}
                    />
                  ) : null}
                  <Button size="small" onClick={resetFilters}>
                    清空筛选
                  </Button>
                </Space>
                <Tabs
                  activeKey={activeMetadata.kind}
                  onChange={(key) => {
                    setActiveKind(key);
                    resetFilters();
                  }}
                  items={presetKinds.map((kind) => ({
                    key: kind.kind,
                    label: `${kind.label} (${filteredItemsForKind(kind).length})`,
                    children: renderTab(kind),
                  }))}
                />
              </>
            ) : (
              <Empty description="没有可用的预设类型" />
            )}
          </div>
          <div className="preset-composition-summary">
            <div className="train-section-title">当前组合</div>
            {selectedSingleRows.map(({ kind, item }) => (
              <div key={`${kind.kind}-${item.id}`} className="preset-composition-row">
                <Tag color={kind.kind === 'scene' ? 'cyan' : 'purple'}>{kind.label}</Tag>
                <span>{item.label}</span>
                <Button
                  size="small"
                  type="link"
                  danger
                  onClick={() => removeSelection(kind, item.id)}
                >
                  移除
                </Button>
              </div>
            ))}
            {presetKinds
              .filter((kind) => kind.selection_type === 'multiple')
              .flatMap((kind) =>
                (multiSelections[kind.kind] || []).map((selection) => {
                  const preset = presetMaps[kind.kind]?.get(selection.id);
                  return (
                    <div
                      key={`${kind.kind}-${selection.id}`}
                      className="preset-composition-row preset-composition-stack"
                    >
                      <div>
                        <Tag color={kind.supports_colors ? 'blue' : 'orange'}>
                          {kind.label}
                        </Tag>
                        <span>{preset?.label || selection.id}</span>
                      </div>
                      <Space wrap size={4}>
                        {kind.scope_capable ? (
                          <Select
                            size="small"
                            value={selection.scope}
                            options={scopeOptions}
                            onChange={(value) => updateScope(kind, selection.id, value)}
                            style={{ width: 92 }}
                          />
                        ) : null}
                        {kind.supports_colors
                          ? (['primary', 'secondary', 'accent'] as PresetColorSlot[])
                              .filter((slot) => {
                                const slots = preset ? itemStrings(preset, 'color_slots') : [];
                                return slots.length === 0 || slots.includes(slot);
                              })
                              .map((slot) => (
                                <Input
                                  key={slot}
                                  size="small"
                                  maxLength={40}
                                  value={selection.colors?.[slot] || ''}
                                  placeholder={slot}
                                  onChange={(e) =>
                                    updateColor(kind, selection.id, slot, e.target.value)
                                  }
                                  style={{ width: slot === 'accent' ? 74 : 86 }}
                                />
                              ))
                          : null}
                        <Button
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => removeSelection(kind, selection.id)}
                        />
                      </Space>
                    </div>
                  );
                }),
              )}
            {totalItems === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未选择预设" />
            ) : null}
            <Space style={{ marginTop: 10 }}>
              <Button
                type="primary"
                loading={composing}
                disabled={totalItems === 0}
                onClick={() => void compose()}
              >
                生成组合提示词
              </Button>
              <Button
                icon={<SaveOutlined />}
                disabled={totalItems === 0}
                onClick={() => setSaveOpen(true)}
              >
                保存组合
              </Button>
            </Space>
            {result ? (
              <>
                {result.warnings.map((warning) => (
                  <Alert
                    key={warning}
                    type="warning"
                    showIcon
                    message={warning}
                    style={{ marginTop: 8 }}
                  />
                ))}
                <div className="setting-label" style={{ marginTop: 10 }}>
                  组合结果
                </div>
                <Input.TextArea rows={8} value={result.prompt} readOnly />
                <Space style={{ marginTop: 8 }}>
                  <Button type="primary" onClick={() => void handleApply('replace')}>
                    替换第一组
                  </Button>
                  <Button onClick={() => void handleApply('append')}>追加到第一组</Button>
                </Space>
              </>
            ) : null}
          </div>
        </div>
      </Drawer>
      <Modal
        title="保存预设组合"
        open={saveOpen}
        onOk={() => void handleSave()}
        onCancel={() => setSaveOpen(false)}
        confirmLoading={saving}
      >
        <Input
          value={saveName}
          onChange={(e) => setSaveName(e.target.value)}
          placeholder="例如：校园制服 + 镜面摄影棚"
          onPressEnter={() => void handleSave()}
        />
      </Modal>
    </>
  );
}
