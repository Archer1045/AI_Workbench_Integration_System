// 内置服装预设：搜索、筛选并插入到第一组提示词
import { PictureOutlined } from '@ant-design/icons';
import { Button, Image, Input, Modal, Select, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useMemo, useState } from 'react';
import { api, type ClothingPreset } from '../api';
import { CLOTHING_SCOPE_OPTIONS, type ClothingScope } from '../clothingPresets';
import { isPresetHidden } from '../presetComposition';
import type { PresetAssetSelection } from '../stores/presetAssetStore';
import { settingsStore } from '../stores/settings';
import PresetCategoryFilter, {
  matchesPresetCategory,
  presetCategoryGroup,
  presetSubcategory,
  sortPresetItems,
} from './PresetCategoryFilter';

export default function ClothingPresetsModal({
  open,
  onClose,
  onInsert,
  onManageThumbnail,
}: {
  open: boolean;
  onClose: () => void;
  onInsert: (preset: ClothingPreset, scope: ClothingScope) => void;
  onManageThumbnail?: (selection: PresetAssetSelection) => void;
}) {
  const { restrictionEnabled } = settingsStore;
  const [items, setItems] = useState<ClothingPreset[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [categoryGroup, setCategoryGroup] = useState('');
  const [subcategory, setSubcategory] = useState('');
  const [gender, setGender] = useState('');
  const [part, setPart] = useState('');
  const [rating, setRating] = useState('');
  const [material, setMaterial] = useState('');
  const [layerState, setLayerState] = useState('');
  const [intensity, setIntensity] = useState('');
  const [scope, setScope] = useState<ClothingScope>('all');

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get<{ items: ClothingPreset[] }>('/prompt-agent/clothing-presets')
      .then((res) => setItems(sortPresetItems(res.data.items || [])))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (!open) {
      setKeyword('');
      setCategoryGroup('');
      setSubcategory('');
      setGender('');
      setPart('');
      setRating('');
      setMaterial('');
      setLayerState('');
      setIntensity('');
      setScope('all');
    }
  }, [open]);

  const availableItems = useMemo(
    () => items.filter((item) => !isPresetHidden(item, restrictionEnabled)),
    [items, restrictionEnabled],
  );
  const genderOptions = Array.from(new Set(availableItems.map((item) => item.gender)));
  const partOptions = Array.from(new Set(availableItems.map((item) => item.part)));
  const materialOptions = Array.from(new Set(availableItems.flatMap((item) => item.materials || [])));
  const layerStateOptions = Array.from(new Set(availableItems.map((item) => item.layer_state || '').filter(Boolean)));
  const intensityOptions = Array.from(new Set(availableItems.map((item) => item.intensity || '').filter(Boolean)));
  const keywordLower = keyword.trim().toLowerCase();
  const filteredItems = availableItems.filter((item) => {
    const haystack = `${item.label} ${item.translation} ${item.category} ${presetCategoryGroup(item)} ${presetSubcategory(item)} ${item.gender} ${item.part} ${(item.materials || []).join(' ')} ${(item.accessories || []).join(' ')} ${(item.aliases || []).join(' ')} ${item.tags.join(' ')}`.toLowerCase();
    return (
      (!keywordLower || haystack.includes(keywordLower)) &&
      matchesPresetCategory(item, categoryGroup, subcategory) &&
      (!gender || item.gender === gender) &&
      (!part || item.part === part) &&
      (!rating || item.rating === rating) &&
      (!material || (item.materials || []).includes(material)) &&
      (!layerState || item.layer_state === layerState) &&
      (!intensity || item.intensity === intensity)
    );
  });

  const columns: ColumnsType<ClothingPreset> = [
    {
      title: '预览',
      dataIndex: 'image',
      key: 'image',
      width: 64,
      render: (value: string | null | undefined) =>
        value ? (
          <Image
            src={value}
            width={48}
            height={85}
            style={{ objectFit: 'cover', borderRadius: 4 }}
            preview={{ mask: false }}
          />
        ) : (
          <span>-</span>
        ),
    },
    {
      title: '名称',
      dataIndex: 'label',
      key: 'label',
      width: 150,
      render: (value: string, record) => (
        <Space size={4}>
          <span>{value}</span>
          {record.nsfw ? <Tag color="red">R18</Tag> : null}
        </Space>
      ),
    },
    {
      title: '说明',
      dataIndex: 'translation',
      key: 'translation',
      width: 230,
      render: (value: string) => (
        <Tooltip title={value}>
          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</div>
        </Tooltip>
      ),
    },
    {
      title: '属性',
      key: 'meta',
      width: 150,
      render: (_, record) => (
        <Space size={4} wrap>
          <Tag color="blue">{presetCategoryGroup(record)}</Tag>
          <Tag>{presetSubcategory(record)}</Tag>
          <Tag>{record.gender}</Tag>
          <Tag>{record.part}</Tag>
          {record.layer_state ? <Tag>{record.layer_state}</Tag> : null}
          {record.intensity ? <Tag>{record.intensity}</Tag> : null}
        </Space>
      ),
    },
    {
      title: '材质',
      dataIndex: 'materials',
      key: 'materials',
      width: 150,
      render: (value: string[] | undefined) => (
        <Tooltip title={(value || []).join(', ')}>
          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {(value || []).join(', ') || '-'}
          </div>
        </Tooltip>
      ),
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      render: (value: string[]) => (
        <Tooltip title={value.join(', ')}>
          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value.join(', ')}</div>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: onManageThumbnail ? 126 : 76,
      render: (_, record) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => onInsert(record, scope)}>
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
                    presetType: 'clothing',
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
    <Modal title="服装预设" open={open} onCancel={onClose} footer={null} width={1040}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <Input
          allowClear
          placeholder="搜索名称、说明或标签"
          style={{ width: 220 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
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
          placeholder="适用性别"
          style={{ width: 120 }}
          value={gender || undefined}
          options={genderOptions.map((value) => ({ label: value, value }))}
          onChange={(value) => setGender(value || '')}
        />
        <Select
          allowClear
          placeholder="部位"
          style={{ width: 120 }}
          value={part || undefined}
          options={partOptions.map((value) => ({ label: value, value }))}
          onChange={(value) => setPart(value || '')}
        />
        <Select
          allowClear
          placeholder="材质"
          style={{ width: 120 }}
          value={material || undefined}
          options={materialOptions.map((value) => ({ label: value, value }))}
          onChange={(value) => setMaterial(value || '')}
        />
        <Select
          allowClear
          placeholder="层次状态"
          style={{ width: 120 }}
          value={layerState || undefined}
          options={layerStateOptions.map((value) => ({ label: value, value }))}
          onChange={(value) => setLayerState(value || '')}
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
          placeholder="内容分级"
          style={{ width: 120 }}
          value={rating || undefined}
          options={(restrictionEnabled ? ['普通'] : ['普通', 'R18']).map((value) => ({
            label: value,
            value,
          }))}
          onChange={(value) => setRating(value || '')}
        />
        <Select
          style={{ width: 112 }}
          value={scope}
          options={CLOTHING_SCOPE_OPTIONS}
          onChange={setScope}
        />
        <Tag color="blue">
          当前 {filteredItems.length} / {availableItems.length}
        </Tag>
        <Button
          size="small"
          onClick={() => {
            setKeyword('');
            setCategoryGroup('');
            setSubcategory('');
            setGender('');
            setPart('');
            setRating('');
            setMaterial('');
            setLayerState('');
            setIntensity('');
          }}
          disabled={!keyword && !categoryGroup && !subcategory && !gender && !part && !rating && !material && !layerState && !intensity}
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
        scroll={{ y: 420 }}
      />
    </Modal>
  );
}
