import { PictureOutlined } from '@ant-design/icons';
import { Button, Image, Input, Modal, Segmented, Select, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useMemo, useState } from 'react';
import { api, type PresetScope, type ScenePreset } from '../api';
import {
  formatScenePresetInsert,
  isPresetHidden,
  PRESET_SCOPE_OPTIONS,
  type ScenePeoplePolicy,
} from '../presetComposition';
import type { PresetAssetSelection } from '../stores/presetAssetStore';
import { settingsStore } from '../stores/settings';
import PresetCategoryFilter, {
  matchesPresetCategory,
  presetCategoryGroup,
  presetSubcategory,
  sortPresetItems,
} from './PresetCategoryFilter';

export default function ScenePresetsModal({
  open,
  onClose,
  onInsert,
  onManageThumbnail,
}: {
  open: boolean;
  onClose: () => void;
  onInsert: (
    preset: ScenePreset,
    scope: PresetScope,
    peoplePolicy: ScenePeoplePolicy,
  ) => void;
  onManageThumbnail?: (selection: PresetAssetSelection) => void;
}) {
  const { restrictionEnabled } = settingsStore;
  const [items, setItems] = useState<ScenePreset[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [categoryGroup, setCategoryGroup] = useState('');
  const [subcategory, setSubcategory] = useState('');
  const [intensity, setIntensity] = useState('');
  const [setting, setSetting] = useState('');
  const [people, setPeople] = useState('');
  const [scope, setScope] = useState<PresetScope>('all');
  const [peoplePolicy, setPeoplePolicy] = useState<ScenePeoplePolicy>('occupied');

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get<{ items: ScenePreset[] }>('/prompt-agent/scene-presets')
      .then((res) => setItems(sortPresetItems(res.data.items || [])))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (open) return;
    setKeyword('');
    setCategoryGroup('');
    setSubcategory('');
    setIntensity('');
    setSetting('');
    setPeople('');
    setScope('all');
    setPeoplePolicy('occupied');
  }, [open]);

  const availableItems = useMemo(
    () => items.filter((item) => !isPresetHidden(item, restrictionEnabled)),
    [items, restrictionEnabled],
  );
  const intensityOptions = Array.from(new Set(availableItems.map((item) => item.intensity).filter(Boolean)));
  const settingOptions = Array.from(new Set(availableItems.map((item) => item.setting).filter(Boolean)));
  const peopleOptions = Array.from(new Set(availableItems.map((item) => item.people).filter(Boolean)));
  const keywordLower = keyword.trim().toLowerCase();
  const filteredItems = availableItems.filter((item) => {
    const haystack = `${item.label} ${item.translation} ${item.category} ${presetCategoryGroup(item)} ${presetSubcategory(item)} ${item.setting} ${item.people} ${item.equipment.join(' ')} ${item.tags.join(' ')}`.toLowerCase();
    return (
      (!keywordLower || haystack.includes(keywordLower)) &&
      matchesPresetCategory(item, categoryGroup, subcategory) &&
      (!intensity || item.intensity === intensity) &&
      (!setting || item.setting === setting) &&
      (!people || item.people === people)
    );
  });

  const columns: ColumnsType<ScenePreset> = [
    {
      title: '预览',
      dataIndex: 'image',
      key: 'image',
      width: 112,
      render: (value: string | null | undefined, record) =>
        value ? (
          <Image
            src={value}
            alt={record.label}
            width={96}
            height={54}
            style={{ objectFit: 'cover', borderRadius: 4 }}
            preview={{ mask: false }}
          />
        ) : (
          <span>-</span>
        ),
    },
    {
      title: '分类',
      key: 'category',
      width: 170,
      render: (_, record) => (
        <Space size={4} wrap>
          <Tag color="blue">{presetCategoryGroup(record)}</Tag>
          <Tag>{presetSubcategory(record)}</Tag>
        </Space>
      ),
    },
    { title: '场景', dataIndex: 'label', key: 'label', width: 130 },
    {
      title: '说明',
      dataIndex: 'translation',
      key: 'translation',
      width: 280,
      render: (value: string) => <span style={{ wordBreak: 'break-word' }}>{value}</span>,
    },
    {
      title: '属性',
      key: 'meta',
      width: 210,
      render: (_, record) => (
        <Space size={4} wrap>
          <Tag>{record.setting}</Tag>
          <Tag>{record.people}</Tag>
          <Tag>{record.intensity}</Tag>
          {record.rating === 'R18' ? <Tag color="red">R18</Tag> : null}
        </Space>
      ),
    },
    {
      title: '器材 / 光线',
      key: 'equipment',
      width: 190,
      render: (_, record) => (
        <Tooltip title={`${record.equipment.join(', ')} / ${record.camera} / ${record.lighting}`}>
          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {record.equipment.join(', ')} / {record.lighting}
          </div>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: onManageThumbnail ? 126 : 76,
      render: (_, record) => (
        <Space size={0}>
          <Button
            size="small"
            type="link"
            onClick={() => onInsert(record, scope, peoplePolicy)}
          >
            插入
          </Button>
          {onManageThumbnail ? (
            <Tooltip title="管理缩略图">
              <Button
                size="small"
                type="link"
                icon={<PictureOutlined />}
                onClick={() => {
                  onManageThumbnail({
                    presetType: 'scene',
                    presetId: record.id,
                    label: record.label,
                  });
                  onClose();
                }}
              />
            </Tooltip>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <Modal title="场景预设" open={open} onCancel={onClose} footer={null} width={1240}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <Input
          allowClear
          placeholder="搜索场景、说明或标签"
          style={{ width: 220 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Tooltip title="默认移除 no people 等空场景限制；只有明确选择“空场景”时才保留无人物提示。">
          <Segmented
            value={peoplePolicy}
            options={[
              { label: '包含角色', value: 'occupied' },
              { label: '空场景', value: 'empty' },
            ]}
            onChange={(value) => setPeoplePolicy(value as ScenePeoplePolicy)}
          />
        </Tooltip>
        <PresetCategoryFilter
          items={availableItems}
          categoryGroup={categoryGroup}
          subcategory={subcategory}
          onCategoryGroupChange={(value) => {
            setCategoryGroup(value);
            setSubcategory('');
          }}
          onSubcategoryChange={setSubcategory}
        />
        <Select
          allowClear
          placeholder="强度"
          style={{ width: 100 }}
          value={intensity || undefined}
          options={intensityOptions.map((value) => ({ label: value, value }))}
          onChange={(value) => setIntensity(value || '')}
        />
        <Select
          allowClear
          placeholder="环境"
          style={{ width: 110 }}
          value={setting || undefined}
          options={settingOptions.map((value) => ({ label: value, value }))}
          onChange={(value) => setSetting(value || '')}
        />
        <Select
          allowClear
          placeholder="人数"
          style={{ width: 100 }}
          value={people || undefined}
          options={peopleOptions.map((value) => ({ label: value, value }))}
          onChange={(value) => setPeople(value || '')}
        />
        <Select
          style={{ width: 112 }}
          value={scope}
          options={PRESET_SCOPE_OPTIONS}
          onChange={setScope}
        />
        <Tag color="blue">当前 {filteredItems.length} / {availableItems.length}</Tag>
        <Button
          size="small"
          onClick={() => {
            setKeyword('');
            setCategoryGroup('');
            setSubcategory('');
            setIntensity('');
            setSetting('');
            setPeople('');
          }}
          disabled={!keyword && !categoryGroup && !subcategory && !intensity && !setting && !people}
        >
          清空筛选
        </Button>
      </div>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={filteredItems}
        loading={loading}
        size="small"
        pagination={false}
        tableLayout="fixed"
        scroll={{ y: 430 }}
      />
      <div className="help" style={{ marginTop: 8 }}>
        当前插入格式：
        {formatScenePresetInsert(
          {
            tags: ['scene tags'],
            draw_prompt: 'scene prompt',
            occupied_scene_prompt: 'scene prompt',
            empty_scene_prompt: 'scene prompt, no people',
          },
          scope,
          peoplePolicy,
        )}
      </div>
    </Modal>
  );
}
