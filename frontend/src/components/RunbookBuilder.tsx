// 自定义 runbook 表单：副本 + 三人队伍（从账号从者下拉）+ 每回合操作 + 助战规则。
//
// 提交后走后端 `POST /execution/runbooks`：**先编译期校验**（同名歧义、技能槽越界、
// 每回合必须 3 个出手位），通过才落盘，随后自动出现在执行页的 runbook 下拉里。
// 助战规则按「从者 + 礼装白名单」——白名单里的礼装指纹要先在助战屏登记（见下方提示）。
import { Alert, Button, Card, Checkbox, Input, InputNumber, Modal, Select, Space, Tag, message } from 'antd';
import { PlusOutlined, SaveOutlined, DeleteOutlined, CameraOutlined, ImportOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  createRunbook,
  importCombatProfile,
  loadAccountServants,
  loadExecutionOptions,
  loadGameAssistantBootstrap,
  loadSupportLibrary,
  listCombatProfiles,
  questAp,
  questLevel,
  registerSupportRow,
  type AccountServantBrief,
  type CombatProfile,
  type CombatProfileImportResult,
  type QuestSummary,
  type RunbookStep,
  type SupportRegisterResult,
  type SupportLibrary,
} from '../stores/gameAssistant';
import { runbookTeamMemberName } from '../runbookDraft';

const TURNS = [1, 2, 3];
const KIND_OPTIONS = [
  { value: 'skill', label: '技能' },
  { value: 'np', label: '宝具' },
  { value: 'card', label: '指令卡' },
  { value: 'mystic_code', label: '御主技能' },
];
const CARD_OPTIONS = [
  { value: 'any', label: '任意' },
  { value: 'arts', label: '蓝（Arts）' },
  { value: 'buster', label: '红（Buster）' },
  { value: 'quick', label: '绿（Quick）' },
];
const CARD_LABELS: Record<string, string> = {
  any: '任意卡',
  arts: '蓝卡',
  buster: '红卡',
  quick: '绿卡',
};
const POSITION_OPTIONS = [
  { value: 'leftmost', label: '最左优先' },
];
const SLOT_OPTIONS = [1, 2, 3].map((slot) => ({ value: slot, label: `第 ${slot} 个` }));

type DraftStep = RunbookStep;

function slotKey(servant: AccountServantBrief): string {
  return `${servant.name}|${servant.class_name}`;
}

function describeStep(step: DraftStep): string {
  const who = `${step.actor_slot ? `站位${step.actor_slot} ` : ''}${step.actor}`;
  if (step.kind === 'np') return `第${step.turn}回合 · ${who} 宝具`;
  if (step.kind === 'card') {
    const chain = step.choose?.length
      ? step.choose.map((entry) => CARD_LABELS[entry.card] ?? entry.card).join('→')
      : CARD_LABELS[step.card ?? 'any'] ?? 'any';
    return `第${step.turn}回合 · ${who} 出卡（${chain}）`;
  }
  const target = step.target ? ` → ${step.target}` : '';
  return `第${step.turn}回合 · ${who} ${step.kind === 'mystic_code' ? '御主' : ''}技能${step.skill_slot ?? ''}${target}`;
}

export default function RunbookBuilder({ onCreated }: { onCreated?: () => void }) {
  const [servants, setServants] = useState<AccountServantBrief[]>([]);
  const [library, setLibrary] = useState<SupportLibrary>({ servant: [], ce: [] });
  const [name, setName] = useState('my_runbook.json');
  const [questId, setQuestId] = useState('');
  const [title, setTitle] = useState('');
  const [team, setTeam] = useState<string[]>(['', '', '']);
  const [steps, setSteps] = useState<DraftStep[]>([]);
  const [supportServant, setSupportServant] = useState('');
  const [supportCe, setSupportCe] = useState<string[]>([]);
  const [draftTurn, setDraftTurn] = useState(1);
  const [draftKind, setDraftKind] = useState<DraftStep['kind']>('skill');
  const [draftActor, setDraftActor] = useState('');
  const [draftSlot, setDraftSlot] = useState(1);
  const [draftCard, setDraftCard] = useState('any');
  const [cardFallback, setCardFallback] = useState(true);
  const [dpsSlot, setDpsSlot] = useState(0);
  const [draftTarget, setDraftTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [okText, setOkText] = useState('');
  const [registerRow, setRegisterRow] = useState(1);
  const [registerServant, setRegisterServant] = useState('');
  const [registerCe, setRegisterCe] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerResult, setRegisterResult] = useState<SupportRegisterResult | null>(null);
  // 副本目录：当前活动的关卡 + 已入库战斗档案（选了副本才知道能不能做 3T 推荐）
  const [profiles, setProfiles] = useState<CombatProfile[]>([]);
  const [eventQuests, setEventQuests] = useState<QuestSummary[]>([]);
  const [eventId, setEventId] = useState('');
  const [eventStatus, setEventStatus] = useState<string>('running');
  const [runbookQuestIds, setRunbookQuestIds] = useState<Array<{ quest_id: string; title: string }>>([]);
  const [manualQuest, setManualQuest] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importHeading, setImportHeading] = useState('');
  const [importUrl, setImportUrl] = useState('');
  const [importHtml, setImportHtml] = useState('');
  const [importResult, setImportResult] = useState<CombatProfileImportResult | null>(null);

  useEffect(() => {
    loadAccountServants()
      .then(setServants)
      .catch(() => message.warning('读账号从者失败：队伍下拉会是空的'));
    loadSupportLibrary()
      .then(setLibrary)
      .catch(() => undefined);
    listCombatProfiles()
      .then(setProfiles)
      .catch(() => undefined);
    loadGameAssistantBootstrap()
      .then((data) => {
        const eventView = data.event_view;
        if (!eventView || data.event_data_status !== 'ready') {
          setEventQuests([]);
          setEventId('');
          return;
        }
        setEventQuests(eventView.event.quests ?? []);
        setEventId(eventView.event.event_id);
        setEventStatus(eventView.event_status ?? 'running');
      })
      .catch(() => undefined);
    loadExecutionOptions()
      .then((loaded) =>
        setRunbookQuestIds(
          (loaded.runbook_items ?? [])
            .filter((item) => item.quest_id)
            .map((item) => ({ quest_id: item.quest_id, title: item.title || item.name })),
        ))
      .catch(() => undefined);
  }, []);

  // 副本目录 = 当前活动的关卡（有名字/AP/推荐等级）+ 已入库档案（有档案才能做 3T 推荐）
  const questOptions = useMemo(() => {
    const merged = new Map<string, { quest_id: string; name: string; detail: string; hasProfile: boolean }>();
    for (const quest of eventQuests) {
      merged.set(quest.quest_id, {
        quest_id: quest.quest_id,
        name: quest.name,
        detail: [
          quest.ap ? `${quest.ap} AP` : '',
          questLevel(quest),
          eventStatus === 'running' ? '' : '活动已结束（仅供对照）',
        ].filter(Boolean).join(' · '),
        hasProfile: false,
      });
    }
    for (const item of runbookQuestIds) {
      if (merged.has(item.quest_id)) continue;
      merged.set(item.quest_id, {
        quest_id: item.quest_id,
        name: item.title || item.quest_id,
        detail: '已有 runbook',
        hasProfile: false,
      });
    }
    for (const profile of profiles) {
      const current = merged.get(profile.quest_id);
      merged.set(profile.quest_id, {
        quest_id: profile.quest_id,
        name: current?.name || profile.quest_name,
        detail: current?.detail || `只有档案（${profile.waves.length} 面）`,
        hasProfile: true,
      });
    }
    return Array.from(merged.values());
  }, [eventQuests, eventStatus, profiles, runbookQuestIds]);

  const selectedQuest = questOptions.find((item) => item.quest_id === questId) || null;
  const selectedProfile = profiles.find((item) => item.quest_id === questId) || null;

  const servantOptions = useMemo(
    () => servants.map((servant) => ({
      value: slotKey(servant),
      label: `${servant.name}（${servant.class_name || '?'} ${servant.rarity}★ Lv${servant.level}）`,
    })),
    [servants],
  );

  // 由谁出：**按站位选**（value = 站位号）。双杀狐/双 C呆这种同名占两个站位时，
  // 只按名字选会永远指到第一个同名站位 —— 站位号才是唯一标识。
  const actorOptions = useMemo(
    () =>
      team
        .map((key, index) => ({ key, slot: index + 1 }))
        .filter((item) => item.key)
        .map((item) => ({ value: String(item.slot), label: `站位 ${item.slot} · ${item.key.split('|')[0]}` })),
    [team],
  );

  const submittedServantName = useCallback(
    (slotKey: string) => runbookTeamMemberName(slotKey, servants),
    [servants],
  );

  const addStep = useCallback(() => {
    if (!draftActor) {
      message.warning('先选这一动作由哪位从者出');
      return;
    }
    const actorSlot = Number(draftActor);
    const actor = team[actorSlot - 1]
      ? submittedServantName(team[actorSlot - 1])
      : '';
    const targetName = draftTarget && team[Number(draftTarget) - 1]
      ? submittedServantName(team[Number(draftTarget) - 1])
      : '';
    const step: DraftStep = draftKind === 'card'
      ? {
          turn: draftTurn,
          actor,
          actor_slot: actorSlot,
          kind: 'card',
          // 「没有就退到任意卡」：编成偏好链，第一条挑不到就自动走第二条（不再停在原地）
          choose: cardFallback
            ? [{ card: draftCard, position: 'leftmost' }, { card: 'any', position: 'leftmost' }]
            : [{ card: draftCard, position: 'leftmost' }],
        }
      : draftKind === 'np'
        ? { turn: draftTurn, actor, actor_slot: actorSlot, kind: 'np' }
        : {
            turn: draftTurn, actor, actor_slot: actorSlot, kind: draftKind, skill_slot: draftSlot,
            ...(targetName ? { target: targetName } : {}),
          };
    setSteps((current) => [...current, step]);
  }, [cardFallback, draftActor, draftCard, draftKind, draftSlot, draftTarget, draftTurn, submittedServantName, team]);

  const submit = useCallback(async () => {
    setError('');
    setOkText('');
    if (!name.trim().endsWith('.json')) {
      setError('文件名必须以 .json 结尾。');
      return;
    }
    const selectedTeam = team.filter(Boolean);
    if (selectedTeam.length === 0) {
      setError('请至少选择一位从者组成队伍。');
      return;
    }
    if (steps.length === 0) {
      setError('请先添加至少一个动作。');
      return;
    }
    const invalidTurn = Array.from(new Set(steps.map((step) => step.turn))).find(
      (turn) =>
        steps.filter(
          (step) =>
            step.turn === turn &&
            step.kind !== 'skill' &&
            step.kind !== 'mystic_code',
        ).length !== 3,
    );
    if (invalidTurn != null) {
      const slots = steps.filter(
        (step) =>
          step.turn === invalidTurn &&
          step.kind !== 'skill' &&
          step.kind !== 'mystic_code',
      ).length;
      setError(
        `第 ${invalidTurn} 回合目前有 ${slots} 个出手位，需要正好 3 个（宝具和指令卡计入，技能不计）。`,
      );
      return;
    }
    setBusy(true);
    try {
      const created = await createRunbook({
        name,
        quest_id: questId,
        title,
        source: '界面表单',
        notes: [],
        dps: dpsSlot && team[dpsSlot - 1]
          ? submittedServantName(team[dpsSlot - 1])
          : '',
        team: selectedTeam.map((key) => {
          const [, className = ''] = key.split('|');
          return { name: submittedServantName(key), class_name: className };
        }),
        steps,
        support: supportServant || supportCe.length
          ? { servant: supportServant, ce_names: supportCe }
          : null,
      });
      setOkText(`已生成 ${created.name}（${created.actions} 个动作）。回执行页刷新下拉即可选它。`);
      onCreated?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [dpsSlot, name, onCreated, questId, steps, submittedServantName, supportCe, supportServant, team, title]);

  const submitRegister = useCallback(async () => {
    const ceList = registerCe
      .split(/[,，\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!registerServant.trim() && ceList.length === 0) {
      message.warning('至少要给一个名字：从者名 或 礼装名');
      return;
    }
    setRegistering(true);
    setRegisterResult(null);
    try {
      const result = await registerSupportRow({
        row: registerRow,
        servant: registerServant.trim(),
        ce: ceList,
      });
      setRegisterResult(result);
      if (result.ok) {
        message.success('登记完成（没有点任何东西、没花 AP）；白名单已刷新');
        setLibrary(await loadSupportLibrary());
      } else {
        message.error('没能登记：看下面的原因（执行器已停手，什么也没点）');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRegistering(false);
    }
  }, [registerCe, registerRow, registerServant]);

  // 导入战斗档案：解析 Mooncell 的「关卡配置」表 ⇒ 落一份 mock=false / verified=false 的档案。
  // 执行不需要档案，档案是给 3T 推荐用的；数值来自公开 wiki，开刷前仍需人工确认。
  const submitImport = useCallback(async () => {
    setImporting(true);
    try {
      const result = await importCombatProfile({
        quest_id: questId,
        quest_name: selectedQuest?.name || questId,
        heading_id: importHeading.trim(),
        event_id: eventId,
        url: importUrl.trim(),
        html: importHtml,
      });
      setImportResult(result);
      setProfiles(await listCombatProfiles());
      message.success('档案已导入（未核对状态；3T 推荐可以用了）');
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (err instanceof Error ? err.message : '导入失败');
      message.error(detail);
    } finally {
      setImporting(false);
    }
  }, [eventId, importHeading, importHtml, importUrl, questId, selectedQuest]);

  return (
    <Card size="small" title="新建 runbook（我的 3T 队伍）" style={{ marginBottom: 12 }}>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Space wrap>
          <Input
            addonBefore="文件名" style={{ width: 320 }} value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="my_runbook.json（必须以 .json 结尾）"
          />
          {manualQuest ? (
            <Input
              addonBefore="副本 ID" style={{ width: 360 }} value={questId}
              onChange={(event) => setQuestId(event.target.value)}
              placeholder="例如 fgo-cn-daily-treasure-door-extreme"
            />
          ) : (
            <Select
              style={{ width: 360 }} showSearch optionFilterProp="label"
              placeholder="选一个副本（当前活动关卡 / 已入库档案）"
              value={questId || undefined}
              onChange={setQuestId}
              options={questOptions.map((item) => ({
                value: item.quest_id,
                label: `${item.name}（${item.detail}${item.hasProfile ? ' · 有档案' : ' · 无档案'}）`,
              }))}
              notFoundContent={<span className="ga-small">目录是空的：点右边「手动输入」自己填 ID</span>}
            />
          )}
          <Button size="small" onClick={() => setManualQuest((current) => !current)}>
            {manualQuest ? '从目录选' : '手动输入'}
          </Button>
          <Input
            addonBefore="标题" style={{ width: 320 }} value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="例如 宝物库之门 极级（我的队伍）"
          />
        </Space>

        {questId ? (
          <div className="ga-row" style={{ marginTop: 2 }}>
            {selectedProfile ? (
              <span className="ga-small ga-muted">
                已有战斗档案：{selectedProfile.waves.length} 面 ·{' '}
                {selectedProfile.verified ? '已核对' : '未核对'} ·{' '}
                {selectedProfile.mock ? '示例数据' : '来自公开 wiki'} ⇒ 可以做 3T 推荐
              </span>
            ) : (
              <>
                <span className="ga-small ga-muted">
                  这个副本还没有战斗档案 ⇒ runbook 只能执行；要做 3T 推荐得先导入档案
                </span>
                <Button size="small" icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
                  导入战斗档案
                </Button>
              </>
            )}
          </div>
        ) : null}

        <div>
          <span className="ga-small ga-muted">队伍（站位 1 / 2 / 3，从账号已导入的从者里选）</span>
          <Space wrap style={{ marginTop: 4 }}>
            {[0, 1, 2].map((index) => (
              <Select
                key={index}
                style={{ width: 300 }}
                placeholder={`站位 ${index + 1}`}
                value={team[index] || undefined}
                options={servantOptions}
                showSearch
                optionFilterProp="label"
                onChange={(value) =>
                  setTeam((current) => current.map((item, at) => (at === index ? value : item)))}
              />
            ))}
          </Space>
          <Space wrap style={{ marginTop: 6 }}>
            <Select
              style={{ width: 260 }}
              placeholder="打手位（可选）"
              allowClear
              value={dpsSlot || undefined}
              options={actorOptions}
              onChange={(value) => setDpsSlot(value ? Number(value) : 0)}
            />
            <span className="ga-small ga-muted">
              指定打手后，辅助位的单体友方技能<b>不写目标</b>就默认指向它（生成时会在计划里通知一句）
            </span>
          </Space>
        </div>

        <div>
          <span className="ga-small ga-muted">
            每回合操作（每回合需要 3 个出手位：宝具占 1 个，指令卡各占 1 个；技能不加出手位）
          </span>
          <Space wrap style={{ marginTop: 4 }}>
            <Select
              style={{ width: 110 }} value={draftTurn}
              options={TURNS.map((turn) => ({ value: turn, label: `第 ${turn} 回合` }))}
              onChange={setDraftTurn}
            />
            <Select
              style={{ width: 120 }} value={draftKind}
              options={KIND_OPTIONS}
              onChange={(value) => setDraftKind(value as DraftStep['kind'])}
            />
            <Select
              style={{ width: 220 }} placeholder="由谁出" value={draftActor || undefined}
              options={actorOptions}
              onChange={setDraftActor}
            />
            {(draftKind === 'skill' || draftKind === 'mystic_code') && (
              <>
                <Select
                  style={{ width: 110 }} value={draftSlot} options={SLOT_OPTIONS}
                  onChange={setDraftSlot}
                />
                <Select
                  style={{ width: 200 }} placeholder="目标（留空 = 默认打手）"
                  allowClear value={draftTarget || undefined}
                  options={actorOptions}
                  onChange={(value) => setDraftTarget(value ?? '')}
                />
              </>
            )}
            {draftKind === 'card' && (
              <>
                <Select
                  style={{ width: 130 }} value={draftCard} options={CARD_OPTIONS}
                  onChange={setDraftCard}
                />
                <Select
                  style={{ width: 130 }} value="leftmost" options={POSITION_OPTIONS} disabled
                />
                <Checkbox checked={cardFallback} onChange={(event) => setCardFallback(event.target.checked)}>
                  <span className="ga-small">没有这种卡就改出任意卡</span>
                </Checkbox>
              </>
            )}
            <Button icon={<PlusOutlined />} onClick={addStep}>加动作</Button>
          </Space>
        </div>

        <div>
          {TURNS.map((turn) => {
            const inTurn = steps.filter((step) => step.turn === turn);
            const marks = inTurn.filter((step) => step.kind !== 'skill' && step.kind !== 'mystic_code');
            return (
              <div key={turn} style={{ marginBottom: 4 }}>
                <Tag color={marks.length === 3 ? 'green' : 'orange'}>第 {turn} 回合</Tag>
                <span className="ga-small ga-muted">
                  {marks.length === 3 ? '出手位齐了' : `还差 ${3 - marks.length} 个出手位`}
                </span>
                <Space wrap style={{ marginLeft: 8 }}>
                  {inTurn.map((step, index) => (
                    <Tag
                      key={`${turn}-${index}`}
                      closable
                      onClose={() => {
                        const target = steps.indexOf(step);
                        setSteps((current) => current.filter((_, at) => at !== target));
                      }}
                    >
                      {describeStep(step).replace(`第${turn}回合 · `, '')}
                    </Tag>
                  ))}
                </Space>
              </div>
            );
          })}
        </div>

        <div>
          <span className="ga-small ga-muted">
            登记当前助战行（游戏停在「助战选择」屏时点这个）：执行器只截图 + 存指纹，
            <b>一下都不点</b>，所以不花 AP。礼装项写 <code>名字:行号</code> 表示取另一行的礼装。
          </span>
          <Space wrap style={{ marginTop: 4 }}>
            <InputNumber
              addonBefore="第几行"
              min={1}
              max={9}
              value={registerRow}
              onChange={(value) => setRegisterRow(value ?? 1)}
            />
            <Input
              addonBefore="从者名"
              style={{ width: 320 }}
              value={registerServant}
              onChange={(event) => setRegisterServant(event.target.value)}
              placeholder="留空则不登记从者"
            />
            <Input
              addonBefore="礼装名"
              style={{ width: 320 }}
              value={registerCe}
              onChange={(event) => setRegisterCe(event.target.value)}
              placeholder="多个用逗号分开，例如 贝拉丽莎, 蒙娜丽莎"
            />
            <Button icon={<CameraOutlined />} loading={registering} onClick={submitRegister}>
              登记这一行（不点任何东西）
            </Button>
          </Space>
          {registerResult ? (
            <Alert
              style={{ marginTop: 6 }}
              type={registerResult.ok ? 'success' : 'warning'}
              showIcon
              message={
                registerResult.ok
                  ? `已登记：${(registerResult.report?.saved ?? [])
                      .map((item) => `${item.kind === 'servant' ? '从者' : '礼装'}「${item.name}」`)
                      .join('、')}`
                  : '没能登记（执行器已停手，什么也没点）'
              }
              description={
                <div className="ga-small">
                  {registerResult.report?.rows_seen ? (
                    <div>
                      这一屏看到 {registerResult.report.rows_seen} 行助战；指纹取自第{' '}
                      {Array.from(
                        new Set((registerResult.report.saved ?? []).map((item) => item.source_row)),
                      ).join('、')}
                      行。
                    </div>
                  ) : null}
                  <pre className="ga-small">{registerResult.output_tail.slice(-8).join('\n')}</pre>
                </div>
              }
            />
          ) : null}
        </div>

        <div>
          <span className="ga-small ga-muted">
            助战规则：从上往下挑第一行（指纹要先在助战屏登记）。<b>礼装留空 = 只按从者挑</b> ——
            冠位战里冠位从者可以戴 3 件礼装、礼装区几何不一样，那种场合通常只指定从者。
          </span>
          <Space wrap style={{ marginTop: 4 }}>
            <Select
              style={{ width: 260 }} placeholder="借哪只从者" allowClear
              value={supportServant || undefined}
              options={library.servant.map((item) => ({ value: item, label: item }))}
              onChange={(value) => setSupportServant(value ?? '')}
            />
            <Select
              mode="multiple" style={{ minWidth: 260 }} placeholder="礼装白名单（留空 = 只按从者挑）"
              value={supportCe}
              options={library.ce.map((item) => ({ value: item, label: item }))}
              onChange={setSupportCe}
            />
          </Space>
          <div className="ga-small ga-muted" style={{ marginTop: 4 }}>
            库里已有：从者 {library.servant.length} 个、礼装 {library.ce.length} 个。缺的（例如好友换了礼装）
            就在游戏停在助战屏时用上面的「登记这一行」补一次。
          </div>
        </div>

        <Space>
          <Button type="primary" icon={<SaveOutlined />} loading={busy} onClick={submit}>
            生成并校验
          </Button>
          <Button icon={<DeleteOutlined />} onClick={() => setSteps([])}>清空动作</Button>
        </Space>
        {okText && <Alert type="success" showIcon message={okText} />}
        {error && <Alert type="error" showIcon message={error} />}
      </Space>

      <Modal
        open={importOpen}
        title={`导入战斗档案：${selectedQuest?.name || questId}`}
        onCancel={() => setImportOpen(false)}
        onOk={() => void submitImport()}
        okText="解析并导入"
        confirmLoading={importing}
        okButtonProps={{ disabled: !importHeading.trim() }}
        width={620}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <span className="ga-small ga-muted">
            来源是 Mooncell FGO Wiki 的「关卡配置」表：填那一节的<b>锚点 id</b>（页面 URL 里 # 后面那截，
            例如 <code>神剑改_燃烧吧翡翠剑</code>）。解析器是窄口的——读不出的字段会报 warning，<b>不会猜数值</b>；
            导入的档案是「未核对」状态，3T 推荐可以用，但开刷前仍要人工确认。
          </span>
          <Input
            addonBefore="锚点 id" value={importHeading}
            onChange={(event) => setImportHeading(event.target.value)}
            placeholder="例如 神剑改_燃烧吧翡翠剑"
          />
          <Input
            addonBefore="页面链接" value={importUrl}
            onChange={(event) => setImportUrl(event.target.value)}
            placeholder="https://fgo.wiki/w/...（留空则要贴下面的 HTML）"
          />
          <Input.TextArea
            rows={4} value={importHtml}
            onChange={(event) => setImportHtml(event.target.value)}
            placeholder="或者直接贴页面 HTML（离线 / 抓不到时兜底）"
          />
          {importResult ? (
            <Alert
              type={importResult.warnings.length ? 'warning' : 'success'}
              showIcon
              message={importResult.warnings.length ? '导入完成，但有需要人工核对的地方' : '导入完成'}
              description={
                <div className="ga-small">
                  <div>{importResult.note}</div>
                  {importResult.warnings.map((warning) => (
                    <div key={warning}>· {warning}</div>
                  ))}
                </div>
              }
            />
          ) : null}
        </Space>
      </Modal>
    </Card>
  );
}
