// 执行页：选方案 → 显式确认 AP → 开始 / 停止 → 实时步骤流 + 现场截图。
//
// 安全口径（与后端 execution_router 一致）：
//   * 每次运行都要显式确认（每局真实扣 40 AP，连刷 N 局就是 N×40）；
//   * 「从地图开刷」会走：点关卡卡片 → 选助战 →（必要时）开始任务 → 进本；
//   * 停手时把**原因 + 现场截图 + 退路**直接摆出来（点完「连续出击」后不想继续刷，
//     可以点「关闭」退出，不必把那一局打掉）。
import {
  Alert,
  Button,
  Card,
  Empty,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  message,
} from 'antd';
import {
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  archiveRunbook,
  checkRunbook,
  executionEvidenceUrl,
  loadExecutionOptions,
  loadExecutionStatus,
  startExecution,
  stopExecution,
  unarchiveRunbook,
  type ExecutionOptions,
  type ExecutionStatus,
  type RunbookOption,
} from '../stores/gameAssistant';
import RunbookBuilder from './RunbookBuilder';

const POLL_MS = 2000;
const AP_PER_RUN = 40;

const VERDICT_COLOR: Record<string, string> = {
  ok: 'green',
  'battle_over': 'blue',
  paused: 'orange',
  abort: 'red',
  'dry-run': 'default',
};

function isStopReason(verdict?: string | null): boolean {
  return verdict === 'abort' || verdict === 'paused';
}

export default function ExecutionPanel() {
  const [options, setOptions] = useState<ExecutionOptions | null>(null);
  const [status, setStatus] = useState<ExecutionStatus | null>(null);
  const [spec, setSpec] = useState('');
  const [layout, setLayout] = useState('');
  const [rounds, setRounds] = useState(1);
  const [autoApple, setAutoApple] = useState(0);
  const [enterQuest, setEnterQuest] = useState(true);
  const [supportRow, setSupportRow] = useState(0);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [checking, setChecking] = useState(false);
  const [allowEnded, setAllowEnded] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef<number | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await loadExecutionStatus();
      setStatus(next);
      setError('');
      return next;
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取执行状态失败');
      return null;
    }
  }, []);

  // 表单生成完新 runbook 之后，把下拉刷新一下（新文件会自动出现在 /options 里）
  const reloadOptions = useCallback(async () => {
    try {
      const loaded = await loadExecutionOptions();
      setOptions(loaded);
    } catch (err) {
      setError(err instanceof Error ? err.message : '刷新 runbook 列表失败');
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await loadExecutionOptions();
        if (cancelled) return;
        setOptions(loaded);
        setSpec((current) => current || loaded.runbooks[0] || '');
        setLayout((current) => current || loaded.layouts[0] || '');
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '读取可选项失败');
      }
      await refreshStatus();
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshStatus]);

  const running = Boolean(status?.running);

  // 运行中才轮询（每 2 秒）；停下就自动停轮询，避免无意义的请求。
  useEffect(() => {
    if (!running) {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current === null) {
      pollRef.current = window.setInterval(() => {
        void refreshStatus();
      }, POLL_MS);
    }
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [running, refreshStatus]);

  const progress = status?.progress;
  const lastSteps = progress?.last_steps ?? [];
  // runbook 的可用性：绑的活动结束了 ⇒ 下拉里标注 + 默认禁用（后端也会拦）
  const runbookItems: RunbookOption[] = options?.runbook_items ?? [];
  const selectedRunbook = runbookItems.find((item) => item.name === spec) ?? null;
  const selectedEnded = selectedRunbook?.availability === 'event_ended';
  const stopReason = useMemo(() => {
    for (let i = lastSteps.length - 1; i >= 0; i -= 1) {
      if (isStopReason(lastSteps[i].verdict)) return lastSteps[i];
    }
    return null;
  }, [lastSteps]);
  const evidence = progress?.latest_evidence ?? null;

  const handleStart = () => {
    if (!spec || !layout) {
      message.warning('先选 runbook 和 layout');
      return;
    }
    const apText = `${rounds} × ${AP_PER_RUN} = ${rounds * AP_PER_RUN} AP`;
    Modal.confirm({
      title: '确认开始刷本？',
      width: 520,
      okText: '确认开始（花 AP）',
      cancelText: '取消',
      content: (
        <div className="ga-small">
          <p>
            这次会跑 <b>{rounds}</b> 局，连续出击会自动开下一局，合计约 <b>{apText}</b>
            （本关每局 40 AP）。
          </p>
          {autoApple > 0 ? (
            <p>
              AP 不足时自动使用黄金果实，最多 <b>{autoApple}</b> 个（会消耗道具；用完仍不足会停手）。
            </p>
          ) : (
            <p className="ga-muted">不会自动使用金苹果；AP 不足时会停手。</p>
          )}
          <p>
            {enterQuest
              ? '会从当前画面把这一局开起来：地图上就点关卡卡片；已经停在「助战选择」屏就直接选助战 →（必要时）开始任务 → 进本。'
              : '不会点关卡卡片；要求当前就在主战斗界面（第 1 回合）或助战选择屏。'}
          </p>
          <p className="ga-muted">
            中途想停就点「停止」；停手后会给出原因和现场截图。另外：点了「连续出击」之后如果不打算继续刷，
            可以点「关闭」退出，不必把那一局打掉。
          </p>
        </div>
      ),
      onOk: async () => {
        setStarting(true);
        try {
          const result = await startExecution({
            spec,
            layout,
            rounds,
            enter_quest: enterQuest,
            support_row: supportRow,
            auto_apple: autoApple,
            confirm_ap: true,
            allow_ended: allowEnded,
          });
          message.success(`已开始（run ${result.run_id}）`);
          await refreshStatus();
        } catch (err) {
          const detail =
            (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
            (err instanceof Error ? err.message : '启动失败');
          message.error(detail);
        } finally {
          setStarting(false);
        }
      },
    });
  };

  // 自检：让执行器用"不执行"模式跑一遍（只截图判据，不点任何东西、不花 AP），
  // 先把"现在能不能起步 / 停在哪个屏"看清楚，再决定要不要真的开刷。
  const handleCheck = async () => {
    if (!spec) {
      message.warning('先选 runbook');
      return;
    }
    setChecking(true);
    try {
      const result = await checkRunbook(spec, { layout, enterQuest });
      Modal.info({
        title: result.ok ? '自检通过（没有点任何东西、没花 AP）' : '自检没通过（这是期望行为，不是错误）',
        width: 720,
        content: (
          <div className="ga-small">
            <p className="ga-muted">exit {result.exit_code ?? '-'} · {enterQuest ? '含从地图开刷的检查' : '只看当前画面'}</p>
            <pre className="ga-exec-log">{result.output_tail.join('\n') || '（没有输出）'}</pre>
          </div>
        ),
      });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (err instanceof Error ? err.message : '自检失败');
      message.error(detail);
    } finally {
      setChecking(false);
    }
  };

  // 归档 = 挪进 runbooks/_archive/（不删）。活动结束的 runbook 用这个退出下拉，复刻时还能翻。
  const handleArchive = () => {
    if (!spec) return;
    Modal.confirm({
      title: `归档 ${spec}？`,
      width: 520,
      okText: '归档（不删除）',
      cancelText: '取消',
      content: (
        <div className="ga-small">
          <p>文件会挪进 <code>runbooks/_archive/</code>，<b>不会删除</b>；执行页下拉里不再出现，随时可以恢复。</p>
          <p className="ga-muted">动作序列与 notes 都留在文件里，复刻或做同类 90++ 时可以拿来对照。</p>
        </div>
      ),
      onOk: async () => {
        setArchiving(true);
        try {
          const result = await archiveRunbook(spec);
          message.success(`已归档 ${result.name}（文件还在 runbooks/_archive/）`);
          await reloadOptions();
        } catch (err) {
          message.error(err instanceof Error ? err.message : '归档失败');
        } finally {
          setArchiving(false);
        }
      },
    });
  };

  const handleUnarchive = async (name: string) => {
    try {
      await unarchiveRunbook(name);
      message.success(`已恢复 ${name}`);
      await reloadOptions();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '恢复失败');
    }
  };

  const handleStop = async () => {
    setStopping(true);
    try {
      const result = await stopExecution();
      message.info(result.stopped ? '已发出停止' : result.reason ?? '当前没有在跑的运行');
      await refreshStatus();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '停止失败');
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="ga-section-stack">
      <div className="ga-heading">
        <div>
          <h2>执行</h2>
          <p className="ga-small ga-muted">
            只执行已确认的活动 FREE 本 3T 方案；每一步都会留截图证据。
          </p>
        </div>
        <Space wrap>
          {running ? (
            <Tag color="processing">运行中 · {status?.run_id}</Tag>
          ) : status?.exit_code !== null && status?.exit_code !== undefined ? (
            <Tag color={status.exit_code === 0 ? 'green' : 'red'}>
              上次结束（exit {status.exit_code}）
            </Tag>
          ) : (
            <Tag>空闲</Tag>
          )}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => void refreshStatus()}
          >
            刷新
          </Button>
        </Space>
      </div>

      <Alert
        type="warning"
        showIcon
        message="执行范围受控"
        description="主线本和高难本明确排除；每一局都真实消耗 AP（本关 40）。停手时设备会停在当时的画面，需要人工确认。"
      />

      {error ? <Alert type="error" showIcon message={error} /> : null}

      <RunbookBuilder onCreated={() => void reloadOptions()} />

      <Card size="small" title="运行设置">
        <div className="ga-exec-grid">
          <label>
            <span className="ga-small ga-muted">runbook（配队动作流）</span>
            <Select
              value={spec || undefined}
              onChange={setSpec}
              options={
                runbookItems.length
                  ? runbookItems.map((item) => ({
                      value: item.name,
                      label: item.availability === 'event_ended'
                        ? `活动已结束 · ${item.name}`
                        : item.name,
                      disabled: item.availability === 'event_ended' && !allowEnded,
                    }))
                  : (options?.runbooks ?? []).map((name) => ({ value: name, label: name }))
              }
              placeholder="选择 runbook"
              disabled={running}
            />
          </label>
          <label>
            <span className="ga-small ga-muted">layout（本会话坐标）</span>
            <Select
              value={layout || undefined}
              onChange={setLayout}
              options={(options?.layouts ?? []).map((name) => ({ value: name, label: name }))}
              placeholder="选择 layout"
              disabled={running}
            />
          </label>
          <label>
            <span className="ga-small ga-muted">连刷局数（每局 40 AP）</span>
            <InputNumber
              min={1}
              max={99}
              value={rounds}
              onChange={(value) => setRounds(value ?? 1)}
              disabled={running}
              style={{ width: '100%' }}
            />
          </label>
          <label className="ga-exec-switch">
            <span className="ga-small ga-muted">
              <Tooltip title="AP 不足时自动使用黄金果实，最多 3 个；会消耗道具。用尽仍不足则停手，不会盲点">
                AP 不足时自动用金苹果（最多 3 个）
              </Tooltip>
            </span>
            <Switch
              checked={autoApple > 0}
              onChange={(value) => setAutoApple(value ? 3 : 0)}
              disabled={running}
            />
          </label>
          <label>
            <span className="ga-small ga-muted">
              <Tooltip title="0 = 按已登记的助战指纹自动认；填 N 会强制取第 N 行并把指纹存下来（首次登记 / 换助战用）">
                助战行（0 = 自动认）
              </Tooltip>
            </span>
            <InputNumber
              min={0}
              max={9}
              value={supportRow}
              onChange={(value) => setSupportRow(value ?? 0)}
              disabled={running}
              style={{ width: '100%' }}
            />
          </label>
          <label className="ga-exec-switch">
            <span className="ga-small ga-muted">
              <Tooltip title="会先在地图上点关卡卡片 → 选助战 →（必要时）开始任务；这一步就会扣 AP">
                从当前画面把这一局开起来（会进本、扣 AP）
              </Tooltip>
            </span>
            <Switch checked={enterQuest} onChange={setEnterQuest} disabled={running} />
          </label>
          <label className="ga-exec-switch">
            <span className="ga-small ga-muted">
              <Tooltip title="默认拦住：活动已结束的 runbook 绑的副本已经不在游戏里，而执行器认路靠关卡卡片模板、不认 quest_id ⇒ 硬跑会点到别的关卡、白烧 AP。只有你确认要手动对照时才打开">
                允许跑「活动已结束」（危险）
              </Tooltip>
            </span>
            <Switch checked={allowEnded} onChange={setAllowEnded} disabled={running} />
          </label>
        </div>
        {selectedEnded ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 10 }}
            message="这份 runbook 绑的活动已经结束"
            description={
              <div className="ga-small">
                <p>{selectedRunbook?.reason}</p>
                <p className="ga-muted">
                  建议归档（文件挪进 runbooks/_archive/，不会删）；复刻或做同类关卡时还能翻出来对照。
                </p>
              </div>
            }
            action={
              <Button size="small" danger loading={archiving} onClick={() => void handleArchive()}>
                归档这份
              </Button>
            }
          />
        ) : null}
        {options?.archived_runbooks?.length ? (
          <div className="ga-small ga-muted" style={{ marginTop: 8 }}>
            已归档 {options.archived_runbooks.length} 份（不在下拉里）：
            <Space wrap size={4} style={{ marginLeft: 6 }}>
              {options.archived_runbooks.map((name) => (
                <span key={name}>
                  {name}
                  <Button type="link" size="small" onClick={() => void handleUnarchive(name)}>
                    恢复
                  </Button>
                </span>
              ))}
            </Space>
          </div>
        ) : null}
        <Space wrap className="ga-exec-actions">
          <Button
            icon={<SafetyCertificateOutlined />}
            loading={checking}
            disabled={running || !spec}
            onClick={handleCheck}
          >
            自检（不点、不花 AP）
          </Button>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={starting}
            disabled={running || !spec || !layout}
            onClick={handleStart}
          >
            开始刷本
          </Button>
          <Button danger icon={<StopOutlined />} loading={stopping} disabled={!running} onClick={handleStop}>
            停止
          </Button>
          <span className="ga-small ga-muted">
            合计约 {rounds * AP_PER_RUN} AP · {rounds > 1 ? '连刷时会自动点「连续出击」+ 选助战' : '只打这一局'}
          </span>
        </Space>
      </Card>

      {stopReason ? (
        <Alert
          type={stopReason.verdict === 'abort' ? 'error' : 'warning'}
          showIcon
          icon={<WarningOutlined />}
          message={`停手：${stopReason.label ?? stopReason.kind ?? '未知步骤'}（${stopReason.verdict}）`}
          description={
            <div className="ga-small">
              <p>{stopReason.note ?? '没有记录原因'}</p>
              <p className="ga-muted">
                退路：点完「连续出击」之后如果不打算继续刷，可以点「关闭」退出，不必把那一局打掉；
                也可以按下面的现场截图判断当前停在哪一屏再决定。
              </p>
            </div>
          }
        />
      ) : null}

      <Card size="small" title="实时进度">
        {status?.run_id ? (
          <div className="ga-exec-progress">
            <div className="ga-small ga-muted ga-exec-meta">
              <span>run：{status.run_id}</span>
              <span>开始：{status.started_at || '-'}</span>
              <span>局数：{status.rounds}</span>
              {status.auto_apple ? <span>自动苹果上限：{status.auto_apple}</span> : null}
              <span>步骤：{progress?.steps_total ?? 0}</span>
              {progress?.support?.picked_row ? <span>助战第 {progress.support.picked_row} 行</span> : null}
            </div>
            <Space wrap>
              {Object.entries(progress?.by_verdict ?? {}).map(([verdict, count]) => (
                <Tag key={verdict} color={VERDICT_COLOR[verdict] ?? 'default'}>
                  {verdict} × {count}
                </Tag>
              ))}
            </Space>
            {evidence && status.run_id ? (
              <div className="ga-exec-evidence">
                <img
                  alt="最新现场截图"
                  src={`${executionEvidenceUrl(status.run_id, evidence.name)}?t=${evidence.mtime}`}
                />
                <span className="ga-small ga-muted">{evidence.name}</span>
              </div>
            ) : null}
            <div className="ga-exec-steps">
              {lastSteps.length === 0 ? (
                <span className="ga-small ga-muted">还没有步骤记录</span>
              ) : (
                lastSteps.map((step, index) => (
                  <div className="ga-exec-step" key={`${step.index}-${index}`}>
                    <Tag color={VERDICT_COLOR[step.verdict ?? ''] ?? 'default'}>{step.verdict}</Tag>
                    <span className="ga-small">
                      第 {step.round ?? '?'} 局 · #{step.index} {step.kind} {step.label}
                    </span>
                    {step.note ? <span className="ga-small ga-muted ga-exec-note">{step.note}</span> : null}
                  </div>
                ))
              )}
            </div>
            {progress?.log_tail?.length ? (
              <pre className="ga-exec-log">{progress.log_tail.join('\n')}</pre>
            ) : null}
            {status.run_dir ? <span className="ga-small ga-muted">证据目录：{status.run_dir}</span> : null}
          </div>
        ) : (
          <Empty description="还没有运行记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>
    </div>
  );
}
