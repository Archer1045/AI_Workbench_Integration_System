// 3T 组队：关卡选择 → 推荐方案 → 礼装确认 → 执行预检
import { Alert, Button, Checkbox, Select, Space, Spin, Tag, Tooltip, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  listCombatProfiles,
  loadCraftEssenceConfirmation,
  recommendTeam,
  runExecutionPreflight,
  saveCraftEssenceConfirmation,
  type CombatProfile,
  type CraftEssenceConfirmation,
  type PreflightCheck,
  type PreflightResult,
  type RecommendationOption,
  type RecommendationResult,
} from '../stores/gameAssistant';

const CHECK_TONE: Record<PreflightCheck['status'], string> = {
  ok: 'green',
  warning: 'orange',
  blocked: 'red',
};

function profileLabel(profile: CombatProfile): string {
  const flags = [profile.mock ? 'Mock' : '真实', profile.verified ? '已验证' : '未验证'];
  return `${profile.quest_name} · AP${profile.ap_cost} · ${flags.join('/')}`;
}

function formatDamage(value: number): string {
  return Math.round(value).toLocaleString('en-US');
}

function BulletList({ title, items, tone }: { title: string; items: string[]; tone?: string }) {
  if (!items.length) return null;
  return (
    <div>
      <strong>{title}</strong>
      <ul className="ga-guide-section" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
        {items.map((item, index) => (
          <li key={`${title}-${index}`} className={tone ? `ga-${tone}` : undefined}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TeamPlannerPanel() {
  const [profiles, setProfiles] = useState<CombatProfile[]>([]);
  const [profilesError, setProfilesError] = useState('');
  const [questId, setQuestId] = useState('');
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [recommending, setRecommending] = useState(false);
  const [activeOptionId, setActiveOptionId] = useState('');
  const [confirmations, setConfirmations] = useState<Record<string, CraftEssenceConfirmation | null>>({});
  const [available, setAvailable] = useState<Record<string, string[]>>({});
  const [savingConfirmation, setSavingConfirmation] = useState(false);
  const [preflights, setPreflights] = useState<Record<string, PreflightResult>>({});
  const [runningPreflight, setRunningPreflight] = useState(false);

  useEffect(() => {
    let active = true;
    listCombatProfiles()
      .then((items) => {
        if (!active) return;
        setProfiles(items);
        setProfilesError('');
        const preferred = items.find((item) => item.verified && !item.mock) ?? items[0];
        if (preferred) setQuestId(preferred.quest_id);
      })
      .catch((error: unknown) => {
        if (active) setProfilesError(error instanceof Error ? error.message : '读取关卡档案失败');
      });
    return () => {
      active = false;
    };
  }, []);

  const activeOption: RecommendationOption | null = useMemo(() => {
    if (!result) return null;
    return result.options.find((item) => item.option_id === activeOptionId) ?? result.options[0] ?? null;
  }, [result, activeOptionId]);

  const activePlanId = activeOption?.plan.plan_id ?? '';

  const loadConfirmation = useCallback(async (planId: string, required: string[]) => {
    try {
      const record = await loadCraftEssenceConfirmation(planId);
      setConfirmations((prev) => ({ ...prev, [planId]: record }));
      setAvailable((prev) => ({
        ...prev,
        [planId]: prev[planId] ?? record?.available_essences ?? required,
      }));
    } catch (error: unknown) {
      message.error(error instanceof Error ? error.message : '读取礼装确认失败');
    }
  }, []);

  useEffect(() => {
    if (!activeOption) return;
    if (activePlanId in confirmations) return;
    void loadConfirmation(activePlanId, activeOption.required_craft_essences);
  }, [activeOption, activePlanId, confirmations, loadConfirmation]);

  const handleRecommend = async () => {
    if (!questId) {
      message.warning('请先选择关卡');
      return;
    }
    setRecommending(true);
    try {
      const data = await recommendTeam(questId);
      setResult(data);
      setActiveOptionId(data.options[0]?.option_id ?? '');
      setPreflights({});
      if (!data.options.length) message.warning('没有生成候选方案');
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || (error instanceof Error ? error.message : '推荐生成失败'));
    } finally {
      setRecommending(false);
    }
  };

  const toggleAvailable = (planId: string, essence: string, checked: boolean) => {
    setAvailable((prev) => {
      const current = prev[planId] ?? [];
      const next = checked ? [...current, essence] : current.filter((item) => item !== essence);
      return { ...prev, [planId]: Array.from(new Set(next)) };
    });
  };

  const handleSaveConfirmation = async () => {
    if (!activeOption || !result) return;
    setSavingConfirmation(true);
    try {
      const record = await saveCraftEssenceConfirmation({
        plan_id: activePlanId,
        quest_id: result.quest_id,
        required_essences: activeOption.required_craft_essences,
        available_essences: available[activePlanId] ?? [],
        confirmed: true,
      });
      setConfirmations((prev) => ({ ...prev, [activePlanId]: record }));
      message.success('礼装确认已保存');
    } catch (error: unknown) {
      message.error(error instanceof Error ? error.message : '礼装确认保存失败');
    } finally {
      setSavingConfirmation(false);
    }
  };

  const handlePreflight = async () => {
    if (!result || !activePlanId) return;
    setRunningPreflight(true);
    try {
      const data = await runExecutionPreflight(result.quest_id, activePlanId);
      setPreflights((prev) => ({ ...prev, [activePlanId]: data }));
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || (error instanceof Error ? error.message : '预检失败'));
    } finally {
      setRunningPreflight(false);
    }
  };

  const confirmation = confirmations[activePlanId] ?? null;
  const checkedEssences = available[activePlanId] ?? [];
  const missingEssences = activeOption
    ? activeOption.required_craft_essences.filter((item) => !checkedEssences.includes(item))
    : [];
  const preflight = preflights[activePlanId];

  return (
    <div className="ga-section-stack">
      <div className="ga-heading">
        <div>
          <h2>3T 组队</h2>
          <p className="ga-small ga-muted">
            面向活动 FREE 本的 3T 候选队伍：选人、每回合行动、伤害/宝具闸门、最低练度与失败条件。
          </p>
        </div>
        <span className="ga-pill green">推荐已接入</span>
      </div>

      {profilesError ? <Alert type="warning" showIcon message="关卡档案读取失败" description={profilesError} /> : null}

      <div className="ga-card">
        <div className="ga-row ga-between">
          <h3>选择关卡</h3>
          <span className="ga-small ga-muted">
            共 {profiles.length} 个档案 · 已验证 {profiles.filter((item) => item.verified).length} 个 · Mock{' '}
            {profiles.filter((item) => item.mock).length} 个
          </span>
        </div>
        <Space wrap style={{ marginTop: 10 }}>
          <Select
            style={{ minWidth: 360 }}
            value={questId || undefined}
            placeholder="选择关卡档案"
            onChange={setQuestId}
            options={profiles.map((profile) => ({ label: profileLabel(profile), value: profile.quest_id }))}
          />
          <Button type="primary" loading={recommending} onClick={() => void handleRecommend()}>
            生成推荐
          </Button>
        </Space>
        <p className="ga-small ga-muted" style={{ marginTop: 8 }}>
          未验证档案只允许 Dry Run 级推演；正式执行要求档案已验证、礼装确认通过，并且再次校验助战。
        </p>
      </div>

      {result ? (
        <>
          <Alert
            type={result.profile_mock ? 'warning' : result.profile_verified ? 'success' : 'info'}
            showIcon
            message={
              `${result.quest_name} · 主要敌人职阶 ${result.dominant_enemy_class || '未知'} · 生成 ${
                result.options.length
              } 个方案`
            }
            description={
              result.notes.length ? (
                <div>
                  {result.notes.map((note, index) => (
                    <div key={index}>{note}</div>
                  ))}
                </div>
              ) : (
                '档案与账号数据均已就绪。'
              )
            }
          />

          <div className="ga-card">
            <h3>候选方案</h3>
            <Space wrap style={{ marginTop: 10 }}>
              {result.options.map((option) => (
                <Button
                  key={option.option_id}
                  type={option.option_id === activeOption?.option_id ? 'primary' : 'default'}
                  onClick={() => setActiveOptionId(option.option_id)}
                >
                  {option.title} · 置信度 {option.confidence}
                </Button>
              ))}
            </Space>
          </div>

          {activeOption ? (
            <>
              <div className="ga-card">
                <div className="ga-row ga-between">
                  <h3>出战与练度</h3>
                  <Space>
                    <Tag color="blue">羁绊位 {activeOption.bond_slots}</Tag>
                    <Tag color="purple">置信度 {activeOption.confidence}</Tag>
                  </Space>
                </div>
                {activeOption.required_servants.map((servant) => (
                  <div className="ga-phase" key={servant.name}>
                    <span className="ga-phase-index">{servant.class_name.slice(0, 2)}</span>
                    <span>
                      <strong>{servant.name}</strong>
                      <small className="ga-muted">
                        Lv{servant.level ?? '?'} · 宝具 {servant.np_level ?? '?'} · 技能{' '}
                        {servant.skills.join('/')} · 攻击 {formatDamage(servant.attack)}
                        {servant.attack_source === 'class_rarity_median' ? '（中位数回退）' : ''} · 职阶倍率{' '}
                        {servant.damage_multiplier} · 宝具倍率 {servant.np_multiplier}
                        {servant.np_card ? ` · ${servant.np_card}` : ''}
                        {servant.np_target_type ? ` · ${servant.np_target_type}` : ''}
                      </small>
                    </span>
                  </div>
                ))}
              </div>

              <div className="ga-card">
                <h3>每回合行动与模拟结果</h3>
                <Space wrap style={{ marginTop: 8 }}>
                  <Tag color={activeOption.simulation.status === 'success' ? 'green' : 'red'}>
                    模拟 {activeOption.simulation.status}
                  </Tag>
                  <Tag>清场回合 {activeOption.simulation.cleared_by_turn ?? '未清场'}</Tag>
                  <Tag>估算总伤害 {formatDamage(activeOption.simulation.total_damage_avg)}</Tag>
                </Space>
                {activeOption.simulation.turns.map((turn) => (
                  <div className="ga-phase" key={turn.turn}>
                    <span className="ga-phase-index">T{turn.turn}</span>
                    <span>
                      <strong>
                        剩余敌人 {turn.enemies_remaining} · 剩余血量 {formatDamage(turn.total_enemy_hp_remaining)}
                      </strong>
                      <small className="ga-muted">
                        {turn.actions
                          .map((action) => `位置${action.actor_slot} ${action.action_type} 伤害 ${formatDamage(action.damage_avg)}`)
                          .join('；')}
                      </small>
                    </span>
                  </div>
                ))}
                {activeOption.simulation.errors.length ? (
                  <BulletList title="模拟错误" items={activeOption.simulation.errors} tone="red" />
                ) : null}
              </div>

              <div className="ga-grid-2">
                <div className="ga-card">
                  <BulletList title="最低练度要求" items={activeOption.minimum_investment} />
                  <BulletList title="替代方案" items={activeOption.alternatives} />
                </div>
                <div className="ga-card">
                  <BulletList title="失败条件" items={activeOption.failure_conditions} tone="orange" />
                  <BulletList title="缺失数据" items={activeOption.missing_data} />
                </div>
              </div>

              <div className="ga-card">
                <h3>礼装可行性确认</h3>
                <p className="ga-small ga-muted">
                  推荐阶段按需求假定礼装可用；进入 Dry Run 或执行前必须逐项确认。未确认时执行预检会保持阻塞。
                </p>
                {activeOption.required_craft_essences.map((essence) => (
                  <div key={essence} style={{ marginTop: 6 }}>
                    <Checkbox
                      checked={checkedEssences.includes(essence)}
                      onChange={(event) => toggleAvailable(activePlanId, essence, event.target.checked)}
                    >
                      {essence}
                    </Checkbox>
                  </div>
                ))}
                <Space wrap style={{ marginTop: 10 }}>
                  <Button type="primary" loading={savingConfirmation} onClick={() => void handleSaveConfirmation()}>
                    确认所选礼装可用
                  </Button>
                  {confirmation ? (
                    <Tag color={confirmation.confirmed && !missingEssences.length ? 'green' : 'orange'}>
                      已保存：确认 {confirmation.confirmed ? '是' : '否'} · 缺 {missingEssences.length} 项 ·{' '}
                      {confirmation.updated_at}
                    </Tag>
                  ) : (
                    <Tag>尚无确认记录</Tag>
                  )}
                </Space>
              </div>

              <div className="ga-card">
                <div className="ga-row ga-between">
                  <h3>执行预检</h3>
                  <Button loading={runningPreflight} onClick={() => void handlePreflight()} disabled={!activePlanId}>
                    运行预检
                  </Button>
                </div>
                {preflight ? (
                  <>
                    <Alert
                      style={{ marginTop: 10 }}
                      type={preflight.can_execute ? 'success' : preflight.can_dry_run ? 'info' : 'warning'}
                      showIcon
                      message={preflight.summary}
                      description={`可 Dry Run：${preflight.can_dry_run ? '是' : '否'} · 可执行：${
                        preflight.can_execute ? '是' : '否'
                      }`}
                    />
                    {preflight.checks.map((check) => (
                      <div className="ga-phase" key={check.check_id}>
                        <span className="ga-phase-index">
                          <Tag color={CHECK_TONE[check.status]}>{check.status}</Tag>
                        </span>
                        <span>
                          <strong>{check.label}</strong>
                          <small className="ga-muted">{check.detail}</small>
                        </span>
                      </div>
                    ))}
                  </>
                ) : (
                  <p className="ga-small ga-muted" style={{ marginTop: 8 }}>
                    <Tooltip title="预检会校验档案验证状态、模拟清场、礼装确认、助战与模拟器资源。">
                      尚未运行
                    </Tooltip>
                  </p>
                )}
              </div>

              <div className="ga-card">
                <BulletList title="本方案的假设" items={activeOption.assumptions} />
                <BulletList title="需要保留的注意事项" items={activeOption.plan.warnings} />
              </div>
            </>
          ) : null}
        </>
      ) : (
        <div className="ga-card">
          <Spin spinning={recommending} />
          <p className="ga-small ga-muted" style={{ marginTop: 8 }}>
            选择关卡后点击“生成推荐”，会给出候选队伍、每回合宝具动作、伤害与宝具闸门、最低练度要求、替代方案和失败条件。
          </p>
        </div>
      )}
    </div>
  );
}
