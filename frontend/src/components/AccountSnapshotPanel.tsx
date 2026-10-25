import {
  Alert,
  Button,
  Card,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import CombatInventoryPanel from './CombatInventoryPanel';
import {
  deleteAccountMaterial,
  deleteAccountServant,
  listAccountMaterials,
  listAccountServants,
  loadAccountSummary,
  saveAccountMaterial,
  saveAccountServant,
  type AccountSnapshotSummary,
  type ConfidenceState,
  type MaterialRecord,
  type ServantRecord,
} from '../stores/accountSnapshot';

const classOptions = [
  'Saber',
  'Archer',
  'Lancer',
  'Rider',
  'Caster',
  'Assassin',
  'Berserker',
  'Ruler',
  'Avenger',
  'Alterego',
  'MoonCancer',
  'Foreigner',
  'Pretender',
  'Beast',
  'Shielder',
].map((value) => ({ value, label: value }));

const confidenceOptions: Array<{ value: ConfidenceState; label: string }> = [
  { value: 'confirmed', label: '已确认' },
  { value: 'candidate', label: '候选' },
  { value: 'unknown', label: '未知' },
];

const materialCategories = [
  '棋子',
  '辉石',
  '魔石',
  '秘石',
  '技能素材',
  '灵基素材',
  '活动素材',
  '其他',
].map((value) => ({ value, label: value }));

function blankServant(): ServantRecord {
  return {
    record_id: `draft-servant-${Date.now()}-${Math.random()}`,
    name: '',
    class_name: '',
    rarity: null,
    level: null,
    max_level: null,
    np_level: null,
    skill_1: null,
    skill_2: null,
    skill_3: null,
    append_2: null,
    source: 'manual',
    confidence: 'confirmed',
    notes: '',
    updated_at: '',
  };
}

function blankMaterial(): MaterialRecord {
  return {
    record_id: `draft-material-${Date.now()}-${Math.random()}`,
    name: '',
    category: '',
    quantity: 0,
    reserve_quantity: 0,
    source: 'manual',
    confidence: 'confirmed',
    notes: '',
    updated_at: '',
  };
}

function confidenceTag(value: ConfidenceState) {
  if (value === 'confirmed') return <Tag color="green">已确认</Tag>;
  if (value === 'candidate') return <Tag color="orange">候选</Tag>;
  return <Tag>未知</Tag>;
}
export default function AccountSnapshotPanel() {
  const [messageApi, contextHolder] = message.useMessage();
  const [servants, setServants] = useState<ServantRecord[]>([]);
  const [materials, setMaterials] = useState<MaterialRecord[]>([]);
  const [summary, setSummary] = useState<AccountSnapshotSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [servantRows, materialRows, nextSummary] = await Promise.all([
        listAccountServants(),
        listAccountMaterials(),
        loadAccountSummary(),
      ]);
      setServants(servantRows);
      setMaterials(materialRows);
      setSummary(nextSummary);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '账号快照加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateServant = <K extends keyof ServantRecord>(
    recordId: string,
    key: K,
    value: ServantRecord[K],
  ) => {
    setServants((rows) =>
      rows.map((row) => (row.record_id === recordId ? { ...row, [key]: value } : row)),
    );
  };

  const updateMaterial = <K extends keyof MaterialRecord>(
    recordId: string,
    key: K,
    value: MaterialRecord[K],
  ) => {
    setMaterials((rows) =>
      rows.map((row) => (row.record_id === recordId ? { ...row, [key]: value } : row)),
    );
  };

  const saveServantRow = async (row: ServantRecord) => {
    if (!row.name.trim()) {
      messageApi.error('从者名不能为空');
      return;
    }
    setSavingId(row.record_id);
    try {
      const saved = await saveAccountServant(row);
      setServants((rows) => rows.map((item) => (item.record_id === row.record_id ? saved : item)));
      setSummary(await loadAccountSummary());
      messageApi.success(`${saved.name} 已保存`);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '从者保存失败');
    } finally {
      setSavingId(null);
    }
  };

  const removeServantRow = async (row: ServantRecord) => {
    if (row.record_id.startsWith('draft-')) {
      setServants((rows) => rows.filter((item) => item.record_id !== row.record_id));
      return;
    }
    try {
      await deleteAccountServant(row.record_id);
      setServants((rows) => rows.filter((item) => item.record_id !== row.record_id));
      setSummary(await loadAccountSummary());
      messageApi.success(`${row.name} 已删除`);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '从者删除失败');
    }
  };

  const saveMaterialRow = async (row: MaterialRecord) => {
    if (!row.name.trim()) {
      messageApi.error('材料名不能为空');
      return;
    }
    setSavingId(row.record_id);
    try {
      const saved = await saveAccountMaterial(row);
      setMaterials((rows) => rows.map((item) => (item.record_id === row.record_id ? saved : item)));
      setSummary(await loadAccountSummary());
      messageApi.success(`${saved.name} 已保存`);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '材料保存失败');
    } finally {
      setSavingId(null);
    }
  };

  const removeMaterialRow = async (row: MaterialRecord) => {
    if (row.record_id.startsWith('draft-')) {
      setMaterials((rows) => rows.filter((item) => item.record_id !== row.record_id));
      return;
    }
    try {
      await deleteAccountMaterial(row.record_id);
      setMaterials((rows) => rows.filter((item) => item.record_id !== row.record_id));
      setSummary(await loadAccountSummary());
      messageApi.success(`${row.name} 已删除`);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '材料删除失败');
    }
  };
  const servantColumns = useMemo<ColumnsType<ServantRecord>>(
    () => [
      {
        title: '从者名',
        dataIndex: 'name',
        fixed: 'left',
        width: 180,
        render: (_value, row) => (
          <Input
            value={row.name}
            placeholder="如：河上彦斋"
            onChange={(event) => updateServant(row.record_id, 'name', event.target.value)}
          />
        ),
      },
      {
        title: '职阶',
        dataIndex: 'class_name',
        width: 120,
        render: (_value, row) => (
          <Select
            value={row.class_name || undefined}
            options={classOptions}
            placeholder="选择"
            onChange={(value) => updateServant(row.record_id, 'class_name', value)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '稀有度',
        dataIndex: 'rarity',
        width: 90,
        render: (_value, row) => (
          <InputNumber
            min={0}
            max={5}
            value={row.rarity}
            onChange={(value) => updateServant(row.record_id, 'rarity', value ?? null)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '等级',
        dataIndex: 'level',
        width: 90,
        render: (_value, row) => (
          <InputNumber
            min={0}
            max={999}
            value={row.level}
            onChange={(value) => updateServant(row.record_id, 'level', value ?? null)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '上限',
        dataIndex: 'max_level',
        width: 90,
        render: (_value, row) => (
          <InputNumber
            min={0}
            max={999}
            value={row.max_level}
            onChange={(value) => updateServant(row.record_id, 'max_level', value ?? null)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '宝具',
        dataIndex: 'np_level',
        width: 80,
        render: (_value, row) => (
          <InputNumber
            min={1}
            max={5}
            value={row.np_level}
            onChange={(value) => updateServant(row.record_id, 'np_level', value ?? null)}
            style={{ width: '100%' }}
          />
        ),
      },
      ...(['skill_1', 'skill_2', 'skill_3'] as const).map((key, index) => ({
        title: `技能${index + 1}`,
        dataIndex: key,
        width: 82,
        render: (_value: number | null, row: ServantRecord) => (
          <InputNumber
            min={1}
            max={10}
            value={row[key]}
            onChange={(value) => updateServant(row.record_id, key, value ?? null)}
            style={{ width: '100%' }}
          />
        ),
      })),
      {
        title: '追加2',
        dataIndex: 'append_2',
        width: 82,
        render: (_value, row) => (
          <InputNumber
            min={1}
            max={10}
            value={row.append_2}
            onChange={(value) => updateServant(row.record_id, 'append_2', value ?? null)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '可信度',
        dataIndex: 'confidence',
        width: 110,
        render: (_value, row) => (
          <Select
            value={row.confidence}
            options={confidenceOptions}
            onChange={(value) => updateServant(row.record_id, 'confidence', value)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '备注',
        dataIndex: 'notes',
        width: 220,
        render: (_value, row) => (
          <Input
            value={row.notes}
            placeholder="可写练度或使用限制"
            onChange={(event) => updateServant(row.record_id, 'notes', event.target.value)}
          />
        ),
      },
      {
        title: '操作',
        key: 'action',
        fixed: 'right',
        width: 120,
        render: (_value, row) => (
          <Space size={4}>
            <Button
              size="small"
              type="primary"
              icon={<SaveOutlined />}
              loading={savingId === row.record_id}
              onClick={() => void saveServantRow(row)}
            >
              保存
            </Button>
            <Popconfirm title="删除该从者记录？" onConfirm={() => void removeServantRow(row)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [savingId, servants],
  );

  const materialColumns = useMemo<ColumnsType<MaterialRecord>>(
    () => [
      {
        title: '材料名',
        dataIndex: 'name',
        width: 220,
        render: (_value, row) => (
          <Input
            value={row.name}
            placeholder="如：鬼炎鬼灯"
            onChange={(event) => updateMaterial(row.record_id, 'name', event.target.value)}
          />
        ),
      },
      {
        title: '分类',
        dataIndex: 'category',
        width: 130,
        render: (_value, row) => (
          <Select
            value={row.category || undefined}
            options={materialCategories}
            placeholder="选择"
            onChange={(value) => updateMaterial(row.record_id, 'category', value)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '持有数量',
        dataIndex: 'quantity',
        width: 130,
        render: (_value, row) => (
          <InputNumber
            min={0}
            max={99999999}
            value={row.quantity}
            onChange={(value) => updateMaterial(row.record_id, 'quantity', value ?? 0)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '计划保留',
        dataIndex: 'reserve_quantity',
        width: 130,
        render: (_value, row) => (
          <InputNumber
            min={0}
            max={99999999}
            value={row.reserve_quantity}
            onChange={(value) => updateMaterial(row.record_id, 'reserve_quantity', value ?? 0)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '可信度',
        dataIndex: 'confidence',
        width: 110,
        render: (_value, row) => (
          <Select
            value={row.confidence}
            options={confidenceOptions}
            onChange={(value) => updateMaterial(row.record_id, 'confidence', value)}
            style={{ width: '100%' }}
          />
        ),
      },
      {
        title: '备注',
        dataIndex: 'notes',
        width: 240,
        render: (_value, row) => (
          <Input
            value={row.notes}
            onChange={(event) => updateMaterial(row.record_id, 'notes', event.target.value)}
          />
        ),
      },
      {
        title: '操作',
        key: 'action',
        fixed: 'right',
        width: 120,
        render: (_value, row) => (
          <Space size={4}>
            <Button
              size="small"
              type="primary"
              icon={<SaveOutlined />}
              loading={savingId === row.record_id}
              onClick={() => void saveMaterialRow(row)}
            >
              保存
            </Button>
            <Popconfirm title="删除该材料记录？" onConfirm={() => void removeMaterialRow(row)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [materials, savingId],
  );
  return (
    <div className="account-snapshot-panel">
      {contextHolder}
      <div className="ga-heading">
        <div>
          <h2>账号基础资源</h2>
          <p className="ga-small ga-muted">
            3T 组队所需的从者快照 · 材料库存暂作辅助，不参与首版推荐算法
          </p>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setServants((rows) => [blankServant(), ...rows])}
          >
            新增从者
          </Button>
          <Button icon={<PlusOutlined />} onClick={() => setMaterials((rows) => [blankMaterial(), ...rows])}>
            新增材料
          </Button>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        message="账号数据仅保存在本地私有数据库"
        description="从者副本、宝具、技能及后续补充的礼装/御主礼装用于本地 3T 组队；数据不会发送给云端模型。标注为“候选”的数据需要人工确认。"
      />

      <div className="ga-grid-3">
        <Card size="small">
          <Typography.Text type="secondary">已录入从者</Typography.Text>
          <div className="account-stat">{summary?.servants || 0}</div>
        </Card>
        <Card size="small">
          <Typography.Text type="secondary">已确认从者</Typography.Text>
          <div className="account-stat">{summary?.confirmed_servants || 0}</div>
        </Card>
        <Card size="small">
          <Typography.Text type="secondary">已录入材料</Typography.Text>
          <div className="account-stat">{summary?.materials || 0}</div>
        </Card>
      </div>

      <Tabs
        className="account-snapshot-tabs"
        items={[
          {
            key: 'servants',
            label: `从者练度 (${servants.length})`,
            children: (
              <Table<ServantRecord>
                rowKey="record_id"
                size="small"
                loading={loading}
                columns={servantColumns}
                dataSource={servants}
                pagination={{ pageSize: 20, showSizeChanger: false }}
                scroll={{ x: 1580 }}
              />
            ),
          },
          {
            key: 'combat',
            label: '礼装与助战',
            children: <CombatInventoryPanel />,
          },
          {
            key: 'materials',
            label: `材料库存 (${materials.length})`,
            children: (
              <Table<MaterialRecord>
                rowKey="record_id"
                size="small"
                loading={loading}
                columns={materialColumns}
                dataSource={materials}
                pagination={{ pageSize: 30, showSizeChanger: false }}
                scroll={{ x: 1160 }}
              />
            ),
          },
        ]}
      />
    </div>
  );
}