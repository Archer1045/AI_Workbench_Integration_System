import { SearchOutlined } from '@ant-design/icons';
import { Button, Empty, Input, Modal, Select, Space, Spin, Tag, Tooltip } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { api, type PresetScope, type WaterPreset } from '../api';
import { PRESET_SCOPE_OPTIONS } from '../presetComposition';

interface WaterPresetResponse {
  items: WaterPreset[];
  categories: string[];
  water_levels: string[];
  targets: string[];
}

export default function WaterPresetsModal({
  open,
  onClose,
  onInsert,
}: {
  open: boolean;
  onClose: () => void;
  onInsert: (preset: WaterPreset, scope: PresetScope) => void;
}) {
  const [items, setItems] = useState<WaterPreset[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [waterLevels, setWaterLevels] = useState<string[]>([]);
  const [targets, setTargets] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState('');
  const [waterLevel, setWaterLevel] = useState('');
  const [target, setTarget] = useState('');
  const [scope, setScope] = useState<PresetScope>('all');

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get<WaterPresetResponse>('/prompt-agent/water-presets')
      .then((response) => {
        setItems(response.data.items || []);
        setCategories(response.data.categories || []);
        setWaterLevels(response.data.water_levels || []);
        setTargets(response.data.targets || []);
      })
      .catch(() => {
        setItems([]);
        setCategories([]);
        setWaterLevels([]);
        setTargets([]);
      })
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (open) return;
    setKeyword('');
    setCategory('');
    setWaterLevel('');
    setTarget('');
    setScope('all');
  }, [open]);

  const filteredItems = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return items.filter((item) => {
      const haystack = [
        item.id,
        item.label,
        item.translation,
        item.category,
        item.water_level,
        item.target,
        ...item.tags,
      ]
        .join(' ')
        .toLowerCase();
      return (
        (!query || haystack.includes(query)) &&
        (!category || item.category === category) &&
        (!waterLevel || item.water_level === waterLevel) &&
        (!target || item.target === target)
      );
    });
  }, [category, items, keyword, target, waterLevel]);

  const hasFilters = Boolean(keyword || category || waterLevel || target);

  return (
    <Modal
      title="水中玩法"
      open={open}
      onCancel={onClose}
      footer={null}
      width={980}
      className="water-presets-modal"
    >
      <div className="water-presets-toolbar">
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索水中状态、说明或标签"
          aria-label="搜索水中玩法"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
        <Select
          allowClear
          placeholder="分类"
          value={category || undefined}
          options={categories.map((value) => ({ label: value, value }))}
          onChange={(value) => setCategory(value || '')}
        />
        <Select
          allowClear
          placeholder="水深"
          value={waterLevel || undefined}
          options={waterLevels.map((value) => ({ label: value, value }))}
          onChange={(value) => setWaterLevel(value || '')}
        />
        <Select
          allowClear
          placeholder="作用对象"
          value={target || undefined}
          options={targets.map((value) => ({ label: value, value }))}
          onChange={(value) => setTarget(value || '')}
        />
        <Tooltip title="角色修饰写入目标角色状态块；环境修饰写入全局场景块。">
          <Select
            value={scope}
            options={PRESET_SCOPE_OPTIONS}
            onChange={setScope}
          />
        </Tooltip>
        <Tag color="blue">
          当前 {filteredItems.length} / {items.length}
        </Tag>
        <Button
          size="small"
          disabled={!hasFilters}
          onClick={() => {
            setKeyword('');
            setCategory('');
            setWaterLevel('');
            setTarget('');
          }}
        >
          清空筛选
        </Button>
      </div>

      <Spin spinning={loading}>
        {!loading && filteredItems.length === 0 ? (
          <Empty description="没有符合条件的水中玩法" />
        ) : (
          <div className="water-presets-grid">
            {filteredItems.map((preset) => (
              <article className="water-preset-card" key={preset.id}>
                <div className="water-preset-heading">
                  <div>
                    <strong>{preset.label}</strong>
                    <span>{preset.translation}</span>
                  </div>
                  <Tag color={preset.target === '环境' ? 'cyan' : 'blue'}>
                    {preset.target}
                  </Tag>
                </div>
                <div className="water-preset-tags">
                  {preset.tags.map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </div>
                <div className="water-preset-footer">
                  <Space size={4} wrap>
                    <Tag color="blue">{preset.category}</Tag>
                    <Tag>{preset.water_level}</Tag>
                    <Tag>{preset.intensity}</Tag>
                  </Space>
                  <Button
                    size="small"
                    type="primary"
                    aria-label={`插入 ${preset.label}`}
                    onClick={() => onInsert(preset, preset.target === '环境' ? 'all' : scope)}
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
