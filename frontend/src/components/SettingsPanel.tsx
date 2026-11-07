// 全局设置页：服务管理、默认参数、数据保留策略
import { DatabaseOutlined, SaveOutlined } from '@ant-design/icons';
import { Button, InputNumber, message, Popconfirm, Select, Space, Switch, Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';
import { api, type BackupItem, type ServiceSupervision } from '../api';
import { autoShutdownStore, cancelAutoShutdown, loadAutoShutdown, saveAutoShutdown } from '../stores/autoShutdown';
import { getRuntimeConfig } from '../stores/runtimeConfig';
import { refreshServices, servicesStore } from '../stores/services';
import WebToolsSettings from './WebToolsSettings';

const VLM_OPTIONS = ['huihui_ai/qwen2.5-vl-abliterated:7b', 'qwen2.5vl:7b', 'qwen2.5vl:3b'];

export default function SettingsPanel() {
  const { ollama, comfyui } = servicesStore;
  const settingsConfig = getRuntimeConfig().settings;
  const backupConfig = getRuntimeConfig().backup;
  const [supervision, setSupervision] = useState<ServiceSupervision | null>(null);
  const [savingSupervision, setSavingSupervision] = useState(false);
  const [retentionDays, setRetentionDays] = useState(settingsConfig.data_retention_default);
  const [retentionSaving, setRetentionSaving] = useState(false);
  const [visualReview, setVisualReview] = useState(true);
  const [vlmModel, setVlmModel] = useState('');
  const [cleaning, setCleaning] = useState(false);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [backingUp, setBackingUp] = useState(false);
  const [semanticCheck, setSemanticCheck] = useState(false);

  const loadBackups = async () => {
    try {
      const { data } = await api.get<{ items: BackupItem[] }>('/system/backups');
      setBackups(data.items || []);
    } catch {
      setBackups([]);
    }
  };

  const handleBackup = async () => {
    setBackingUp(true);
    try {
      const { data } = await api.post<{ ok: boolean; backup: BackupItem & { path: string } }>('/system/backup');
      message.success(`数据库备份完成：${data.backup.name}（${data.backup.size_mb}MB）`);
      await loadBackups();
    } catch {
      message.error('数据库备份失败');
    } finally {
      setBackingUp(false);
    }
  };

  useEffect(() => {
    void refreshServices();
    void loadAutoShutdown().catch(() => undefined);
    let cancelled = false;
    void Promise.all([
      api.get<ServiceSupervision>('/settings/service-supervision'),
      api.get<{ days: number }>('/settings/data-retention'),
      api.get<{ enabled: boolean }>('/settings/visual-review'),
      api.get<{ model: string }>('/settings/vlm-model'),
      api.get<{ items: BackupItem[] }>('/system/backups'),
      api.get<{ enabled: boolean }>('/settings/prompt-semantic-check'),
    ])
      .then(([sup, retention, visual, vlm, backupList, semantic]) => {
        if (cancelled) return;
        setSupervision(sup.data);
        setRetentionDays(retention.data.days);
        setVisualReview(Boolean(visual.data.enabled));
        setVlmModel(vlm.data.model);
        setBackups(backupList.data.items || []);
        setSemanticCheck(Boolean(semantic.data.enabled));
      })
      .catch(() => message.error('加载全局设置失败'));
    return () => {
      cancelled = true;
    };
  }, []);

  const saveSupervision = async (patch: Partial<ServiceSupervision>) => {
    if (!supervision) return;
    setSavingSupervision(true);
    try {
      const { data } = await api.post<ServiceSupervision>('/settings/service-supervision', { ...patch });
      setSupervision(data);
      message.success('服务管理设置已保存');
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '保存失败');
    } finally {
      setSavingSupervision(false);
    }
  };

  const saveRetention = async () => {
    setRetentionSaving(true);
    try {
      const { data } = await api.post<{ days: number }>('/settings/data-retention', { days: retentionDays });
      setRetentionDays(data.days);
      message.success('数据保留策略已保存');
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '保存失败');
    } finally {
      setRetentionSaving(false);
    }
  };

  const handleCleanup = async () => {
    setCleaning(true);
    try {
      const { data } = await api.post<{ deleted: Record<string, number> }>('/records/cleanup', { days: retentionDays });
      message.success(
        `清理完成：招聘 ${data.deleted.agent || 0} 条，绘画 ${data.deleted.draw || 0} 条，提示词 ${data.deleted.prompt || 0} 条`,
      );
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '清理失败');
    } finally {
      setCleaning(false);
    }
  };

  const toggleVisualReview = async (checked: boolean) => {
    setVisualReview(checked);
    try {
      await api.post('/settings/visual-review', { enabled: checked });
    } catch {
      setVisualReview(!checked);
      message.error('保存失败');
    }
  };

  const changeVlmModel = async (value: string) => {
    setVlmModel(value);
    try {
      await api.post('/settings/vlm-model', { model: value });
      message.success(`视觉模型已切换：${value}`);
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '切换失败');
    }
  };

  const toggleSemanticCheck = async (checked: boolean) => {
    setSemanticCheck(checked);
    try {
      await api.post('/settings/prompt-semantic-check', { enabled: checked });
      message.success(checked ? '提示词 AI 语义校验已开启' : '提示词 AI 语义校验已关闭');
    } catch {
      setSemanticCheck(!checked);
      message.error('保存失败');
    }
  };

  const toggleAutoShutdown = async (checked: boolean) => {
    try {
      const data = await saveAutoShutdown({ enabled: checked });
      if (checked) {
        message.success(`任务完成后自动关机已开启：任务正常完成后 ${data.delay_seconds} 秒自动关机`);
      } else {
        message.success('任务完成后自动关机已关闭');
      }
    } catch {
      message.error('自动关机设置保存失败');
    }
  };

  const changeAutoShutdownDelay = async (value: number | null) => {
    if (value == null) return;
    try {
      const data = await saveAutoShutdown({ delay_seconds: value });
      message.success(`关机前等待时间已更新为 ${data.delay_seconds} 秒`);
    } catch {
      message.error('关机前等待时间保存失败');
    }
  };

  const handleCancelAutoShutdown = async () => {
    try {
      await cancelAutoShutdown();
      message.success('已取消本次自动关机');
    } catch {
      message.error('取消自动关机失败');
    }
  };

  const autoShutdownText = (() => {
    if (!autoShutdownStore.enabled) return '未启用';
    if (autoShutdownStore.phase === 'pending') {
      return `任务已完成，${autoShutdownStore.remaining_seconds ?? 0} 秒后自动关机`;
    }
    if (autoShutdownStore.phase === 'executed') return '已发送关机指令';
    if (autoShutdownStore.phase === 'error') return `关机失败：${autoShutdownStore.last_error || '未知错误'}`;
    return '等待任务完成后自动关机';
  })();

  return (
    <div className="settings-page">
      <div className="panel-box">
        <h3 className="settings-section-title">服务管理</h3>
        <Space wrap style={{ marginBottom: 10 }}>
          <Tag color={ollama ? 'green' : 'red'}>Ollama {ollama ? '运行中' : '未运行'}</Tag>
          <Tag color={comfyui ? 'green' : 'red'}>ComfyUI {comfyui ? '运行中' : '未运行'}</Tag>
          <Tag>
            连续失败 Ollama {supervision?.consecutive?.ollama ?? 0} / ComfyUI {supervision?.consecutive?.comfyui ?? 0}
          </Tag>
        </Space>
        <div className="settings-grid">
          <div className="setting-field">
            <Tooltip title="后端启动时自动在后台拉起 Ollama 与 ComfyUI。">
              <span className="setting-label">启动时自动启动服务</span>
            </Tooltip>
            <Switch
              checked={supervision?.auto_start ?? false}
              onChange={(checked) => void saveSupervision({ auto_start: checked })}
            />
          </div>
          <div className="setting-field">
            <Tooltip title="服务连续健康检查失败达到阈值后自动重启。">
              <span className="setting-label">自动重启</span>
            </Tooltip>
            <Switch
              checked={supervision?.auto_restart ?? true}
              onChange={(checked) => void saveSupervision({ auto_restart: checked })}
            />
          </div>
          <div className="setting-field">
            <Tooltip title="健康探活的检查间隔。">
              <span className="setting-label">探活间隔（秒）</span>
            </Tooltip>
            <InputNumber
              min={settingsConfig.health_interval_min}
              max={settingsConfig.health_interval_max}
              value={supervision?.interval_seconds ?? settingsConfig.health_interval_default}
              onChange={(value) =>
                void saveSupervision({
                  interval_seconds: value ?? settingsConfig.health_interval_default,
                })
              }
              style={{ width: '100%' }}
            />
          </div>
          <div className="setting-field">
            <Tooltip title="连续失败多少次后自动重启服务。">
              <span className="setting-label">连续失败阈值</span>
            </Tooltip>
            <InputNumber
              min={settingsConfig.max_failures_min}
              max={settingsConfig.max_failures_max}
              value={supervision?.max_failures ?? settingsConfig.max_failures_default}
              onChange={(value) =>
                void saveSupervision({
                  max_failures: value ?? settingsConfig.max_failures_default,
                })
              }
              style={{ width: '100%' }}
            />
          </div>
        </div>
        {savingSupervision ? (
          <Tag color="blue" style={{ marginTop: 8 }}>
            保存中...
          </Tag>
        ) : null}
      </div>

      <div className="panel-box">
        <h3 className="settings-section-title">默认参数</h3>
        <div className="settings-grid">
          <div className="setting-field">
            <Tooltip title="识别图片与生成后视觉复核使用的视觉模型。">
              <span className="setting-label">视觉模型</span>
            </Tooltip>
            <Select
              value={vlmModel || undefined}
              placeholder="选择模型"
              options={VLM_OPTIONS.map((value) => ({ label: value, value }))}
              onChange={(value) => void changeVlmModel(value)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="setting-field">
            <Tooltip title="AI 绘画完成后使用视觉模型复核人数与角色一致性。">
              <span className="setting-label">生成后视觉复核</span>
            </Tooltip>
            <Switch checked={visualReview} onChange={(checked) => void toggleVisualReview(checked)} />
          </div>
          <div className="setting-field">
            <Tooltip title="开启后提示词校验会额外调用本地模型检查规则引擎难以发现的隐性语义冲突（默认关闭，会增加校验耗时）。">
              <span className="setting-label">提示词 AI 语义校验</span>
            </Tooltip>
            <Switch checked={semanticCheck} onChange={(checked) => void toggleSemanticCheck(checked)} />
          </div>
        </div>
      </div>

      <WebToolsSettings />

      <div className="panel-box">
        <h3 className="settings-section-title">自动关机</h3>
        <div className="settings-grid">
          <div className="setting-field">
            <Tooltip title="开启后，任意统一任务正常完成且没有新任务开始时，按设定秒数倒计时并自动关机；错误、停止和中断不触发，可随时取消。">
              <span className="setting-label">任务完成后自动关机</span>
            </Tooltip>
            <Switch
              className={autoShutdownStore.enabled ? 'auto-shutdown-switch danger-switch' : 'auto-shutdown-switch'}
              checked={autoShutdownStore.enabled}
              onChange={(checked) => void toggleAutoShutdown(checked)}
            />
          </div>
          <div className="setting-field">
            <Tooltip title="任务正常完成后等待的秒数，期间可取消关机；若开启新任务会自动取消本次关机。">
              <span className="setting-label">关机前等待（秒）</span>
            </Tooltip>
            <InputNumber
              min={settingsConfig.auto_shutdown_delay_min}
              max={settingsConfig.auto_shutdown_delay_max}
              value={autoShutdownStore.delay_seconds}
              onChange={(value) => void changeAutoShutdownDelay(value)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="setting-field">
            <span className="setting-label">当前状态</span>
            <Space wrap>
              <Tag color={autoShutdownStore.phase === 'pending' ? 'red' : autoShutdownStore.phase === 'error' ? 'red' : 'default'}>
                {autoShutdownText}
              </Tag>
              {autoShutdownStore.enabled && autoShutdownStore.phase === 'pending' ? (
                <Button danger size="small" onClick={() => void handleCancelAutoShutdown()}>
                  取消关机
                </Button>
              ) : null}
            </Space>
          </div>
        </div>
      </div>

      <div className="panel-box">
        <h3 className="settings-section-title">数据库备份</h3>
        <div className="settings-grid">
          <div className="setting-field">
            <Tooltip
              title={`使用 SQLite 在线备份机制复制当前数据库，保留最近 ${backupConfig.keep_count} 份。`}
            >
              <span className="setting-label">立即备份</span>
            </Tooltip>
            <Space wrap>
              <Button icon={<DatabaseOutlined />} loading={backingUp} onClick={() => void handleBackup()}>
                创建备份
              </Button>
            </Space>
          </div>
          <div className="setting-field">
            <span className="setting-label">最近备份</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
              {backups.length === 0 ? <span style={{ color: '#9ca3af' }}>暂无备份</span> : null}
              {backups.slice(0, 5).map((item) => (
                <Tag key={item.name} style={{ overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>
                  {item.name}（{item.size_mb}MB）
                </Tag>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="panel-box">
        <h3 className="settings-section-title">数据保留策略</h3>
        <div className="settings-grid">
          <div className="setting-field">
            <Tooltip title="只清理数据库中的历史记录，不删除图片文件；0 表示永久保留。">
              <span className="setting-label">保留天数</span>
            </Tooltip>
            <InputNumber
              min={settingsConfig.data_retention_min}
              max={settingsConfig.data_retention_max}
              value={retentionDays}
              onChange={(value) => setRetentionDays(value ?? settingsConfig.data_retention_default)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="setting-field">
            <span className="setting-label">操作</span>
            <Space wrap>
              <Button icon={<SaveOutlined />} loading={retentionSaving} onClick={() => void saveRetention()}>
                保存策略
              </Button>
              <Popconfirm
                title="确认立即清理？"
                description="将删除保留天数之前的所有数据库记录，不可恢复。"
                disabled={retentionDays <= 0}
                onConfirm={() => void handleCleanup()}
              >
                <Button danger loading={cleaning} disabled={retentionDays <= 0}>
                  立即清理
                </Button>
              </Popconfirm>
            </Space>
          </div>
        </div>
      </div>
    </div>
  );
}
