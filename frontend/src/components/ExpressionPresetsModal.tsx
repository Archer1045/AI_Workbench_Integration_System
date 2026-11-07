import { SearchOutlined } from '@ant-design/icons';
import { Button, Empty, Input, Modal, Select, Space, Spin, Tag, Tooltip } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { api, type ExpressionPreset, type PresetScope } from '../api';
import { isPresetHidden, PRESET_SCOPE_OPTIONS } from '../presetComposition';
import { settingsStore } from '../stores/settings';

interface ExpressionPresetResponse {
  items: ExpressionPreset[];
  total: number;
  categories: string[];
  intensities: string[];
  character_scopes: string[];
}

export default function ExpressionPresetsModal({
  open,
  onClose,
  onInsert,
}: {
  open: boolean;
  onClose: () => void;
  onInsert: (preset: ExpressionPreset, scope: PresetScope) => void;
}) {
  const { restrictionEnabled } = settingsStore;
  const [items, setItems] = useState<ExpressionPreset[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [intensities, setIntensities] = useState<string[]>([]);
  const [characterScopes, setCharacterScopes] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState('');
  const [intensity, setIntensity] = useState('');
  const [characterScope, setCharacterScope] = useState('');
  const [scope, setScope] = useState<PresetScope>('all');

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get<ExpressionPresetResponse>('/prompt-agent/expression-presets')
      .then((response) => {
        setItems(response.data.items || []);
        setCategories(response.data.categories || []);
        setIntensities(response.data.intensities || []);
        setCharacterScopes(response.data.character_scopes || []);
      })
      .catch(() => {
        setItems([]);
        setCategories([]);
        setIntensities([]);
        setCharacterScopes([]);
      })
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (open) return;
    setKeyword('');
    setCategory('');
    setIntensity('');
    setCharacterScope('');
    setScope('all');
  }, [open]);

  const availableItems = useMemo(
    () => items.filter((item) => !isPresetHidden(item, restrictionEnabled)),
    [items, restrictionEnabled],
  );
  const filteredItems = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return availableItems.filter((item) => {
      const haystack = [
        item.id,
        item.label,
        item.translation,
        item.category,
        item.intensity,
        ...(item.aliases || []),
        ...(item.character_scope || []),
        ...item.tags,
      ]
        .join(' ')
        .toLowerCase();
      return (
        (!query || haystack.includes(query)) &&
        (!category || item.category === category) &&
        (!intensity || item.intensity === intensity) &&
        (!characterScope || item.character_scope.includes(characterScope))
      );
    });
  }, [availableItems, category, characterScope, intensity, keyword]);

  const hasFilters =
    Boolean(keyword || category || intensity || characterScope);

  return (
    <Modal
      title="表情预设"
      open={open}
      onCancel={onClose}
      footer={null}
      width={980}
      className="expression-presets-modal"
    >
      <div className="expression-presets-toolbar">
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索表情、说明或标签"
          aria-label="搜索表情预设"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
        <Select
          allowClear
          placeholder="情绪分类"
          value={category || undefined}
          options={categories.map((value) => ({ label: value, value }))}
          onChange={(value) => setCategory(value || '')}
        />
        <Select
          allowClear
          placeholder="强度"
          value={intensity || undefined}
          options={intensities.map((value) => ({ label: value, value }))}
          onChange={(value) => setIntensity(value || '')}
        />
        <Select
          allowClear
          placeholder="适用角色"
          value={characterScope || undefined}
          options={characterScopes.map((value) => ({ label: value, value }))}
          onChange={(value) => setCharacterScope(value || '')}
        />
        <Tooltip title="结构化模式下写入对应角色的表情块；原始文本模式追加到当前组。">
          <Select
            value={scope}
            options={PRESET_SCOPE_OPTIONS}
            onChange={setScope}
          />
        </Tooltip>
        <Tag color="blue">
          当前 {filteredItems.length} / {availableItems.length}
        </Tag>
        <Button
          size="small"
          disabled={!hasFilters}
          onClick={() => {
            setKeyword('');
            setCategory('');
            setIntensity('');
            setCharacterScope('');
          }}
        >
          清空筛选
        </Button>
      </div>

      <Spin spinning={loading}>
        {!loading && filteredItems.length === 0 ? (
          <Empty description="没有符合条件的表情预设" />
        ) : (
          <div className="expression-presets-grid">
            {filteredItems.map((preset) => (
              <article className="expression-preset-card" key={preset.id}>
                <div className="expression-preset-card-heading">
                  <div>
                    <strong>{preset.label}</strong>
                    <span>{preset.translation}</span>
                  </div>
                  <Tag color={preset.intensity === '强' ? 'volcano' : 'gold'}>
                    {preset.intensity}
                  </Tag>
                </div>
                <div className="expression-preset-tags">
                  {preset.tags.map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </div>
                <div className="expression-preset-card-footer">
                  <Space size={4} wrap>
                    <Tag color="blue">{preset.category}</Tag>
                    <Tag>{preset.character_scope.join(' / ')}</Tag>
                  </Space>
                  <Button
                    size="small"
                    type="primary"
                    aria-label={`插入 ${preset.label}`}
                    onClick={() => onInsert(preset, scope)}
                  >
                    插入
                  </Button>
                </div>
              </article>
            ))}
          </div>
        )}
      </Spin>
    </Modal>
  );
}
