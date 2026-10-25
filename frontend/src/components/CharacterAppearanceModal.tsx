// 角色外貌预设库 + 旧查询草稿 + 人工修正
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import {
  Button,
  Image,
  Input,
  message,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Tooltip,
} from 'antd';
import { useEffect, useState } from 'react';
import {
  api,
  type CharacterAppearancePreset,
  type CharacterAppearancePresetApplyResult,
  type CharacterAppearancePresetList,
} from '../api';
import type { PresetAssetSelection } from '../stores/presetAssetStore';
import ClothingPresetsModal from './ClothingPresetsModal';

const SOURCE_LABELS: Record<string, string> = {
  builtin: '内置预设',
  user: '用户预设',
  llm_draft: 'LLM 草稿',
  legacy_cache: '旧缓存导入',
};

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] || source;
}

export interface CharacterAppearanceResult {
  character_name?: string;
  work?: string;
  appearance: string[];
  clothing: string[];
  expression: string[];
  full_prompt?: string;
  confidence?: number;
  source?: 'cache' | 'llm' | 'manual' | string;
  note: string;
  corrected?: boolean;
  default_outfit_id?: string;
  default_outfit_name?: string;
  preset_ref?: { preset_id: string; version: number };
  snapshot?: Record<string, unknown>;
}

interface LegacyCharacterAppearanceResult {
  character_name: string;
  work: string;
  appearance: string[];
  clothing: string[];
  expression?: string[];
  full_prompt: string;
  confidence: number;
  source: 'cache' | 'llm' | 'manual' | string;
  note: string;
  corrected?: boolean;
}

function parseTags(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function resultFromApply(data: CharacterAppearancePresetApplyResult): CharacterAppearanceResult {
  return {
    ...data,
    note: data.snapshot.note,
    source: 'preset',
  };
}

export default function CharacterAppearanceModal({
  open,
  onClose,
  onApply,
  onManageThumbnail,
  title = '角色外观查询',
}: {
  open: boolean;
  onClose: () => void;
  onApply: (apply: { scope: 'current' | 'all'; result: CharacterAppearanceResult }) => void;
  onManageThumbnail?: (selection: PresetAssetSelection) => void;
  title?: string;
}) {
  const [activeTab, setActiveTab] = useState('presets');
  const [scope, setScope] = useState<'current' | 'all'>('current');
  const [presets, setPresets] = useState<CharacterAppearancePreset[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [works, setWorks] = useState<string[]>([]);
  const [keyword, setKeyword] = useState('');
  const [workFilter, setWorkFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [enabledFilter, setEnabledFilter] = useState('');
  const [presetLoading, setPresetLoading] = useState(false);
  const [applyingId, setApplyingId] = useState('');

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingPreset, setEditingPreset] = useState<CharacterAppearancePreset | null>(null);
  const [savingPreset, setSavingPreset] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [presetWork, setPresetWork] = useState('');
  const [presetCategory, setPresetCategory] = useState('自由备注');
  const [presetAppearance, setPresetAppearance] = useState('');
  const [presetClothing, setPresetClothing] = useState('');
  const [presetExpression, setPresetExpression] = useState('');
  const [presetOutfitId, setPresetOutfitId] = useState('');
  const [presetNote, setPresetNote] = useState('');
  const [presetEnabled, setPresetEnabled] = useState(true);

  const [characterName, setCharacterName] = useState('');
  const [work, setWork] = useState('');
  const [queryLoading, setQueryLoading] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [draft, setDraft] = useState<LegacyCharacterAppearanceResult | null>(null);
  const [appearanceText, setAppearanceText] = useState('');
  const [clothingText, setClothingText] = useState('');
  const [expressionText, setExpressionText] = useState('');
  const [noteText, setNoteText] = useState('');
  const [clothingPresetOpen, setClothingPresetOpen] = useState(false);

  const loadPresets = () => {
    setPresetLoading(true);
    api
      .get<CharacterAppearancePresetList>('/prompt-agent/appearance-presets', {
        params: {
          keyword: keyword.trim() || undefined,
          work: workFilter || undefined,
          category: categoryFilter || undefined,
          source: sourceFilter || undefined,
          enabled:
            enabledFilter === 'enabled'
              ? true
              : enabledFilter === 'disabled'
                ? false
                : undefined,
        },
      })
      .then(({ data }) => {
        setPresets(data.items || []);
        setCategories(data.categories || []);
        setSources(data.sources || []);
        setWorks(data.works || []);
      })
      .catch(() => setPresets([]))
      .finally(() => setPresetLoading(false));
  };

  useEffect(() => {
    if (!open) return;
    loadPresets();
  }, [open, keyword, workFilter, categoryFilter, sourceFilter, enabledFilter]);

  useEffect(() => {
    if (!open) return;
    setActiveTab('presets');
    setDraft(null);
    setAppearanceText('');
    setClothingText('');
    setExpressionText('');
    setNoteText('');
  }, [open]);

  const openCreate = () => {
    setEditingPreset(null);
    setPresetName('');
    setPresetWork('');
    setPresetCategory(categories[0] || '自由备注');
    setPresetAppearance('');
    setPresetClothing('');
    setPresetExpression('');
    setPresetOutfitId('');
    setPresetNote('');
    setPresetEnabled(true);
    setEditorOpen(true);
  };

  const openEdit = (item: CharacterAppearancePreset) => {
    setEditingPreset(item);
    setPresetName(item.name);
    setPresetWork(item.work);
    setPresetCategory(item.category);
    setPresetAppearance(item.appearance_tags.join(', '));
    setPresetClothing(item.clothing_tags.join(', '));
    setPresetExpression(item.expression_tags.join(', '));
    setPresetOutfitId(item.outfit_id || '');
    setPresetNote(item.note);
    setPresetEnabled(item.enabled);
    setEditorOpen(true);
  };

  const handleSavePreset = async () => {
    if (!presetName.trim()) {
      message.warning('请输入预设名称');
      return;
    }
    setSavingPreset(true);
    const payload = {
      name: presetName.trim(),
      work: presetWork.trim(),
      category: presetCategory,
      appearance_tags: parseTags(presetAppearance),
      clothing_tags: parseTags(presetClothing),
      expression_tags: parseTags(presetExpression),
      outfit_id: presetOutfitId.trim(),
      note: presetNote.trim(),
      enabled: presetEnabled,
    };
    try {
      if (editingPreset) {
        const { data } = await api.put<{ item: CharacterAppearancePreset; created_copy?: boolean }>(
          `/prompt-agent/appearance-presets/${encodeURIComponent(editingPreset.preset_id)}`,
          payload,
        );
        message.success(data.created_copy ? '内置预设已复制为用户预设' : '已保存预设');
      } else {
        await api.post('/prompt-agent/appearance-presets', payload);
        message.success('已新增预设');
      }
      setEditorOpen(false);
      loadPresets();
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '保存预设失败');
    } finally {
      setSavingPreset(false);
    }
  };

  const handleDuplicate = async (item: CharacterAppearancePreset) => {
    try {
      await api.post(`/prompt-agent/appearance-presets/${encodeURIComponent(item.preset_id)}/duplicate`, {
        name: `${item.name} 副本`,
      });
      message.success('已复制预设');
      loadPresets();
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '复制失败');
    }
  };

  const handleToggle = async (item: CharacterAppearancePreset, enabled: boolean) => {
    try {
      await api.put(`/prompt-agent/appearance-presets/${encodeURIComponent(item.preset_id)}`, {
        enabled,
      });
      message.success(enabled ? '已启用预设' : '已禁用预设');
      loadPresets();
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '更新失败');
    }
  };

  const handleDelete = async (item: CharacterAppearancePreset) => {
    try {
      await api.delete(`/prompt-agent/appearance-presets/${encodeURIComponent(item.preset_id)}`);
      message.success('已删除预设');
      loadPresets();
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '删除失败');
    }
  };

  const handleApplyPreset = async (item: CharacterAppearancePreset) => {
    if (!item.enabled) {
      message.warning('该预设已禁用');
      return;
    }
    setApplyingId(item.preset_id);
    try {
      const { data } = await api.post<CharacterAppearancePresetApplyResult>(
        `/prompt-agent/appearance-presets/${encodeURIComponent(item.preset_id)}/apply`,
        { version: item.version },
      );
      onApply({ scope, result: resultFromApply(data) });
      onClose();
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '应用预设失败');
    } finally {
      setApplyingId('');
    }
  };

  const applyQueryResult = (data: LegacyCharacterAppearanceResult) => {
    setDraft(data);
    setAppearanceText((data.appearance || []).join(', '));
    setClothingText((data.clothing || []).join(', '));
    setExpressionText((data.expression || []).join(', '));
    setNoteText(data.note || '');
  };

  const handleQuery = async () => {
    if (!characterName.trim()) {
      message.warning('请输入角色名');
      return;
    }
    setQueryLoading(true);
    try {
      const { data } = await api.get<LegacyCharacterAppearanceResult>('/prompt-agent/character-appearance', {
        params: { character_name: characterName.trim(), work: work.trim() },
      });
      applyQueryResult(data);
      message.success(data.source === 'cache' ? '已命中本地缓存' : '已生成草稿');
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '查询失败');
    } finally {
      setQueryLoading(false);
    }
  };

  const handleSaveDraft = async () => {
    if (!characterName.trim()) {
      message.warning('请输入角色名');
      return;
    }
    setSavingDraft(true);
    try {
      const { data } = await api.put<LegacyCharacterAppearanceResult>('/prompt-agent/character-appearance', {
        character_name: characterName.trim(),
        work: work.trim(),
        appearance: parseTags(appearanceText),
        clothing: parseTags(clothingText),
        expression: parseTags(expressionText),
        note: noteText.trim(),
        confidence: draft?.confidence ?? 0.95,
      });
      applyQueryResult(data);
      message.success('已保存人工修正');
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '保存失败');
    } finally {
      setSavingDraft(false);
    }
  };

  const handleImportLegacy = async () => {
    if (!characterName.trim()) {
      message.warning('请输入角色名');
      return;
    }
    try {
      await api.post('/prompt-agent/appearance-presets/import-character-cache', {
        character_name: characterName.trim(),
        work: work.trim(),
        category: '自由备注',
      });
      message.success('旧缓存已显式导入为外观预设');
      loadPresets();
      setActiveTab('presets');
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '导入旧缓存失败');
    }
  };

  const handleCreateFromDraft = () => {
    setEditingPreset(null);
    setPresetName(characterName.trim());
    setPresetWork(work.trim());
    setPresetCategory('自由备注');
    setPresetAppearance(appearanceText);
    setPresetClothing(clothingText);
    setPresetExpression(expressionText);
    setPresetNote(noteText);
    setPresetEnabled(true);
    setEditorOpen(true);
  };

  const handleApplyDraft = () => {
    const result: CharacterAppearanceResult = {
      character_name: characterName.trim(),
      work: work.trim(),
      appearance: parseTags(appearanceText),
      clothing: parseTags(clothingText),
      expression: parseTags(expressionText),
      full_prompt: draft?.full_prompt || '',
      confidence: draft?.confidence,
      source: draft?.source,
      note: noteText.trim(),
      corrected: draft?.corrected,
    };
    if (result.appearance.length + result.clothing.length + result.expression.length === 0) {
      message.warning('当前没有可填入的外貌、服装或表情标签');
      return;
    }
    onApply({ scope, result });
    onClose();
  };

  const presetLibrary = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Space wrap>
        <Input.Search
          allowClear
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="搜索名称、作品或标签"
          style={{ width: 230 }}
        />
        <Select
          allowClear
          showSearch
          value={workFilter || undefined}
          placeholder="作品"
          style={{ width: 180 }}
          options={works.map((value) => ({ label: value, value }))}
          optionFilterProp="label"
          onChange={(value) => setWorkFilter(value || '')}
        />
        <Select
          allowClear
          value={categoryFilter || undefined}
          placeholder="分类"
          style={{ width: 150 }}
          options={categories.map((value) => ({ label: value, value }))}
          onChange={(value) => setCategoryFilter(value || '')}
        />
        <Select
          allowClear
          value={sourceFilter || undefined}
          placeholder="来源"
          style={{ width: 140 }}
          options={sources.map((value) => ({ label: sourceLabel(value), value }))}
          onChange={(value) => setSourceFilter(value || '')}
        />
        <Select
          allowClear
          value={enabledFilter || undefined}
          placeholder="状态"
          style={{ width: 110 }}
          options={[
            { label: '已启用', value: 'enabled' },
            { label: '已禁用', value: 'disabled' },
          ]}
          onChange={(value) => setEnabledFilter(value || '')}
        />
        <Button icon={<ReloadOutlined />} loading={presetLoading} onClick={loadPresets}>
          刷新
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建
        </Button>
      </Space>
      <Space wrap>
        <span className="setting-label" style={{ marginBottom: 0 }}>
          应用范围
        </span>
        <Segmented
          value={scope}
          options={[
            { label: '当前角色', value: 'current' },
            { label: '全部角色', value: 'all' },
          ]}
          onChange={(value) => setScope(value as 'current' | 'all')}
        />
        <Tag>{presets.length} 项</Tag>
      </Space>
      {presets.length === 0 && !presetLoading ? (
        <div className="train-status-text">没有符合条件的外观预设。</div>
      ) : null}
      {presets.map((item) => {
        const hasThumbnail = Boolean(item.has_thumbnail && item.thumbnail_url);
        return (
          <div
            key={item.preset_id}
            style={{
              border: '1px solid #e5e7eb',
              borderRadius: 6,
              padding: 10,
              opacity: item.enabled ? 1 : 0.62,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, minWidth: 0 }}>
                {onManageThumbnail ? (
                  <div style={{ width: 72, flex: '0 0 72px' }}>
                    {hasThumbnail ? (
                      <Image
                        src={item.thumbnail_url || ''}
                        alt={`${item.name}缩略图`}
                        width={72}
                        height={128}
                        preview={false}
                        style={{
                          objectFit: 'cover',
                          borderRadius: 6,
                          border: '1px solid #e5e7eb',
                        }}
                      />
                    ) : (
                      <div
                        style={{
                          width: 72,
                          height: 128,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          border: '1px dashed #d1d5db',
                          borderRadius: 6,
                          color: '#8c8c8c',
                          fontSize: 12,
                        }}
                      >
                        无缩略图
                      </div>
                    )}
                  </div>
                ) : null}
                <div style={{ minWidth: 0 }}>
                  <Space wrap>
                    <strong>{item.name}</strong>
                    {item.work ? <Tag>{item.work}</Tag> : null}
                    <Tag color="blue">{item.category}</Tag>
                    <Tag>{sourceLabel(item.source)}</Tag>
                    {!item.enabled ? <Tag color="red">已禁用</Tag> : null}
                    {hasThumbnail && item.thumbnail_stale ? (
                      <Tag color="orange">缩略图已过期</Tag>
                    ) : null}
                    {!hasThumbnail ? <Tag>无缩略图</Tag> : null}
                  </Space>
                  <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div>
                      <span className="setting-label" style={{ marginBottom: 0 }}>
                        外貌：
                      </span>
                      {item.appearance_tags.join(', ') || '无'}
                    </div>
                    <div>
                      <span className="setting-label" style={{ marginBottom: 0 }}>
                        服装：
                      </span>
                      {item.clothing_tags.join(', ') || '无'}
                    </div>
                    <div>
                      <span className="setting-label" style={{ marginBottom: 0 }}>
                        默认服装：
                      </span>
                      {item.outfit_name || item.outfit_id || '未关联'}
                    </div>
                    <div>
                      <span className="setting-label" style={{ marginBottom: 0 }}>
                        表情：
                      </span>
                      {item.expression_tags.join(', ') || '无'}
                    </div>
                    {item.note ? <div className="help">{item.note}</div> : null}
                  </div>
                </div>
              </div>
              <Space wrap>
                <Button
                  type="primary"
                  size="small"
                  loading={applyingId === item.preset_id}
                  disabled={!item.enabled}
                  onClick={() => void handleApplyPreset(item)}
                >
                  应用
                </Button>
                {onManageThumbnail ? (
                  <Tooltip title={item.thumbnail_stale ? '管理缩略图；当前缩略图已过期' : '管理缩略图'}>
                    <Button
                      size="small"
                      icon={<PictureOutlined />}
                      onClick={() =>
                        onManageThumbnail({
                          presetType: 'character',
                          presetId: item.preset_id,
                          label: item.name,
                        })
                      }
                    >
                      工坊
                    </Button>
                  </Tooltip>
                ) : null}
                <Tooltip title="编辑；内置模板会复制为用户预设">
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(item)} />
                </Tooltip>
                <Tooltip title="复制">
                  <Button size="small" icon={<CopyOutlined />} onClick={() => void handleDuplicate(item)} />
                </Tooltip>
                <Switch
                  size="small"
                  checked={item.enabled}
                  onChange={(checked) => void handleToggle(item, checked)}
                />
                <Popconfirm
                  title={`确认删除「${item.name}」？`}
                  onConfirm={() => void handleDelete(item)}
                  disabled={item.source === 'builtin'}
                >
                  <Tooltip title={item.source === 'builtin' ? '内置模板不能删除' : '删除'}>
                    <Button size="small" danger icon={<DeleteOutlined />} disabled={item.source === 'builtin'} />
                  </Tooltip>
                </Popconfirm>
              </Space>
            </div>
          </div>
        );
      })}
    </div>
  );

  const legacyQuery = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="settings-grid" style={{ marginTop: 0 }}>
        <div className="setting-field">
          <span className="setting-label">角色名</span>
          <Input value={characterName} onChange={(event) => setCharacterName(event.target.value)} placeholder="例如：蓝砚" />
        </div>
        <div className="setting-field">
          <span className="setting-label">所属作品</span>
          <Input value={work} onChange={(event) => setWork(event.target.value)} placeholder="例如：原神（可留空）" />
        </div>
      </div>
      <Space wrap>
        <Button type="primary" loading={queryLoading} onClick={() => void handleQuery()}>
          查询/生成
        </Button>
        <span className="setting-label" style={{ marginBottom: 0 }}>
          应用范围
        </span>
        <Segmented
          value={scope}
          options={[
            { label: '当前角色', value: 'current' },
            { label: '全部角色', value: 'all' },
          ]}
          onChange={(value) => setScope(value as 'current' | 'all')}
        />
        {draft ? (
          <Tag color={draft.source === 'cache' ? 'blue' : draft.source === 'manual' ? 'green' : 'orange'}>
            {draft.source === 'cache' ? '本地缓存' : draft.source === 'manual' ? '人工修正' : 'LLM 草稿'}
          </Tag>
        ) : null}
        {draft?.confidence != null ? <Tag>置信度 {Math.round(draft.confidence * 100)}%</Tag> : null}
      </Space>
      {draft ? (
        <>
          {draft.source === 'llm' && !draft.corrected && draft.appearance.length === 0 ? (
            <div className="help">{draft.note || '模型未给出可靠外观，可直接编辑并保存人工修正。'}</div>
          ) : draft.note ? (
            <div className="help">{draft.note}</div>
          ) : null}
          <div className="setting-field">
            <span className="setting-label">外貌标签（不含动作/场景/质量词）</span>
            <Input.TextArea rows={3} value={appearanceText} onChange={(event) => setAppearanceText(event.target.value)} />
          </div>
          <div className="setting-field">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span className="setting-label" style={{ marginBottom: 0 }}>
                默认服装标签
              </span>
              <Button size="small" onClick={() => setClothingPresetOpen(true)}>
                从预设选择
              </Button>
            </div>
            <Input.TextArea rows={2} value={clothingText} onChange={(event) => setClothingText(event.target.value)} />
          </div>
          <div className="setting-field">
            <span className="setting-label">表情标签</span>
            <Input.TextArea rows={2} value={expressionText} onChange={(event) => setExpressionText(event.target.value)} />
          </div>
          <div className="setting-field">
            <span className="setting-label">备注/修正说明</span>
            <Input.TextArea rows={2} value={noteText} onChange={(event) => setNoteText(event.target.value)} />
          </div>
          <Space wrap>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleApplyDraft}>
              填入目标角色
            </Button>
            <Button loading={savingDraft} icon={<SaveOutlined />} onClick={() => void handleSaveDraft()}>
              保存人工修正
            </Button>
            <Button onClick={handleCreateFromDraft}>另存为外观预设</Button>
            <Button onClick={() => void handleImportLegacy()}>导入旧缓存为预设</Button>
          </Space>
        </>
      ) : (
        <div className="train-status-text">
          先查询旧角色外观草稿；结果必须人工确认后才能写入目标角色，低置信结果不会自动应用。
        </div>
      )}
    </div>
  );

  return (
    <>
      <Modal title={title} open={open} onCancel={onClose} footer={null} width={900}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            { key: 'presets', label: '外观预设库', children: presetLibrary },
            { key: 'legacy', label: '查询与人工修正', children: legacyQuery },
          ]}
        />
      </Modal>
      <Modal
        title={editingPreset ? '编辑外观预设' : '新增外观预设'}
        open={editorOpen}
        onOk={() => void handleSavePreset()}
        onCancel={() => setEditorOpen(false)}
        confirmLoading={savingPreset}
        width={720}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap>
            <Input
              value={presetName}
              onChange={(event) => setPresetName(event.target.value)}
              placeholder="预设名称"
              style={{ width: 220 }}
            />
            <Input
              value={presetWork}
              onChange={(event) => setPresetWork(event.target.value)}
              placeholder="所属作品"
              style={{ width: 180 }}
            />
            <Select
              value={presetCategory}
              style={{ width: 160 }}
              options={(categories.length ? categories : ['自由备注']).map((value) => ({ label: value, value }))}
              onChange={setPresetCategory}
            />
            <Switch
              checked={presetEnabled}
              onChange={setPresetEnabled}
              checkedChildren="启用"
              unCheckedChildren="禁用"
            />
          </Space>
          <div className="setting-field">
            <span className="setting-label">外貌标签</span>
            <Input.TextArea rows={3} value={presetAppearance} onChange={(event) => setPresetAppearance(event.target.value)} />
          </div>
          <div className="setting-field">
            <span className="setting-label">服装标签</span>
            <Input.TextArea rows={2} value={presetClothing} onChange={(event) => setPresetClothing(event.target.value)} />
          </div>
          <div className="setting-field">
            <span className="setting-label">默认服装预设 ID</span>
            <Input
              value={presetOutfitId}
              onChange={(event) => setPresetOutfitId(event.target.value)}
              placeholder="例如 outfit_genshin_columbina_default"
            />
          </div>
          <div className="setting-field">
            <span className="setting-label">表情标签</span>
            <Input.TextArea rows={2} value={presetExpression} onChange={(event) => setPresetExpression(event.target.value)} />
          </div>
          <div className="setting-field">
            <span className="setting-label">备注</span>
            <Input.TextArea rows={2} value={presetNote} onChange={(event) => setPresetNote(event.target.value)} />
          </div>
        </Space>
      </Modal>
      <ClothingPresetsModal
        open={clothingPresetOpen}
        onClose={() => setClothingPresetOpen(false)}
        onInsert={(preset) => {
          setClothingText(Array.from(new Set([...parseTags(clothingText), ...preset.tags])).join(', '));
          setClothingPresetOpen(false);
          message.success(`已加入默认服装：${preset.label}`);
        }}
      />
    </>
  );
}
