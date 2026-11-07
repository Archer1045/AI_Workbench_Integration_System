import {
  CheckCircleOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  HeartFilled,
  HeartOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Input,
  message,
  Pagination,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Tooltip,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import {
  api,
  type ExternalGalleryCatalogue,
  type ExternalGalleryItem,
  type ExternalGalleryKind,
  type ExternalGallerySettings,
  type PoseCatalogItem,
} from '../api';
import {
  createExternalGalleryFilters,
  externalGalleryBindingKey,
  filterExternalGalleryItems,
  loadExternalGalleryActivity,
  recordExternalGalleryRecent,
  saveExternalGalleryActivity,
  toggleExternalGalleryFavorite,
  type ExternalGalleryActivityMode,
  type ExternalGalleryFilters,
} from '../externalGalleryState';

const KIND_LABELS: Record<ExternalGalleryKind, string> = {
  pose: '姿势图库',
  costume: '服装图库',
};

function errorText(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    .response?.data?.detail;
  return typeof detail === 'string' && detail ? detail : fallback;
}

export default function ExternalGalleryDrawer({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect?: (
    kind: ExternalGalleryKind,
    item: ExternalGalleryItem,
  ) => Promise<void> | void;
}) {
  const [activeKind, setActiveKind] = useState<ExternalGalleryKind>('pose');
  const [settings, setSettings] = useState<ExternalGallerySettings | null>(null);
  const [directoryDraft, setDirectoryDraft] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [posePresets, setPosePresets] = useState<PoseCatalogItem[]>([]);
  const [bindingLoading, setBindingLoading] = useState(false);
  const [catalogue, setCatalogue] = useState<ExternalGalleryCatalogue | null>(
    null,
  );
  const [catalogueLoading, setCatalogueLoading] = useState(false);
  const [galleryError, setGalleryError] = useState('');
  const [filters, setFilters] = useState<ExternalGalleryFilters>(
    createExternalGalleryFilters,
  );
  const [activityMode, setActivityMode] =
    useState<ExternalGalleryActivityMode>('all');
  const [activity, setActivity] = useState(loadExternalGalleryActivity);
  const [selected, setSelected] = useState<ExternalGalleryItem | null>(null);
  const [selectedDimensions, setSelectedDimensions] = useState('');
  const [selecting, setSelecting] = useState(false);
  const [page, setPage] = useState(1);

  const binding = settings?.[activeKind] || null;
  const bindingKey = externalGalleryBindingKey(
    activeKind,
    binding?.binding_id || '',
  );
  const managedActivity = catalogue?.mode === 'database';
  const favorites = managedActivity
    ? catalogue.items.filter((item) => item.favorite).map((item) => item.id)
    : activity.favoritesByBinding[bindingKey] || [];
  const recent = managedActivity
    ? catalogue.items
        .filter((item) => item.last_used_at)
        .sort((left, right) =>
          String(right.last_used_at).localeCompare(String(left.last_used_at)),
        )
        .map((item) => item.id)
    : activity.recentByBinding[bindingKey] || [];
  const filteredItems = useMemo(
    () =>
      catalogue
        ? filterExternalGalleryItems(
            catalogue.items,
            filters,
            activityMode,
            favorites,
            recent,
          )
        : [],
    [activityMode, catalogue, favorites, filters, recent],
  );
  const pageSize = 60;
  const visibleItems = filteredItems.slice(
    (page - 1) * pageSize,
    page * pageSize,
  );

  const loadSettings = async () => {
    setSettingsLoading(true);
    try {
      const response = await api.get<{ settings: ExternalGallerySettings }>(
        '/external-galleries/settings',
      );
      setSettings(response.data.settings);
    } catch (error) {
      message.error(errorText(error, '读取外部图库设置失败'));
    } finally {
      setSettingsLoading(false);
    }
  };

  const loadCatalogue = async (kind: ExternalGalleryKind, refresh = false) => {
    setCatalogueLoading(true);
    setGalleryError('');
    try {
      const response = refresh
        ? await api.post<ExternalGalleryCatalogue>(
            `/external-galleries/${kind}/refresh`,
          )
        : await api.get<ExternalGalleryCatalogue>(
            `/external-galleries/${kind}/catalogue`,
          );
      setCatalogue(response.data);
    } catch (error) {
      setCatalogue(null);
      setGalleryError(errorText(error, '扫描外部图库失败'));
    } finally {
      setCatalogueLoading(false);
    }
  };

  useEffect(() => {
    if (open) void loadSettings();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    api
      .get<{ items: PoseCatalogItem[] }>('/prompt-agent/pose-presets')
      .then((response) => setPosePresets(response.data.items || []))
      .catch(() => setPosePresets([]));
  }, [open]);

  useEffect(() => {
    setDirectoryDraft(binding?.directory || '');
    setConfirmed(false);
  }, [activeKind, binding?.directory]);

  useEffect(() => {
    setCatalogue(null);
    setSelected(null);
    setGalleryError('');
    setFilters(createExternalGalleryFilters());
    setActivityMode('all');
    setPage(1);
    if (open && binding?.configured) void loadCatalogue(activeKind);
  }, [open, activeKind, binding?.directory, binding?.configured]);

  useEffect(() => {
    setPage(1);
  }, [filters, activityMode]);

  const bindDirectory = async () => {
    setBindingLoading(true);
    try {
      const response = await api.put<{ settings: ExternalGallerySettings }>(
        `/external-galleries/settings/${activeKind}`,
        {
          directory: directoryDraft.trim(),
          confirmed_local_access: confirmed,
        },
      );
      setSettings(response.data.settings);
      setConfirmed(false);
      message.success(`${KIND_LABELS[activeKind]}已绑定`);
      await loadCatalogue(activeKind, true);
    } catch (error) {
      message.error(errorText(error, '绑定图库失败'));
    } finally {
      setBindingLoading(false);
    }
  };

  const unbindDirectory = async () => {
    setBindingLoading(true);
    try {
      const response = await api.delete<{ settings: ExternalGallerySettings }>(
        `/external-galleries/settings/${activeKind}`,
      );
      setSettings(response.data.settings);
      setCatalogue(null);
      setSelected(null);
      message.success(`${KIND_LABELS[activeKind]}已解绑`);
    } catch (error) {
      message.error(errorText(error, '解绑图库失败'));
    } finally {
      setBindingLoading(false);
    }
  };

  const persistActivity = (next: typeof activity) => {
    setActivity(next);
    saveExternalGalleryActivity(next);
  };

  const toggleFavorite = async (item: ExternalGalleryItem) => {
    if (catalogue?.mode === 'database' && item.asset_id) {
      try {
        const response = await api.post<{ favorite: boolean }>(
          `/external-galleries/${activeKind}/assets/${item.asset_id}/favorite`,
        );
        setCatalogue((current) =>
          current
            ? {
                ...current,
                items: current.items.map((candidate) =>
                  candidate.id === item.id
                    ? { ...candidate, favorite: response.data.favorite }
                    : candidate,
                ),
              }
            : current,
        );
      } catch (error) {
        message.error(errorText(error, '收藏状态保存失败'));
      }
      return;
    }
    persistActivity(toggleExternalGalleryFavorite(activity, bindingKey, item.id));
  };

  const updatePoseLink = async (posePresetId?: string) => {
    if (!selected?.asset_id || activeKind !== 'pose') return;
    try {
      const response = await api.put<{
        pose_preset_id: string;
        pose_preset_label: string;
        pose_preset_category: string;
      }>(
        `/external-galleries/pose/assets/${selected.asset_id}/pose-link`,
        { pose_preset_id: posePresetId || '' },
      );
      const patch = {
        pose_preset_id: response.data.pose_preset_id,
        pose_preset_label: response.data.pose_preset_label,
        pose_preset_category: response.data.pose_preset_category,
      };
      setSelected((current) => (current ? { ...current, ...patch } : current));
      setCatalogue((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.asset_id === selected.asset_id
                  ? { ...item, ...patch }
                  : item,
              ),
            }
          : current,
      );
      message.success(patch.pose_preset_id ? '已关联体位预设' : '已清除体位关联');
    } catch (error) {
      message.error(errorText(error, '体位关联保存失败'));
    }
  };

  const selectItem = async () => {
    if (!selected || !onSelect) return;
    setSelecting(true);
    try {
      if (catalogue?.mode === 'database' && selected.asset_id) {
        try {
          const response = await api.post<{
            last_used_at: string;
            use_count: number;
          }>(
            `/external-galleries/${activeKind}/assets/${selected.asset_id}/use`,
          );
          setCatalogue((current) =>
            current
              ? {
                  ...current,
                  items: current.items.map((candidate) =>
                    candidate.id === selected.id
                      ? {
                          ...candidate,
                          last_used_at: response.data.last_used_at,
                          use_count: response.data.use_count,
                        }
                      : candidate,
                  ),
                }
              : current,
          );
        } catch {
          message.warning('最近使用记录保存失败，但素材仍会载入');
        }
      } else {
        persistActivity(
          recordExternalGalleryRecent(activity, bindingKey, selected.id),
        );
      }
      await onSelect(activeKind, selected);
      onClose();
    } catch (error) {
      message.error(errorText(error, '载入外部参考图失败'));
    } finally {
      setSelecting(false);
    }
  };

  return (
    <Drawer
      title="外部参考图库"
      width="min(1180px, calc(100vw - 24px))"
      open={open}
      onClose={onClose}
      destroyOnClose={false}
    >
      <Spin spinning={settingsLoading}>
        <Tabs
          activeKey={activeKind}
          onChange={(key) => setActiveKind(key as ExternalGalleryKind)}
          items={[
            { key: 'pose', label: '姿势图库' },
            { key: 'costume', label: '服装图库' },
          ]}
        />

        <Card size="small" className="external-gallery-binding">
          <div className="external-gallery-binding-copy">
            <strong>{KIND_LABELS[activeKind]}目录</strong>
            <span>
              图像会复制到工作台托管目录，数据库保存索引、元数据和收藏状态；
              来源目录始终只读。支持 data/*.json 清单或普通图片目录。
            </span>
          </div>
          <Input
            value={directoryDraft}
            onChange={(event) => setDirectoryDraft(event.target.value)}
            placeholder="例如 D:\AI\reference\pose"
            aria-label={`${KIND_LABELS[activeKind]}绝对路径`}
          />
          <div className="external-gallery-bind-actions">
            <Checkbox
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            >
              我确认拥有该目录及素材的合法使用权
            </Checkbox>
            <Space wrap>
              <Button
                type="primary"
                icon={<FolderOpenOutlined />}
                loading={bindingLoading}
                disabled={!directoryDraft.trim() || !confirmed}
                onClick={() => void bindDirectory()}
              >
                {binding?.configured ? '重新导入并扫描' : '导入托管并扫描'}
              </Button>
              {binding?.configured ? (
                <Popconfirm
                  title={`解绑${KIND_LABELS[activeKind]}？`}
                  description="只会删除绑定记录，不会改动素材目录。"
                  onConfirm={() => void unbindDirectory()}
                >
                  <Button danger icon={<DeleteOutlined />}>
                    解绑
                  </Button>
                </Popconfirm>
              ) : null}
            </Space>
          </div>
          {binding?.configured ? (
            <div className="external-gallery-binding-status">
              <Tag color={binding.available ? 'green' : 'red'}>
                {binding.available ? '托管素材可用' : '素材不可用'}
              </Tag>
              <Tag color={binding.source_available ? 'default' : 'orange'}>
                {binding.source_available ? '来源目录可访问' : '来源目录已移动'}
              </Tag>
              <Tag color="blue">数据库托管</Tag>
              <Tag>{binding.item_count} 项</Tag>
              <Tag>{binding.status}</Tag>
              <span>{binding.directory}</span>
            </div>
          ) : null}
        </Card>

        {!binding?.configured ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={`绑定${KIND_LABELS[activeKind]}后浏览素材`}
          />
        ) : (
          <>
            <div className="external-gallery-toolbar">
              <Input.Search
                allowClear
                value={filters.keyword}
                placeholder="搜索名称、标签或相对路径"
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    keyword: event.target.value,
                  }))
                }
              />
              <Select
                allowClear
                value={filters.category || undefined}
                placeholder="分类"
                options={(catalogue?.facets.category || []).map((value) => ({
                  value,
                  label: value,
                }))}
                onChange={(value) =>
                  setFilters((current) => ({
                    ...current,
                    category: value || '',
                  }))
                }
              />
              {activeKind === 'pose' && managedActivity ? (
                <Select
                  allowClear
                  showSearch
                  value={filters.posePreset || undefined}
                  placeholder="关联体位"
                  optionFilterProp="label"
                  options={posePresets.map((preset) => ({
                    value: preset.id,
                    label: `${preset.label} · ${preset.category}`,
                  }))}
                  onChange={(value) =>
                    setFilters((current) => ({
                      ...current,
                      posePreset: value || '',
                    }))
                  }
                />
              ) : null}
              <Select
                allowClear
                value={filters.system || undefined}
                placeholder="体系"
                options={(catalogue?.facets.system || []).map((value) => ({
                  value,
                  label: value,
                }))}
                onChange={(value) =>
                  setFilters((current) => ({
                    ...current,
                    system: value || '',
                  }))
                }
              />
              <Select
                allowClear
                value={filters.angle || undefined}
                placeholder="角度"
                options={(catalogue?.facets.angle || []).map((value) => ({
                  value,
                  label: value,
                }))}
                onChange={(value) =>
                  setFilters((current) => ({ ...current, angle: value || '' }))
                }
              />
              <Select
                allowClear
                value={filters.tag || undefined}
                placeholder="标签"
                options={(catalogue?.facets.tag || []).map((value) => ({
                  value,
                  label: value,
                }))}
                onChange={(value) =>
                  setFilters((current) => ({ ...current, tag: value || '' }))
                }
              />
              <Button
                icon={<ReloadOutlined />}
                loading={catalogueLoading}
                onClick={() => void loadCatalogue(activeKind, true)}
              >
                重新扫描
              </Button>
              <Segmented
                value={activityMode}
                options={[
                  { label: '全部', value: 'all' },
                  { label: `收藏 ${favorites.length}`, value: 'favorites' },
                  { label: `最近 ${recent.length}`, value: 'recent' },
                ]}
                onChange={(value) =>
                  setActivityMode(value as ExternalGalleryActivityMode)
                }
              />
            </div>

            {galleryError ? (
              <Alert
                type="error"
                showIcon
                message="图库读取失败"
                description={galleryError}
              />
            ) : null}
            {catalogue?.warning ? (
              <Alert
                type="warning"
                showIcon
                message="素材清单不可用，已回退到普通目录扫描"
                description={catalogue.warning}
              />
            ) : null}

            <div className="external-gallery-layout">
              <section className="external-gallery-browser">
                <div className="external-gallery-summary">
                  <Space wrap>
                    <Tag color="blue">
                      {catalogue?.mode === 'database'
                        ? '数据库托管'
                        : catalogue?.mode === 'manifest'
                          ? '清单图库'
                          : '普通文件夹'}
                    </Tag>
                    <span>共 {catalogue?.count || 0} 张</span>
                    <span>当前 {filteredItems.length} 张</span>
                    {catalogue?.manifest ? (
                      <span>清单：{catalogue.manifest}</span>
                    ) : null}
                  </Space>
                </div>
                <Spin spinning={catalogueLoading}>
                  {visibleItems.length ? (
                    <div className="external-gallery-grid">
                      {visibleItems.map((item) => {
                        const favorite = favorites.includes(item.id);
                        return (
                          <div
                            key={`${item.path}:${item.id}`}
                            role="button"
                            tabIndex={0}
                            className={`external-gallery-card${
                              selected?.id === item.id ? ' is-selected' : ''
                            }`}
                            onClick={() => {
                              setSelected(item);
                              setSelectedDimensions('');
                            }}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setSelected(item);
                                setSelectedDimensions('');
                              }
                            }}
                          >
                            <img
                              src={item.thumbnail_url}
                              alt={item.name}
                              loading="lazy"
                            />
                            <div className="external-gallery-card-copy">
                              <strong title={item.name}>{item.name}</strong>
                              <span title={item.category || item.path}>
                                {item.pose_preset_label || item.category || item.path}
                              </span>
                            </div>
                            <Tooltip title={favorite ? '取消收藏' : '收藏'}>
                              <Button
                                className="external-gallery-favorite"
                                type="text"
                                size="small"
                                aria-label={favorite ? '取消收藏' : '收藏'}
                                icon={
                                  favorite ? <HeartFilled /> : <HeartOutlined />
                                }
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void toggleFavorite(item);
                                }}
                              />
                            </Tooltip>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        catalogueLoading ? '正在扫描…' : '没有符合筛选条件的素材'
                      }
                    />
                  )}
                </Spin>
                {filteredItems.length > pageSize ? (
                  <Pagination
                    current={page}
                    pageSize={pageSize}
                    total={filteredItems.length}
                    showSizeChanger={false}
                    showTotal={(total) => `共 ${total} 张`}
                    onChange={setPage}
                  />
                ) : null}
              </section>

              <aside className="external-gallery-inspector">
                {selected ? (
                  <>
                    <div className="external-gallery-preview">
                      <img
                        src={selected.image_url}
                        alt={selected.name}
                        onLoad={(event) =>
                          setSelectedDimensions(
                            `${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`,
                          )
                        }
                      />
                    </div>
                    <h3>{selected.name}</h3>
                    <p className="external-gallery-path">{selected.path}</p>
                    {selectedDimensions ? (
                      <Tag>{selectedDimensions}</Tag>
                    ) : (
                      <Tag>读取尺寸中</Tag>
                    )}
                    <Space size={[4, 4]} wrap>
                      {selected.category ? (
                        <Tag color="blue">{selected.category}</Tag>
                      ) : null}
                      {selected.system ? <Tag>{selected.system}</Tag> : null}
                      {selected.angle ? <Tag>{selected.angle}</Tag> : null}
                      {selected.tags.slice(0, 8).map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </Space>
                    {activeKind === 'pose' &&
                    catalogue?.mode === 'database' &&
                    selected.asset_id ? (
                      <label className="comic-field">
                        <span>关联体位预设</span>
                        <Select
                          allowClear
                          showSearch
                          value={selected.pose_preset_id || undefined}
                          placeholder="选择现有体位语义"
                          optionFilterProp="label"
                          options={posePresets.map((preset) => ({
                            value: preset.id,
                            label: `${preset.label} · ${preset.category}`,
                          }))}
                          onChange={(value) => void updatePoseLink(value)}
                        />
                      </label>
                    ) : null}
                    <Button
                      type="primary"
                      block
                      icon={<CheckCircleOutlined />}
                      loading={selecting}
                      onClick={() => void selectItem()}
                    >
                      作为局部重绘底图
                    </Button>
                    <small>
                      选图后会复制到受控临时目录，不会把外部绝对路径写入生成任务。
                    </small>
                  </>
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="选择一张素材查看原图"
                  />
                )}
              </aside>
            </div>
          </>
        )}
      </Spin>
    </Drawer>
  );
}
