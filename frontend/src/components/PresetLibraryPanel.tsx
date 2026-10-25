import {
  AppstoreOutlined,
  CopyOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Empty,
  Image,
  Input,
  List,
  Segmented,
  Select,
  Space,
  Tabs,
  Tag,
  Tooltip,
  message,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchPresetTypes,
  type PresetAssetKind,
  type PresetCatalog,
  type PresetKindMetadata,
  type PresetTaxonomyFields,
  type PresetTypeCatalog,
} from '../api';
import {
  presetCategoryGroup,
  presetSubcategory,
  sortPresetItems,
} from './PresetCategoryFilter';
import {
  createPresetLibraryFilters,
  loadPresetLibraryViewState,
  savePresetLibraryViewState,
  type PresetLibraryFilters,
} from '../presetLibraryState';
import { setPresetAssetSelection } from '../stores/presetAssetStore';
import { requestPresetComposition } from '../stores/presetLibrary';
import { settingsStore } from '../stores/settings';
import { uiStore } from '../stores/ui';

export type PresetLibraryItem = PresetTaxonomyFields & {
  id: string;
  label: string;
  translation?: string;
  tags?: string[];
  rating?: string;
  nsfw?: boolean;
  image?: string | null;
  has_image?: boolean;
};

function catalogItems(
  catalog: PresetCatalog | null,
  key: string,
): PresetLibraryItem[] {
  if (!catalog) return [];
  const value = (catalog as unknown as Record<string, unknown>)[key];
  return Array.isArray(value) ? (value as PresetLibraryItem[]) : [];
}

function itemText(item: PresetLibraryItem): string {
  return [
    item.id,
    item.label,
    item.translation,
    presetCategoryGroup(item),
    presetSubcategory(item),
    ...(item.tags || []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function itemRating(item: PresetLibraryItem): string {
  return String(item.rating || (item.nsfw ? 'R18' : '普通'));
}

function itemHidden(item: PresetLibraryItem, restrictionEnabled: boolean): boolean {
  return restrictionEnabled && itemRating(item) === 'R18';
}

export interface PresetLibraryPanelProps {
  variant?: 'page' | 'drawer';
  onApply?: (kind: string, item: PresetLibraryItem) => void;
  onAddToComposition?: (kind: string, item: PresetLibraryItem) => void;
  onManageThumbnail?: (kind: string, item: PresetLibraryItem) => void;
}

export default function PresetLibraryPanel({
  variant = 'page',
  onApply,
  onAddToComposition,
  onManageThumbnail,
}: PresetLibraryPanelProps) {
  const { restrictionEnabled } = settingsStore;
  const savedView = useMemo(loadPresetLibraryViewState, []);
  const [types, setTypes] = useState<PresetTypeCatalog>({
    items: [],
    composition: { max_items: 12 },
  });
  const [catalog, setCatalog] = useState<PresetCatalog | null>(null);
  const [activeKind, setActiveKind] = useState(savedView.activeKind);
  const [selectedIds, setSelectedIds] = useState<Record<string, string>>(
    savedView.selectedIds,
  );
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(
    savedView.viewMode,
  );
  const [filtersByKind, setFiltersByKind] = useState(
    savedView.filtersByKind,
  );
  const [loading, setLoading] = useState(false);

  const filters =
    filtersByKind[activeKind] || createPresetLibraryFilters();
  const { keyword, categoryGroup, subcategory, rating, resource } = filters;

  const updateFilters = (patch: Partial<PresetLibraryFilters>) => {
    setFiltersByKind((current) => ({
      ...current,
      [activeKind]: {
        ...(current[activeKind] || createPresetLibraryFilters()),
        ...patch,
      },
    }));
  };

  useEffect(() => {
    savePresetLibraryViewState({
      activeKind,
      selectedIds,
      viewMode,
      filtersByKind,
    });
  }, [
    activeKind,
    selectedIds,
    viewMode,
    filtersByKind,
  ]);

  const load = useCallback(async () => {
    setLoading(true);
    const [typesResult, catalogResult] = await Promise.allSettled([
      fetchPresetTypes(),
      import('../api').then(({ api }) => api.get<PresetCatalog>('/prompt-agent/preset-catalog')),
    ]);
    if (typesResult.status === 'fulfilled') {
      setTypes(typesResult.value);
    } else {
      message.error('预设类型加载失败');
    }
    if (catalogResult.status === 'fulfilled') {
      setCatalog(catalogResult.value.data);
    } else {
      message.error('预设目录加载失败');
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const kinds = useMemo(
    () =>
      types.items
        .filter((item) => item.composition_enabled !== false)
        .sort((left, right) => left.order - right.order),
    [types.items],
  );

  useEffect(() => {
    if (!kinds.length) return;
    if (!kinds.some((item) => item.kind === activeKind)) {
      setActiveKind(kinds[0].kind);
    }
  }, [activeKind, kinds]);

  const activeMetadata = kinds.find((item) => item.kind === activeKind);
  const visibleItems = useMemo(
    () =>
      activeMetadata
        ? sortPresetItems(
            catalogItems(catalog, activeMetadata.catalog_key).filter(
              (item) => !itemHidden(item, restrictionEnabled),
            ),
          )
        : [],
    [activeMetadata, catalog, restrictionEnabled],
  );

  const categoryGroups = useMemo(
    () =>
      Array.from(
        new Set(visibleItems.map((item) => presetCategoryGroup(item)).filter(Boolean)),
      ),
    [visibleItems],
  );
  const subcategories = useMemo(
    () =>
      Array.from(
        new Set(
          visibleItems
            .filter(
              (item) =>
                !categoryGroup ||
                presetCategoryGroup(item) === categoryGroup,
            )
            .map((item) => presetSubcategory(item))
            .filter(Boolean),
        ),
      ),
    [categoryGroup, visibleItems],
  );
  const ratings = useMemo(
    () => Array.from(new Set(visibleItems.map(itemRating).filter(Boolean))),
    [visibleItems],
  );

  useEffect(() => {
    if (!activeMetadata || visibleItems.length === 0) return;
    const patch: Partial<PresetLibraryFilters> = {};
    if (
      categoryGroup &&
      !categoryGroups.includes(categoryGroup)
    ) {
      patch.categoryGroup = '';
      patch.subcategory = '';
    } else if (
      subcategory &&
      !subcategories.includes(subcategory)
    ) {
      patch.subcategory = '';
    }
    if (rating && !ratings.includes(rating)) {
      patch.rating = '';
    }
    if (Object.keys(patch).length > 0) updateFilters(patch);
  }, [
    activeMetadata,
    categoryGroup,
    categoryGroups,
    rating,
    ratings,
    subcategory,
    subcategories,
    visibleItems.length,
  ]);

  const items = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return visibleItems.filter((item) => {
      if (categoryGroup && presetCategoryGroup(item) !== categoryGroup) return false;
      if (subcategory && presetSubcategory(item) !== subcategory) return false;
      if (rating && itemRating(item) !== rating) return false;
      if (resource === 'with_image' && !item.has_image && !item.image) return false;
      if (resource === 'without_image' && (item.has_image || item.image)) return false;
      return !query || itemText(item).includes(query);
    });
  }, [categoryGroup, keyword, rating, resource, subcategory, visibleItems]);

  useEffect(() => {
    if (!activeMetadata || items.length === 0) return;
    const selectedId = selectedIds[activeMetadata.kind];
    if (selectedId && items.some((item) => item.id === selectedId)) return;
    setSelectedIds((current) => ({
      ...current,
      [activeMetadata.kind]: items[0].id,
    }));
  }, [activeMetadata, items, selectedIds]);

  const selectedItem =
    (activeMetadata && items.find(
      (item) => item.id === selectedIds[activeMetadata.kind],
    )) ||
    items[0] ||
    null;

  const resetFilters = () => {
    updateFilters(createPresetLibraryFilters());
  };

  const manageThumbnail = (item: PresetLibraryItem) => {
    if (!activeMetadata) return;
    if (onManageThumbnail) {
      onManageThumbnail(activeMetadata.kind, item);
      return;
    }
    setPresetAssetSelection({
      presetType: activeMetadata.kind as PresetAssetKind,
      presetId: item.id,
      label: item.label,
    });
    uiStore.activeTab = 'presetAssets';
  };

  const addToComposition = (item: PresetLibraryItem) => {
    if (!activeMetadata) return;
    if (onAddToComposition) {
      onAddToComposition(activeMetadata.kind, item);
      return;
    }
    requestPresetComposition({
      kind: activeMetadata.kind,
      id: item.id,
      label: item.label,
    });
    uiStore.activeTab = 'prompt';
    message.success(`已将「${item.label}」加入预设组合`);
  };

  const applyItem = (item: PresetLibraryItem) => {
    if (!activeMetadata) return;
    onApply?.(activeMetadata.kind, item);
  };

  const copyId = async (item: PresetLibraryItem) => {
    try {
      await navigator.clipboard.writeText(item.id);
      message.success('ID 已复制');
    } catch {
      message.error('复制失败');
    }
  };

  return (
    <div className={`preset-library-panel preset-library-panel-${variant}`}>
      <div className="preset-library-header">
        {variant === 'page' ? (
          <div>
            <div className="preset-library-title">预设库</div>
            <div className="preset-library-subtitle">
              浏览全部预设类型，查看缩略图、加入组合或进入预设工坊管理素材。
            </div>
          </div>
        ) : (
          <div className="preset-library-drawer-helper">
            每个预设类型独立保存筛选条件
          </div>
        )}
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
          刷新
        </Button>
      </div>

      <div className="preset-library-layout">
        <aside className="preset-library-type-nav">
          {kinds.map((kind) => {
            const count = catalogItems(catalog, kind.catalog_key).filter(
              (item) => !itemHidden(item, restrictionEnabled),
            ).length;
            return (
              <button
                type="button"
                className={`preset-library-type-item${
                  kind.kind === activeKind ? ' active' : ''
                }`}
                key={kind.kind}
                onClick={() => setActiveKind(kind.kind)}
              >
                <span>{kind.label}</span>
                <small>{count}</small>
              </button>
            );
          })}
        </aside>

        <section className="preset-library-center">
          <div className="preset-library-toolbar">
            <Input.Search
              allowClear
              value={keyword}
              placeholder="搜索名称、ID、标签或分类"
              onChange={(event) => updateFilters({ keyword: event.target.value })}
            />
            <Select
              allowClear
              value={categoryGroup || undefined}
              placeholder="一级分类"
              options={categoryGroups.map((value) => ({ label: value, value }))}
              onChange={(value) => {
                updateFilters({
                  categoryGroup: value || '',
                  subcategory: '',
                });
              }}
            />
            <Select
              allowClear
              value={subcategory || undefined}
              placeholder="二级分类"
              options={subcategories.map((value) => ({ label: value, value }))}
              onChange={(value) => updateFilters({ subcategory: value || '' })}
            />
            <Select
              allowClear
              value={rating || undefined}
              placeholder="评级"
              options={ratings.map((value) => ({ label: value, value }))}
              onChange={(value) => updateFilters({ rating: value || '' })}
            />
            <Select
              value={resource}
              options={[
                { label: '全部资源', value: 'all' },
                { label: '已有缩略图', value: 'with_image' },
                { label: '无缩略图', value: 'without_image' },
              ]}
              onChange={(value) => updateFilters({ resource: value })}
            />
            <Button onClick={resetFilters}>重置筛选</Button>
            <Segmented
              value={viewMode}
              options={[
                { label: <AppstoreOutlined />, value: 'grid' },
                { label: <UnorderedListOutlined />, value: 'list' },
              ]}
              onChange={(value) => setViewMode(value as 'grid' | 'list')}
            />
          </div>

          <div className="preset-library-filter-chips">
            {categoryGroup ? (
              <Tag
                closable
                onClose={() =>
                  updateFilters({ categoryGroup: '', subcategory: '' })
                }
              >
                {categoryGroup}
              </Tag>
            ) : null}
            {subcategory ? (
              <Tag closable onClose={() => updateFilters({ subcategory: '' })}>
                {subcategory}
              </Tag>
            ) : null}
            {rating ? (
              <Tag closable onClose={() => updateFilters({ rating: '' })}>
                {rating}
              </Tag>
            ) : null}
            {resource !== 'all' ? (
              <Tag closable onClose={() => updateFilters({ resource: 'all' })}>
                {resource === 'with_image' ? '已有缩略图' : '无缩略图'}
              </Tag>
            ) : null}
            <span className="help">共 {items.length} 条</span>
          </div>

          {items.length ? (
            <List
              className={`preset-library-list preset-library-list-${viewMode}`}
              loading={loading}
              grid={
                viewMode === 'grid'
                  ? { gutter: 12, xs: 1, sm: 2, md: 2, lg: 3, xl: 4 }
                  : undefined
              }
              dataSource={items}
              renderItem={(item) => {
                const selected = selectedItem?.id === item.id;
                return (
                  <List.Item>
                    <button
                      type="button"
                      className={`preset-library-card${
                        selected ? ' selected' : ''
                      }`}
                      onClick={() =>
                        activeMetadata &&
                        setSelectedIds((current) => ({
                          ...current,
                          [activeMetadata.kind]: item.id,
                        }))
                      }
                    >
                      <div className="preset-library-card-media">
                        {item.image ? (
                          <Image
                            src={item.image}
                            alt={item.label}
                            preview={false}
                          />
                        ) : (
                          <div className="preset-library-card-no-image">
                            无缩略图
                          </div>
                        )}
                      </div>
                      <div className="preset-library-card-copy">
                        <div className="preset-library-card-title">
                          {item.label}
                        </div>
                        <div className="preset-library-card-id">
                          {item.id}
                        </div>
                        <div className="preset-library-card-description">
                          {item.translation || '暂无中文说明'}
                        </div>
                        <Space size={[4, 4]} wrap>
                          {itemRating(item) === 'R18' ? (
                            <Tag color="red">R18</Tag>
                          ) : (
                            <Tag>普通</Tag>
                          )}
                          <Tag>{presetCategoryGroup(item)}</Tag>
                          <Tag>{presetSubcategory(item)}</Tag>
                        </Space>
                      </div>
                    </button>
                  </List.Item>
                );
              }}
            />
          ) : (
            <Empty description="没有符合当前筛选条件的预设" />
          )}
        </section>

        <aside className="preset-library-detail">
          {selectedItem && activeMetadata ? (
            <>
              <div className="preset-library-detail-content">
                <div className="preset-library-detail-cover">
                  {selectedItem.image ? (
                    <Image
                      src={selectedItem.image}
                      alt={selectedItem.label}
                      preview={{ mask: '预览' }}
                    />
                  ) : (
                    <div className="preset-library-card-no-image">
                      无缩略图
                    </div>
                  )}
                </div>
                <div className="preset-library-detail-title">
                  {selectedItem.label}
                </div>
                <div className="preset-library-card-id">
                  {selectedItem.id}
                </div>
                <Space size={[4, 4]} wrap>
                  {itemRating(selectedItem) === 'R18' ? (
                    <Tag color="red">R18</Tag>
                  ) : (
                    <Tag>普通</Tag>
                  )}
                  <Tag>{activeMetadata.label}</Tag>
                  <Tag>{presetCategoryGroup(selectedItem)}</Tag>
                  <Tag>{presetSubcategory(selectedItem)}</Tag>
                </Space>
                <div className="preset-library-detail-description">
                  {selectedItem.translation || '暂无中文说明'}
                </div>
                <div className="preset-library-detail-tags">
                  {(selectedItem.tags || []).map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </div>
              </div>
              <div className="preset-library-detail-actions">
                <Space direction="vertical" style={{ width: '100%' }}>
                  {onApply ? (
                    <Button
                      type="primary"
                      block
                      onClick={() => applyItem(selectedItem)}
                    >
                      应用到当前提示词
                    </Button>
                  ) : null}
                  <Button
                    block
                    icon={<PlusOutlined />}
                    onClick={() => addToComposition(selectedItem)}
                  >
                    加入组合
                  </Button>
                  <Button
                    block
                    icon={<PictureOutlined />}
                    onClick={() => manageThumbnail(selectedItem)}
                  >
                    管理缩略图
                  </Button>
                  <Button
                    block
                    icon={<CopyOutlined />}
                    onClick={() => void copyId(selectedItem)}
                  >
                    复制 ID
                  </Button>
                </Space>
              </div>
            </>
          ) : (
            <Empty description="选择左侧预设查看详情" />
          )}
        </aside>
      </div>
    </div>
  );
}
