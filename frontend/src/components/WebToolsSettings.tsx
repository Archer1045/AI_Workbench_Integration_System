import { Button, Input, InputNumber, message, Select, Space, Switch, Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';
import { api } from '../api';

interface WebToolsConfig {
  enabled: boolean;
  provider: 'deepseek' | 'tavily' | 'serper' | 'duckduckgo';
  base_url: string;
  default_count: number;
  default_need_content: boolean;
  timeout_seconds: number;
  cache_ttl_seconds: number;
  max_results: number;
  max_fetch_per_query: number;
  max_qps: number;
}

interface WebToolsView {
  settings: WebToolsConfig;
  api_key_configured: boolean;
  api_key_source: 'saved' | 'environment' | 'none';
  last_test_at?: string | null;
  last_test_ok?: boolean | null;
  last_test_message?: string;
}

const PROVIDERS = [
  { label: 'DeepSeek Search & Fetch', value: 'deepseek' },
  { label: 'Tavily', value: 'tavily' },
  { label: 'Serper', value: 'serper' },
  { label: 'DuckDuckGo', value: 'duckduckgo' },
];

export default function WebToolsSettings() {
  const [draft, setDraft] = useState<WebToolsConfig | null>(null);
  const [view, setView] = useState<WebToolsView | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [clearing, setClearing] = useState(false);

  const load = async () => {
    try {
      const { data } = await api.get<WebToolsView>('/settings/web-tools');
      setView(data);
      setDraft(data.settings);
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '加载联网搜索配置失败');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const patch = (value: Partial<WebToolsConfig>) => {
    setDraft((current) => (current ? { ...current, ...value } : current));
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const { data } = await api.put<WebToolsConfig>('/settings/web-tools', draft);
      setDraft(data);
      await load();
      message.success('联网搜索配置已保存');
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const saveKey = async (clear = false) => {
    if (!draft) return;
    try {
      await api.put('/settings/web-tools/api-key', {
        provider: draft.provider,
        api_key: apiKey,
        clear,
      });
      setApiKey('');
      await load();
      message.success(clear ? 'API Key 已清除' : 'API Key 已保存');
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'API Key 保存失败');
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const { data } = await api.post<{ ok: boolean; message: string }>('/settings/web-tools/test');
      await load();
      if (data.ok) message.success(data.message);
      else message.error(data.message);
    } catch (e) {
      message.error((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '测试失败');
    } finally {
      setTesting(false);
    }
  };

  const clearCache = async () => {
    setClearing(true);
    try {
      const { data } = await api.post<{ deleted: number }>('/settings/web-tools/cache/clear');
      message.success(`已清空 ${data.deleted} 个搜索缓存`);
    } catch {
      message.error('清空缓存失败');
    } finally {
      setClearing(false);
    }
  };

  if (!draft || !view) {
    return (
      <div className="panel-box">
        <h3 className="settings-section-title">联网搜索</h3>
        <Tag color="blue">加载中...</Tag>
      </div>
    );
  }

  return (
    <div className="panel-box">
      <h3 className="settings-section-title">联网搜索</h3>
      <div className="settings-grid">
        <div className="setting-field">
          <Tooltip title="关闭后，所有应用的联网搜索请求都会被拒绝。">
            <span className="setting-label">启用 Web Tools</span>
          </Tooltip>
          <Switch checked={draft.enabled} onChange={(enabled) => patch({ enabled })} />
        </div>
        <div className="setting-field">
          <Tooltip title="Search & Fetch 的搜索服务提供方。">
            <span className="setting-label">Provider</span>
          </Tooltip>
          <Select
            value={draft.provider}
            options={PROVIDERS}
            style={{ width: '100%' }}
            onChange={(provider) => patch({ provider })}
          />
        </div>
        <div className="setting-field">
          <Tooltip title="DeepSeek 使用 https://api.deepseek.com，路径由后端固定。">
            <span className="setting-label">Base URL</span>
          </Tooltip>
          <Input value={draft.base_url} onChange={(e) => patch({ base_url: e.target.value })} />
        </div>
        <div className="setting-field">
          <Tooltip title="默认返回条数，1–50；不会改变单次请求价格。">
            <span className="setting-label">默认结果数</span>
          </Tooltip>
          <InputNumber
            min={1}
            max={50}
            value={draft.default_count}
            onChange={(value) => patch({ default_count: value ?? 5 })}
            style={{ width: '100%' }}
          />
        </div>
        <div className="setting-field">
          <Tooltip title="默认只读摘要；需要正文时由应用单独发起 Fetch。">
            <span className="setting-label">默认抓取正文</span>
          </Tooltip>
          <Switch
            checked={draft.default_need_content}
            onChange={(default_need_content) => patch({ default_need_content })}
          />
        </div>
        <div className="setting-field">
          <Tooltip title="搜索和抓取请求的超时时间。">
            <span className="setting-label">超时（秒）</span>
          </Tooltip>
          <InputNumber
            min={1}
            max={120}
            value={draft.timeout_seconds}
            onChange={(value) => patch({ timeout_seconds: value ?? 20 })}
            style={{ width: '100%' }}
          />
        </div>
        <div className="setting-field">
          <Tooltip title="相同搜索在缓存期内不重复请求。0 表示禁用缓存。">
            <span className="setting-label">缓存（秒）</span>
          </Tooltip>
          <InputNumber
            min={0}
            max={604800}
            value={draft.cache_ttl_seconds}
            onChange={(value) => patch({ cache_ttl_seconds: value ?? 86400 })}
            style={{ width: '100%' }}
          />
        </div>
        <div className="setting-field">
          <Tooltip title="单次搜索最多允许返回的结果数。">
            <span className="setting-label">最大结果数</span>
          </Tooltip>
          <InputNumber
            min={1}
            max={50}
            value={draft.max_results}
            onChange={(value) => patch({ max_results: value ?? 20 })}
            style={{ width: '100%' }}
          />
        </div>
        <div className="setting-field">
          <Tooltip title="一次查询最多抓取的网页数量。">
            <span className="setting-label">每次最多 Fetch</span>
          </Tooltip>
          <InputNumber
            min={0}
            max={10}
            value={draft.max_fetch_per_query}
            onChange={(value) => patch({ max_fetch_per_query: value ?? 2 })}
            style={{ width: '100%' }}
          />
        </div>
        <div className="setting-field">
          <Tooltip title="DeepSeek 官方账号级限制为 5 QPS；第一次先按单进程限流。">
            <span className="setting-label">QPS</span>
          </Tooltip>
          <InputNumber
            min={0.1}
            max={5}
            step={0.1}
            value={draft.max_qps}
            onChange={(value) => patch({ max_qps: value ?? 5 })}
            style={{ width: '100%' }}
          />
        </div>
      </div>

      <Space wrap style={{ marginTop: 10 }}>
        <Tag color={view.api_key_configured ? 'green' : 'red'}>
          {view.api_key_configured ? 'API Key 已配置' : 'API Key 未配置'}
        </Tag>
        <Tag>{view.api_key_source === 'environment' ? '来自环境变量' : view.api_key_source === 'saved' ? '来自本地加密存储' : '无 Key'}</Tag>
        {view.last_test_at ? (
          <Tag color={view.last_test_ok ? 'green' : 'red'}>
            {view.last_test_ok ? '上次测试成功' : '上次测试失败'}：{view.last_test_at}
          </Tag>
        ) : null}
      </Space>
      {view.last_test_message ? <div className="settings-hint">{view.last_test_message}</div> : null}

      <Space wrap style={{ marginTop: 12 }}>
        <Input.Password
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={`${draft.provider} API Key（留空不修改）`}
          style={{ width: 320, maxWidth: '100%' }}
        />
        <Button onClick={() => void saveKey(false)} disabled={!apiKey.trim()}>保存 Key</Button>
        <Button danger onClick={() => void saveKey(true)}>清除 Key</Button>
        <Button onClick={() => void save()} loading={saving}>保存配置</Button>
        <Button onClick={() => void test()} loading={testing}>测试连接</Button>
        <Button onClick={() => void clearCache()} loading={clearing}>清空缓存</Button>
      </Space>
      <div className="settings-hint" style={{ marginTop: 10 }}>
        联网搜索会把查询词发送给外部搜索服务。Search/Fetch 按成功请求计费；应用关闭联网开关后不会发起请求。
      </div>
    </div>
  );
}
