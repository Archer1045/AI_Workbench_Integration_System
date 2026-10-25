import {
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  message,
} from 'antd';
import {
  CalendarOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  SafetyCertificateOutlined,
  ScheduleOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import dayjs from 'dayjs';
import AccountSnapshotPanel from './AccountSnapshotPanel';
import TeamPlannerPanel from './TeamPlannerPanel';
import ExecutionPanel from './ExecutionPanel';
import ActivityCalendar from './ActivityCalendar';
import ScheduleCard from './ScheduleCard';
import ProviderSettingsModal from './ProviderSettingsModal';
import SourceIngestPanel from './SourceIngestPanel';
import {
  generateFgoGuide,
  loadGameAssistantBootstrap,
  questAp,
  questLevel,
  questUnlock,
  type BootstrapResponse,
  type GuideGenerationResult,
  type GuideProvider,
  type PlanStep,
  type ProviderStatus,
  type QuestSummary,
} from '../stores/gameAssistant';
import { endedSummaryLabel, isEnded, shopWarning } from '../gameAssistantLifecycle';

const providerLabels: Record<GuideProvider, string> = {
  template: '确定性模板',
  local: '本地模型',
  deepseek: 'DeepSeek API',
  openai_compatible: 'OpenAI 兼容接口',
};

const goalPresets = [
  '默认目标：搬空有限商店',
  '当前阶段只刷到解锁下一阶段',
  '生成本期活动的当前阶段攻略',
];

const planStatus: Record<PlanStep['availability'], { label: string; tone: string }> = {
  current: { label: '当前', tone: 'green' },
  upcoming: { label: '待开放', tone: 'orange' },
  conditional: { label: '条件', tone: 'purple' },
  final: { label: '终段', tone: 'red' },
};

// 活动已结束时，计划里原本标「当前」的步骤不该再声称"当前"（2026-10-15 口径）。
const endedPlanStatus = { label: '已结束', tone: '' };

function phaseTime(value: string | null): string {
  if (!value) return '未标注';
  return value.replace('T', ' ').slice(0, 16);
}

function providerAvailable(providers: ProviderStatus[], provider: GuideProvider): boolean {
  return providers.some((item) => item.provider === provider && item.available);
}

function sourcePills(ids: string[], sourceMap: Map<string, string>) {
  return ids.map((id) => (
    <Tooltip key={id} title={sourceMap.get(id) || id}>
      <span className="ga-source">
        <LinkOutlined />
        {id}
      </span>
    </Tooltip>
  ));
}
export default function GameAssistantPanel() {
  const [messageApi, contextHolder] = message.useMessage();
  const [bootstrap, setBootstrap] = useState<BootstrapResponse | null>(null);
  const [result, setResult] = useState<GuideGenerationResult | null>(null);
  const [provider, setProvider] = useState<GuideProvider>('template');
  const [goal, setGoal] = useState(goalPresets[2]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [activeSection, setActiveSection] = useState<
    'activity' | 'calendar' | 'team' | 'execute' | 'account'
  >('activity');
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 已结束活动的复盘资料是否展开（默认收起，但记住用户的选择）。
  const [detailOpen, setDetailOpen] = useState(false);
  // 攻略结果抽屉（2026-10-15 布局优化）：结果就近弹出，**关掉不丢内容**
  // （数据在 result 状态 + 服务端 latest_generation 里，抽屉只管显示；头卡留「查看上次结果」入口）。
  const [resultOpen, setResultOpen] = useState(false);
  // 「活动资料」折叠块（阶段时间轴 / 关卡表 / 来源入料）默认收起。
  const [materialsOpen, setMaterialsOpen] = useState(false);
  // 生成失败的提示放在**按钮旁边**（不放抽屉里）：抽屉关掉也要看得到。
  const [genError, setGenError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    loadGameAssistantBootstrap()
      .then((data) => {
        if (!active) return;
        setBootstrap(data);
        setResult(data.latest_generation);
        setError('');
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : '游戏助手加载失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const providers = bootstrap?.providers || [];
  const providerOptions = (['template', 'local', 'deepseek', 'openai_compatible'] as GuideProvider[]).map((key) => {
    const status = providers.find((item) => item.provider === key);
    return {
      value: key,
      label: `${providerLabels[key]}${status?.model ? ` · ${status.model}` : ''}`,
      disabled: key !== 'template' && status ? !status.available : false,
    };
  });

  useEffect(() => {
    if (providers.length && !providerAvailable(providers, provider)) {
      setProvider('template');
    }
  }, [provider, providers]);

  const eventView = bootstrap?.event_view;
  const event = eventView?.event;
  const ended = isEnded(eventView?.event_status);
  const missingEventData = bootstrap?.event_data_status === 'missing_bundle';
  const noCurrentEvent = bootstrap?.event_data_status === 'no_current_event';
  const shop = eventView?.shop;
  const detailKey = event ? `ga.eventDetail.${event.event_id}.${event.revision}` : '';

  // 折叠状态按「活动 + revision」记住：换活动自动重置为收起。
  useEffect(() => {
    if (!detailKey) return;
    setDetailOpen(window.localStorage.getItem(detailKey) === '1');
    setMaterialsOpen(window.localStorage.getItem(`ga.materials.${detailKey}`) === '1');
  }, [detailKey]);

  useEffect(() => {
    setResultOpen(window.localStorage.getItem('ga.resultDrawerOpen') === '1');
  }, []);

  const toggleMaterials = () => {
    setMaterialsOpen((current) => {
      const next = !current;
      if (detailKey) window.localStorage.setItem(`ga.materials.${detailKey}`, next ? '1' : '0');
      return next;
    });
  };

  const closeResult = () => {
    setResultOpen(false);
    window.localStorage.setItem('ga.resultDrawerOpen', '0');
  };

  const openResult = () => {
    setResultOpen(true);
    window.localStorage.setItem('ga.resultDrawerOpen', '1');
  };

  const toggleDetail = () => {
    setDetailOpen((current) => {
      const next = !current;
      if (detailKey) window.localStorage.setItem(detailKey, next ? '1' : '0');
      return next;
    });
  };

  const sourceMap = useMemo(() => {
    return new Map((event?.sources || []).map((source) => [source.source_id, source.title]));
  }, [event]);
  // 头卡上的四个关键数字：一眼看清「这期还剩什么」。
  const eventSpanDays = event
    ? Math.max(1, dayjs(event.ends_at).diff(dayjs(event.starts_at), 'day') + 1)
    : 0;
  const shopLeftLabel = (() => {
    if (!ended) return '—';
    if (!shop || shop.state !== 'open' || !shop.ends_at) return '已关闭';
    return shop.ends_today ? `今天 ${dayjs(shop.ends_at).format('HH:mm')}` : `${shop.days_left} 天`;
  })();
  const availableFreeQuests = useMemo(() => {
    return (eventView?.available_quests || [])
      .filter((quest) => (quest.quest_type || quest.type) === 'free')
      .sort((left, right) => questAp(left) - questAp(right));
  }, [eventView]);

  const refreshBootstrap = async () => {
    try {
      const data = await loadGameAssistantBootstrap();
      setBootstrap(data);
      setResult(data.latest_generation);
      setError('');
    } catch (err) {
      messageApi.error(err instanceof Error ? err.message : '游戏助手刷新失败');
    }
  };

  const generate = async () => {
    if (!event || missingEventData || noCurrentEvent) {
      messageApi.warning('当前活动资料尚未导入，暂不能生成攻略。');
      return;
    }
    setGenerating(true);
    setGenError('');
    try {
      const response = await generateFgoGuide({
        provider,
        goal,
        event_id: event.event_id,
        revision: event.revision,
      });
      setResult(response);
      setResultOpen(true);                    // 只在**生成成功**这一下自动弹
      window.localStorage.setItem('ga.resultDrawerOpen', '1');
      if (response.fallback_reason) {
        messageApi.warning('模型调用失败，已回退到确定性模板。');
      } else {
        messageApi.success('本期活动攻略已生成。');
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : '攻略生成失败';
      setGenError(detail);
      messageApi.error(detail);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="game-assistant">
      {contextHolder}
      <div className="ga-systembar">
        <span className="ga-status">
          <span className={`ga-dot ${bootstrap ? '' : 'orange'}`} />
          {bootstrap ? '公开知识库已加载' : '正在加载公开知识库'}
        </span>
        <span className="ga-status">
          <DatabaseOutlined />
          账号快照独立保存 · 攻略生成不读取账号数据
        </span>
        <span className="ga-status">
          <SafetyCertificateOutlined />
          执行器已接入「执行」页 · 每次运行都会真实扣 AP
        </span>
        <span className="ga-status">
          <ClockCircleOutlined />
          {eventView ? `服务端时间 ${phaseTime(eventView.server_time)}` : '等待状态'}
        </span>
        <span className="ga-status">
          <PlayCircleOutlined />
          {missingEventData
            ? '活动已开始 · 资料待导入'
            : noCurrentEvent
              ? '暂无进行中的主要活动'
              : ended
                ? '本期活动已结束'
                : eventView?.current_phase?.name || '当前阶段未识别'}
        </span>
        <Button size="small" icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>
          模型设置
        </Button>
      </div>

      {loading ? (
        <div className="ga-loading">
          <Spin size="large" />
          <span>正在读取活动事实与历史生成结果...</span>
        </div>
      ) : error || !eventView || !event ? (
        <div className="ga-main-panel">
          <Alert
            type={error ? 'error' : 'info'}
            showIcon
            message={error ? '游戏助手知识库不可用' : '暂无进行中的主要活动'}
            description={
              error ||
              '活动日历中没有已确认且正在进行的主活动。历史活动不会自动显示为“本期活动”。'
            }
          />
        </div>
      ) : (
        <div className={`ga-layout ${activeSection === 'activity' ? '' : 'account-mode'}`}>
          <aside className="ga-nav">
            <div className="ga-game">
              <span className="ga-game-icon">
                <ExperimentOutlined />
              </span>
              <span>
                <strong>FGO</strong>
                <small>国服 · {event.server}</small>
              </span>
            </div>
            {[
              { key: 'activity', label: '本期活动', icon: <CalendarOutlined /> },
              { key: 'calendar', label: '活动日历', icon: <ScheduleOutlined /> },
              { key: 'team', label: '3T 组队', icon: <TeamOutlined /> },
              { key: 'execute', label: '执行', icon: <PlayCircleOutlined /> },
              { key: 'account', label: '账号基础资源', icon: <DatabaseOutlined /> },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                className={`ga-navbtn ${item.key === activeSection ? 'active' : ''}`}
                onClick={() =>
                  setActiveSection(item.key as 'activity' | 'calendar' | 'team' | 'execute' | 'account')}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </aside>

          <main className="ga-main">
            {activeSection === 'account' ? (
              <AccountSnapshotPanel />
            ) : activeSection === 'calendar' ? (
              <ActivityCalendar eventView={eventView} />
            ) : activeSection === 'team' ? (
              <TeamPlannerPanel />
            ) : activeSection === 'execute' ? (
              <ExecutionPanel />
            ) : (
              <>
            <ScheduleCard onOpenCalendar={() => setActiveSection('calendar')} />
            {missingEventData ? (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 10 }}
                message="本期活动已经开放，但活动资料尚未导入"
                description="已按活动日历识别当前主活动；在关卡、阶段和商店资料发布前，不会复用上一期活动，也不提供复盘攻略入口。"
              />
            ) : null}
            {ended ? (
              <div className={`ga-ended-bar${shopWarning(shop) ? ' warn' : ''}`}>
                <div className="ga-row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <strong>{event.title}</strong>
                  <span className="ga-pill">已结束</span>
                  <span className="ga-small ga-muted">{endedSummaryLabel(shop)}</span>
                  {eventView.quests_closed_at ? (
                    <span className="ga-small ga-muted">
                      副本已于 {phaseTime(eventView.quests_closed_at)} 关闭
                    </span>
                  ) : null}
                </div>
                <Button size="small" onClick={toggleDetail}>
                  {detailOpen ? '收起复盘资料' : '展开复盘资料'}
                </Button>
              </div>
            ) : null}
            <div className="ga-card">
              <div className="ga-heading">
                <div>
                  <h2>{event.title}</h2>
                  <p className="ga-small ga-muted">
                    {event.server} · revision {event.revision} · {phaseTime(event.starts_at)} 至{' '}
                    {phaseTime(event.ends_at)}
                  </p>
                </div>
                <div className="ga-actions">
                  {event.tags.map((tag) => (
                    <Tag key={tag} color="blue">
                      {tag}
                    </Tag>
                  ))}
                  {ended ? <span className="ga-pill">复盘</span> : null}
                  {result ? (
                    <Button size="small" onClick={openResult}>
                      查看上次结果（{phaseTime(result.created_at).slice(-5)}）
                    </Button>
                  ) : null}
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    loading={generating}
                    disabled={missingEventData || noCurrentEvent || !providerAvailable(providers, provider)}
                    onClick={() => void generate()}
                  >
                    {missingEventData
                      ? '活动资料待导入'
                      : noCurrentEvent
                        ? '暂无本期活动'
                        : ended
                          ? '生成复盘攻略'
                          : '生成当前阶段攻略'}
                  </Button>
                </div>
              </div>
              <div className="ga-stats">
                <span className="ga-stat">
                  <span className="ga-small ga-muted">活动周期</span>
                  <b>{eventSpanDays} 天</b>
                </span>
                <span className="ga-stat">
                  <span className="ga-small ga-muted">商店剩余</span>
                  <b>{shopLeftLabel}</b>
                </span>
                <span className="ga-stat">
                  <span className="ga-small ga-muted">阶段数</span>
                  <b>{eventView.event.phases.length}</b>
                </span>
                <span className="ga-stat">
                  <span className="ga-small ga-muted">可刷关卡</span>
                  <b>{availableFreeQuests.length}</b>
                </span>
              </div>
              {genError ? (
                <Alert
                  type="error"
                  showIcon
                  style={{ marginTop: 8 }}
                  message="攻略生成失败"
                  description={genError}
                />
              ) : null}
            </div>

            {!ended || detailOpen ? (
            <>
            <div className="ga-grid-3">
              <div className="ga-card">
                <p className="ga-small ga-muted">{ended ? '最后阶段' : '当前阶段'}</p>
                <strong>{eventView.current_phase?.name || '未开始'}</strong>
                <p className="ga-small ga-muted">
                  {eventView.current_phase?.summary || '等待阶段资料'}
                </p>
              </div>
              <div className="ga-card">
                <p className="ga-small ga-muted">{ended ? '后续阶段' : '下一开放'}</p>
                <strong>{eventView.next_phase?.name || '无'}</strong>
                <p className="ga-small ga-muted">
                  {eventView.next_phase
                    ? `${phaseTime(eventView.next_phase.opens_at)} · ${eventView.next_phase.unlock_condition}`
                    : '没有已登记的后继阶段'}
                </p>
              </div>
              <div className="ga-card">
                <p className="ga-small ga-muted">{ended ? '已结束的关卡' : '当前自由本'}</p>
                <strong>{availableFreeQuests.length} 个</strong>
                <p className="ga-small ga-muted">
                  {ended ? '活动已结束，这些关卡不能再刷（保留作复盘）' : '仅表示公共时间表已开放，不代表账号首通状态'}
                </p>
              </div>
            </div>

            {/* 长内容收进「活动资料」，默认收起（2026-10-15 布局优化） */}
            <div className="ga-slim-row">
              <span className="ga-small ga-muted">
                活动资料：阶段时间轴（{eventView.event.phases.length} 个阶段）· 关卡表（
                {availableFreeQuests.length} 关）· 来源与入料
              </span>
              <Button size="small" onClick={toggleMaterials}>
                {materialsOpen ? '收起' : '展开'}
              </Button>
            </div>
            {materialsOpen ? (
              <>
            <SourceIngestPanel
              eventId={event.event_id}
              revision={event.revision}
              providers={providers}
              onPublished={() => void refreshBootstrap()}
              onOpenSettings={() => setSettingsOpen(true)}
            />

            <div className="ga-card">
              <div className="ga-row ga-between">
                <h3>活动时间轴</h3>
                <span className="ga-pill">{eventView.event.phases.length} 个阶段</span>
              </div>
              <div className="ga-phase-list">
                {eventView.event.phases.map((phase, index) => {
                  const opened = Boolean(phase.opens_at && phase.opens_at <= eventView.server_time);
                  const current = !ended && eventView.current_phase?.phase_id === phase.phase_id;
                  return (
                    <div
                      key={phase.phase_id}
                      className={`ga-phase ${current ? 'active' : ''} ${opened && !current ? 'expired' : ''} ${!opened ? 'locked' : ''}`}
                    >
                      <span className="ga-phase-index">D{index + 1}</span>
                      <span>
                        <strong>{phase.name}</strong>
                        <small className="ga-muted">
                          {phaseTime(phase.opens_at)} · {phase.unlock_condition || '按公告'}
                        </small>
                      </span>
                      <span className={`ga-pill ${current ? 'green' : opened ? '' : 'orange'}`}>
                        {current ? '当前' : opened ? '已开放' : '待开放'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="ga-card">
              <div className="ga-row ga-between">
                <h3>{ended ? '已结束的关卡（不可再刷）' : '当前自由本与 AP'}</h3>
                <span className="ga-pill">{ended ? '复盘用' : '公共事实'}</span>
              </div>
              <table className="ga-table">
                <thead>
                  <tr>
                    <th>关卡</th>
                    <th>地点</th>
                    <th>推荐等级</th>
                    <th>AP</th>
                    <th>开放条件</th>
                  </tr>
                </thead>
                <tbody>
                  {availableFreeQuests.map((quest) => (
                    <tr key={quest.quest_id}>
                      <td>{quest.name}</td>
                      <td>{quest.location}</td>
                      <td>{questLevel(quest)}</td>
                      <td>{questAp(quest)}</td>
                      <td>{questUnlock(quest)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
              </>
            ) : null}
            </>
            ) : null}
              </>
            )}
          </main>

          {activeSection === 'activity' && (
          <aside className="ga-assistant">
            <div className="ga-heading">
              <div>
                <h3>
                  {missingEventData
                    ? '本期活动资料待导入'
                    : ended
                      ? '本期活动回顾（复盘）'
                      : '本期活动攻略'}
                </h3>
                <p className="ga-small ga-muted">公开资料生成 · 账号状态未接入</p>
              </div>
              <span className="ga-pill purple">候选</span>
            </div>
            <div className="ga-bubble">
              {missingEventData
                ? '当前活动已经识别，但缺乏可发布的关卡与阶段资料。导入并确认活动资料后才能生成攻略。'
                : '我会基于当前活动事实生成本期活动攻略。3T 队伍请进入“3T 组队”；本页不会点击游戏，也不会读取账号数据。'}
            </div>
            <div className="ga-chips">
              {goalPresets.map((preset) => (
                <button key={preset} type="button" className="ga-chip" onClick={() => setGoal(preset)}>
                  {preset}
                </button>
              ))}
            </div>
            <div className="ga-soft ga-side-card">
              <strong>生成 Provider</strong>
              <Select
                value={provider}
                onChange={setProvider}
                options={providerOptions}
                style={{ width: '100%', marginTop: 8 }}
              />
              {providers.map((status) => (
                <div key={status.provider} className="ga-provider-row">
                  <span className={`ga-dot ${status.available ? '' : 'red'}`} />
                  <span>{providerLabels[status.provider]}</span>
                  <span className="ga-small ga-muted">{status.available ? '可用' : '未配置'}</span>
                </div>
              ))}
            </div>
            <Input.TextArea
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              autoSize={{ minRows: 3, maxRows: 5 }}
              placeholder="描述本次攻略目标"
            />
            <Button
              type="default"
              icon={<PlayCircleOutlined />}
              loading={generating}
              disabled={missingEventData || noCurrentEvent || !providerAvailable(providers, provider)}
              onClick={() => void generate()}
            >
              {missingEventData
                ? '活动资料待导入'
                : noCurrentEvent
                  ? '暂无本期活动'
                  : ended
                    ? '生成复盘攻略'
                    : '生成当前阶段攻略'}
            </Button>
            <p className="ga-small ga-muted">
              生成后结果会从右侧滑出；关掉也不会丢，头卡上有「查看上次结果」。
            </p>
            <div className="ga-soft ga-side-card">
              <div className="ga-row ga-between">
                <strong>来源</strong>
                <span className="ga-pill">{event.sources.length} 条</span>
              </div>
              <div className="ga-source-list">
                {event.sources.map((source) => (
                  <Tooltip key={source.source_id} title={source.title}>
                    <a href={source.url} target="_blank" rel="noreferrer">
                      <LinkOutlined />
                      {source.source_id}
                    </a>
                  </Tooltip>
                ))}
              </div>
            </div>
          </aside>
          )}
        </div>
      )}

      {activeSection === 'activity' && !loading && event && (
        <Drawer
          title={result ? '攻略生成结果' : '攻略生成结果（还没有内容）'}
          placement="right"
          width={520}
          open={resultOpen}
          onClose={closeResult}
        >
          <div className="ga-results">
            <div className="ga-card">
              <div className="ga-row ga-between">
                <div>
                  <h3>攻略生成结果</h3>
                  <p className="ga-small ga-muted">
                    {result
                      ? `${result.provider_used} · ${result.model} · ${phaseTime(result.created_at)}`
                      : '尚未生成'}
                  </p>
                  {result && <p className="ga-small">目标：{result.plan.objective}</p>}
                </div>
                {result && (
                  <span className={`ga-pill ${result.fallback_reason ? 'orange' : 'green'}`}>
                    {result.fallback_reason ? '已回退模板' : '生成成功'}
                  </span>
                )}
              </div>
              {result ? (
                <div className="ga-guide">
                  <Alert
                    type={result.fallback_reason ? 'warning' : 'info'}
                    showIcon
                    message={result.fallback_reason || result.guide.summary}
                  />
                  {result.guide.sections.map((section) => (
                    <div key={section.heading} className="ga-guide-section">
                      <div className="ga-row ga-between">
                        <h3>{section.heading}</h3>
                        <div className="ga-row">{sourcePills(section.citation_ids, sourceMap)}</div>
                      </div>
                      {section.summary && <p className="ga-small ga-muted">{section.summary}</p>}
                      <ul>
                        {section.bullets.map((bullet) => (
                          <li key={bullet}>{bullet}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {result.warnings.length > 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      message="不确定项"
                      description={result.warnings.join('；')}
                    />
                  )}
                </div>
              ) : (
                <Empty description="尚未生成攻略" />
              )}
            </div>

            <div className="ga-card" style={{ marginTop: 10 }}>
              <div className="ga-row ga-between">
                <div>
                  <h3>活动推进提示</h3>
                  <p className="ga-small ga-muted">只描述活动阶段推进，不代表 3T 队伍或执行脚本</p>
                </div>
                <span className="ga-pill orange">活动进度</span>
              </div>
              {result ? (
                <div className="ga-plan-list">
                  {result.plan.steps.map((step, index) => {
                    const status = ended && step.availability === 'current'
                      ? endedPlanStatus
                      : planStatus[step.availability];
                    const active = !ended && step.availability === 'current';
                    return (
                      <div key={step.step_id} className={`ga-phase ${active ? 'active' : ''}`}>
                        <span className="ga-phase-index">{index + 1}</span>
                        <span>
                          <strong>{step.title}</strong>
                          <small className="ga-muted">{step.action}</small>
                          <small className="ga-muted">
                            {step.condition || step.stop_condition}
                          </small>
                        </span>
                        <span className={`ga-pill ${status.tone}`}>{status.label}</span>
                      </div>
                    );
                  })}
                  <Alert
                    type="warning"
                    showIcon
                    message="推进边界"
                    description={result.plan.stop_conditions.join('；')}
                  />
                </div>
              ) : (
                <Empty description="生成攻略后同时产出活动推进提示" />
              )}
            </div>
          </div>
        </Drawer>
      )}
      <ProviderSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onChanged={() => void refreshBootstrap()}
      />
    </div>
  );
}
