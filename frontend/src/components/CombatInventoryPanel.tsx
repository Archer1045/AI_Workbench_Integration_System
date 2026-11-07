import { Alert, Button, Card, Input, InputNumber, Popconfirm, Select, Space, Switch, Table, Tabs, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DeleteOutlined, PlusOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import {
  deleteCraftEssence,
  deleteMysticCode,
  deleteSupportPreference,
  listCraftEssences,
  listMysticCodes,
  listSupportPreferences,
  saveCraftEssence,
  saveMysticCode,
  saveSupportPreference,
  type CraftEssenceRecord,
  type MysticCodeRecord,
  type SupportPreferenceRecord,
} from '../stores/accountSnapshot';
import { loadCombatAssumptions, saveCombatAssumptions, type CombatAssumptions } from '../stores/gameAssistant';

const classOptions = ['Saber', 'Archer', 'Lancer', 'Rider', 'Caster', 'Assassin', 'Berserker', 'Ruler', 'Avenger', 'Alterego', 'MoonCancer', 'Foreigner', 'Pretender', 'Beast', 'Shielder'].map((value) => ({ value, label: value }));

function blankCraftEssence(): CraftEssenceRecord {
  return { record_id: 'draft-ce-' + Date.now() + '-' + Math.random(), name: '', rarity: 5, level: 1, max_level: 100, limit_break: 0, attack: 0, hp: 0, cost: 12, effects: [], source: 'manual', confidence: 'confirmed', notes: '', updated_at: '' };
}

function blankMysticCode(): MysticCodeRecord {
  return { record_id: 'draft-mc-' + Date.now() + '-' + Math.random(), name: '', level: 1, skills: [], source: 'manual', confidence: 'confirmed', notes: '', updated_at: '' };
}

function blankSupport(): SupportPreferenceRecord {
  return { record_id: 'draft-support-' + Date.now() + '-' + Math.random(), name: '', class_name: '', np_level: null, skill_1: null, skill_2: null, skill_3: null, append_2: null, craft_essence_name: '', friend_only: false, source: 'manual', confidence: 'confirmed', notes: '', updated_at: '' };
}

export default function CombatInventoryPanel() {
  const [messageApi, contextHolder] = message.useMessage();
  const [craftEssences, setCraftEssences] = useState<CraftEssenceRecord[]>([]);
  const [mysticCodes, setMysticCodes] = useState<MysticCodeRecord[]>([]);
  const [supports, setSupports] = useState<SupportPreferenceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [assumptions, setAssumptions] = useState<CombatAssumptions | null>(null);
  const [savingAssumptions, setSavingAssumptions] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [ceRows, mcRows, supportRows, assumptionValues] = await Promise.all([
        listCraftEssences(),
        listMysticCodes(),
        listSupportPreferences(),
        loadCombatAssumptions(),
      ]);
      setCraftEssences(ceRows);
      setMysticCodes(mcRows);
      setSupports(supportRows);
      setAssumptions(assumptionValues);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '礼装与编队资源加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateCe = <K extends keyof CraftEssenceRecord>(recordId: string, key: K, value: CraftEssenceRecord[K]) => {
    setCraftEssences((rows) => rows.map((row) => row.record_id === recordId ? { ...row, [key]: value } : row));
  };

  const updateMc = <K extends keyof MysticCodeRecord>(recordId: string, key: K, value: MysticCodeRecord[K]) => {
    setMysticCodes((rows) => rows.map((row) => row.record_id === recordId ? { ...row, [key]: value } : row));
  };

  const updateSupport = <K extends keyof SupportPreferenceRecord>(recordId: string, key: K, value: SupportPreferenceRecord[K]) => {
    setSupports((rows) => rows.map((row) => row.record_id === recordId ? { ...row, [key]: value } : row));
  };

  const patchAssumptions = (patch: Partial<CombatAssumptions>) => {
    setAssumptions((current) => current ? { ...current, ...patch } : current);
  };

  const saveAssumptionPolicy = async () => {
    if (!assumptions) return;
    setSavingAssumptions(true);
    try {
      setAssumptions(await saveCombatAssumptions(assumptions));
      messageApi.success('礼装假设策略已保存');
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '礼装假设策略保存失败');
    } finally {
      setSavingAssumptions(false);
    }
  };

  const saveCe = async (row: CraftEssenceRecord) => {
    setSavingId(row.record_id);
    try {
      const saved = await saveCraftEssence(row);
      setCraftEssences((rows) => rows.map((item) => item.record_id === row.record_id ? saved : item));
      messageApi.success('概念礼装已保存');
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '概念礼装保存失败');
    } finally {
      setSavingId(null);
    }
  };

  const saveMc = async (row: MysticCodeRecord) => {
    setSavingId(row.record_id);
    try {
      const saved = await saveMysticCode(row);
      setMysticCodes((rows) => rows.map((item) => item.record_id === row.record_id ? saved : item));
      messageApi.success('御主礼装已保存');
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '御主礼装保存失败');
    } finally {
      setSavingId(null);
    }
  };

  const saveSupport = async (row: SupportPreferenceRecord) => {
    setSavingId(row.record_id);
    try {
      const saved = await saveSupportPreference(row);
      setSupports((rows) => rows.map((item) => item.record_id === row.record_id ? saved : item));
      messageApi.success('助战条件已保存');
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '助战条件保存失败');
    } finally {
      setSavingId(null);
    }
  };

  const ceColumns: ColumnsType<CraftEssenceRecord> = [
    { title: '礼装名', dataIndex: 'name', width: 180, render: (_v, row) => <Input value={row.name} onChange={(e) => updateCe(row.record_id, 'name', e.target.value)} /> },
    { title: '星级', dataIndex: 'rarity', width: 70, render: (_v, row) => <InputNumber min={0} max={5} value={row.rarity} onChange={(v) => updateCe(row.record_id, 'rarity', Number(v || 0))} /> },
    { title: '等级', dataIndex: 'level', width: 80, render: (_v, row) => <InputNumber min={1} max={100} value={row.level} onChange={(v) => updateCe(row.record_id, 'level', Number(v || 1))} /> },
    { title: '满级', dataIndex: 'max_level', width: 80, render: (_v, row) => <InputNumber min={1} max={100} value={row.max_level} onChange={(v) => updateCe(row.record_id, 'max_level', Number(v || 1))} /> },
    { title: '满破', dataIndex: 'limit_break', width: 70, render: (_v, row) => <InputNumber min={0} max={4} value={row.limit_break} onChange={(v) => updateCe(row.record_id, 'limit_break', Number(v || 0))} /> },
    { title: 'ATK', dataIndex: 'attack', width: 90, render: (_v, row) => <InputNumber min={0} value={row.attack} onChange={(v) => updateCe(row.record_id, 'attack', Number(v || 0))} /> },
    { title: 'HP', dataIndex: 'hp', width: 90, render: (_v, row) => <InputNumber min={0} value={row.hp} onChange={(v) => updateCe(row.record_id, 'hp', Number(v || 0))} /> },
    { title: 'Cost', dataIndex: 'cost', width: 80, render: (_v, row) => <InputNumber min={0} max={99} value={row.cost} onChange={(v) => updateCe(row.record_id, 'cost', Number(v || 0))} /> },
    { title: '备注', dataIndex: 'notes', width: 220, render: (_v, row) => <Input value={row.notes} onChange={(e) => updateCe(row.record_id, 'notes', e.target.value)} /> },
    { title: '操作', key: 'action', fixed: 'right', width: 120, render: (_v, row) => <Space size={4}><Button size="small" type="primary" icon={<SaveOutlined />} loading={savingId === row.record_id} onClick={() => void saveCe(row)}>保存</Button><Popconfirm title="删除该礼装？" onConfirm={async () => { if (!row.record_id.startsWith('draft-')) await deleteCraftEssence(row.record_id); setCraftEssences((rows) => rows.filter((item) => item.record_id !== row.record_id)); }}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm></Space> },
  ];

  const mcColumns: ColumnsType<MysticCodeRecord> = [
    { title: '御主礼装', dataIndex: 'name', width: 220, render: (_v, row) => <Input value={row.name} onChange={(e) => updateMc(row.record_id, 'name', e.target.value)} /> },
    { title: '等级', dataIndex: 'level', width: 90, render: (_v, row) => <InputNumber min={1} max={10} value={row.level} onChange={(v) => updateMc(row.record_id, 'level', Number(v || 1))} /> },
    { title: '技能', dataIndex: 'skills', width: 360, render: (_v, row) => <span className="ga-small ga-muted">{row.skills.length ? row.skills.map((s) => s.name || s.skill_id).join('、') : '尚未录入技能结构化数据'}</span> },
    { title: '备注', dataIndex: 'notes', width: 240, render: (_v, row) => <Input value={row.notes} onChange={(e) => updateMc(row.record_id, 'notes', e.target.value)} /> },
    { title: '操作', key: 'action', fixed: 'right', width: 120, render: (_v, row) => <Space size={4}><Button size="small" type="primary" icon={<SaveOutlined />} loading={savingId === row.record_id} onClick={() => void saveMc(row)}>保存</Button><Popconfirm title="删除该御主礼装？" onConfirm={async () => { if (!row.record_id.startsWith('draft-')) await deleteMysticCode(row.record_id); setMysticCodes((rows) => rows.filter((item) => item.record_id !== row.record_id)); }}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm></Space> },
  ];

  const supportColumns: ColumnsType<SupportPreferenceRecord> = [
    { title: '助战从者', dataIndex: 'name', width: 180, render: (_v, row) => <Input value={row.name} onChange={(e) => updateSupport(row.record_id, 'name', e.target.value)} /> },
    { title: '职阶', dataIndex: 'class_name', width: 120, render: (_v, row) => <Select value={row.class_name || undefined} options={classOptions} onChange={(v) => updateSupport(row.record_id, 'class_name', v)} style={{ width: '100%' }} /> },
    { title: '宝具', dataIndex: 'np_level', width: 70, render: (_v, row) => <InputNumber min={1} max={5} value={row.np_level} onChange={(v) => updateSupport(row.record_id, 'np_level', v === null ? null : Number(v))} /> },
    { title: '技能', dataIndex: 'skill_1', width: 150, render: (_v, row) => <Space size={4}><InputNumber min={1} max={10} value={row.skill_1} onChange={(v) => updateSupport(row.record_id, 'skill_1', v === null ? null : Number(v))} /><InputNumber min={1} max={10} value={row.skill_2} onChange={(v) => updateSupport(row.record_id, 'skill_2', v === null ? null : Number(v))} /><InputNumber min={1} max={10} value={row.skill_3} onChange={(v) => updateSupport(row.record_id, 'skill_3', v === null ? null : Number(v))} /></Space> },
    { title: '宝具礼装', dataIndex: 'craft_essence_name', width: 180, render: (_v, row) => <Input value={row.craft_essence_name} onChange={(e) => updateSupport(row.record_id, 'craft_essence_name', e.target.value)} /> },
    { title: '好友限定', dataIndex: 'friend_only', width: 90, render: (_v, row) => <Select value={row.friend_only} options={[{ value: false, label: '否' }, { value: true, label: '是' }]} onChange={(v) => updateSupport(row.record_id, 'friend_only', v)} /> },
    { title: '备注', dataIndex: 'notes', width: 220, render: (_v, row) => <Input value={row.notes} onChange={(e) => updateSupport(row.record_id, 'notes', e.target.value)} /> },
    { title: '操作', key: 'action', fixed: 'right', width: 120, render: (_v, row) => <Space size={4}><Button size="small" type="primary" icon={<SaveOutlined />} loading={savingId === row.record_id} onClick={() => void saveSupport(row)}>保存</Button><Popconfirm title="删除该助战条件？" onConfirm={async () => { if (!row.record_id.startsWith('draft-')) await deleteSupportPreference(row.record_id); setSupports((rows) => rows.filter((item) => item.record_id !== row.record_id)); }}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm></Space> },
  ];

  return (
    <div>
      {contextHolder}
      {assumptions && (
        <Card size="small" title="作战资源假设" style={{ marginBottom: 12 }}>
          <Alert
            type={assumptions.craft_essence_confirmation_complete ? 'success' : 'warning'}
            showIcon
            message="概念礼装按推荐需求默认假定可用"
            description="这允许先做推荐和 Dry Run；正式执行前必须确认本次方案涉及的礼装真实可用。"
            style={{ marginBottom: 12 }}
          />
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Space wrap><span>非本次活动御主礼装默认满级</span><Switch checked={assumptions.mystic_codes_default_max_level} onChange={(value) => patchAssumptions({ mystic_codes_default_max_level: value })} /></Space>
            <Space wrap><span>本次新增御主礼装</span><Input value={assumptions.current_event_mystic_code_name} onChange={(event) => patchAssumptions({ current_event_mystic_code_name: event.target.value })} placeholder="填写活动新增御主礼装名称" style={{ width: 240 }} /><InputNumber min={1} max={10} value={assumptions.current_event_mystic_code_level} onChange={(value) => patchAssumptions({ current_event_mystic_code_level: value === null ? null : Number(value) })} placeholder="等级" /><span>已确认</span><Switch checked={assumptions.current_event_mystic_code_confirmed} onChange={(value) => patchAssumptions({ current_event_mystic_code_confirmed: value })} /></Space>
            <Space wrap><span>本次方案礼装可用性已人工确认</span><Switch checked={assumptions.craft_essence_confirmation_complete} onChange={(value) => patchAssumptions({ craft_essence_confirmation_complete: value, assume_required_craft_essences: true })} /></Space>
            <Button type="primary" icon={<SaveOutlined />} loading={savingAssumptions} onClick={() => void saveAssumptionPolicy()}>保存假设策略</Button>
          </Space>
        </Card>
      )}
      <Space wrap style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>刷新</Button>
        <Button icon={<PlusOutlined />} onClick={() => setCraftEssences((rows) => [blankCraftEssence(), ...rows])}>新增礼装</Button>
        <Button icon={<PlusOutlined />} onClick={() => setMysticCodes((rows) => [blankMysticCode(), ...rows])}>新增御主礼装</Button>
        <Button icon={<PlusOutlined />} onClick={() => setSupports((rows) => [blankSupport(), ...rows])}>新增助战条件</Button>
      </Space>
      <Tabs
        items={[
          { key: 'ce', label: '概念礼装', children: <Table rowKey="record_id" size="small" loading={loading} columns={ceColumns} dataSource={craftEssences} pagination={{ pageSize: 20, showSizeChanger: false }} scroll={{ x: 1300 }} /> },
          { key: 'mc', label: '御主礼装', children: <Table rowKey="record_id" size="small" loading={loading} columns={mcColumns} dataSource={mysticCodes} pagination={{ pageSize: 20, showSizeChanger: false }} scroll={{ x: 950 }} /> },
          { key: 'support', label: '助战条件', children: <Table rowKey="record_id" size="small" loading={loading} columns={supportColumns} dataSource={supports} pagination={{ pageSize: 20, showSizeChanger: false }} scroll={{ x: 1350 }} /> },
        ]}
      />
    </div>
  );
}
