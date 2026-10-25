import { Alert, Button, Form, Input, Modal, Space, Tabs, Tag, message } from 'antd';
import { useEffect, useState } from 'react';
import {
  deleteProviderSettings,
  listProviderSettings,
  testProviderSettings,
  updateProviderSettings,
  type ProviderSettingsView,
} from '../stores/gameAssistant';

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

type Draft = { base_url: string; model: string; api_key: string };

const providerHelp: Record<ProviderSettingsView['provider_id'], string> = {
  deepseek: '使用 DeepSeek 官方 API。Key 只发送到本机后端，并保存在 Windows DPAPI 加密文件中。',
  openai_compatible: '适用于 OpenAI 兼容服务。Key 可选；仅当服务要求鉴权时填写。',
  ollama: '本地 Ollama 不保存 API Key。填写服务和模型名称后可直接测试连接。',
};

export default function ProviderSettingsModal({ open, onClose, onChanged }: Props) {
  const [messageApi, contextHolder] = message.useMessage();
  const [settings, setSettings] = useState<ProviderSettingsView[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [active, setActive] = useState<ProviderSettingsView['provider_id']>('deepseek');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const items = await listProviderSettings();
      setSettings(items);
      setDrafts(
        Object.fromEntries(
          items.map((item) => [
            item.provider_id,
            { base_url: item.base_url, model: item.model, api_key: '' },
          ]),
        ),
      );
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '模型设置读取失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void load();
  }, [open]);

  const current = settings.find((item) => item.provider_id === active);
  const draft = drafts[active] || { base_url: '', model: '', api_key: '' };

  const patchDraft = (patch: Partial<Draft>) => {
    setDrafts((previous) => ({ ...previous, [active]: { ...draft, ...patch } }));
  };

  const save = async () => {
    if (!current) return;
    setBusy('save');
    try {
      const updated = await updateProviderSettings(active, {
        base_url: draft.base_url,
        model: draft.model,
        api_key: draft.api_key || undefined,
      });
      setSettings((items) => items.map((item) => (item.provider_id === active ? updated : item)));
      setDrafts((previous) => ({ ...previous, [active]: { ...draft, api_key: '' } }));
      messageApi.success(`${updated.label} 配置已保存`);
      onChanged();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setBusy('');
    }
  };

  const test = async () => {
    setBusy('test');
    try {
      const updated = await updateProviderSettings(active, {
        base_url: draft.base_url,
        model: draft.model,
        api_key: draft.api_key || undefined,
      });
      setSettings((items) => items.map((item) => (item.provider_id === active ? updated : item)));
      setDrafts((previous) => ({ ...previous, [active]: { ...draft, api_key: '' } }));
      const result = await testProviderSettings(active);
      if (result.ok) messageApi.success(result.message);
      else messageApi.warning(result.message);
      await load();
      onChanged();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '连接测试失败');
    } finally {
      setBusy('');
    }
  };

  const clearKey = async () => {
    setBusy('clear');
    try {
      const updated = await deleteProviderSettings(active);
      setSettings((items) => items.map((item) => (item.provider_id === active ? updated : item)));
      messageApi.success('已清除保存的 API Key');
      onChanged();
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '清除密钥失败');
    } finally {
      setBusy('');
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      title="游戏助手模型设置"
      width={760}
      destroyOnHidden={false}
    >
      {contextHolder}
      <Tabs
        activeKey={active}
        onChange={(key) => setActive(key as ProviderSettingsView['provider_id'])}
        items={settings.map((item) => ({
          key: item.provider_id,
          label: item.label,
          children: (
            <div className="ga-provider-settings">
              <Alert type="info" showIcon message={providerHelp[item.provider_id]} />
              <Space wrap>
                <Tag color={item.available ? 'green' : 'default'}>{item.available ? '已配置' : '未配置'}</Tag>
                {item.api_key_configured && (
                  <Tag color="blue">
                    Key: {item.api_key_source === 'environment' ? '环境变量' : '已安全保存'}
                  </Tag>
                )}
                {item.last_test_message && (
                  <Tag color={item.last_test_ok ? 'green' : 'red'}>{item.last_test_message}</Tag>
                )}
              </Space>
              <Form layout="vertical">
                <Form.Item label="Base URL">
                  <Input
                    value={draft.base_url}
                    onChange={(event) => patchDraft({ base_url: event.target.value })}
                    placeholder="https://api.example.com/v1"
                  />
                </Form.Item>
                <Form.Item label="模型名称">
                  <Input
                    value={draft.model}
                    onChange={(event) => patchDraft({ model: event.target.value })}
                    placeholder="deepseek-chat / qwen3:8b"
                  />
                </Form.Item>
                {item.provider_id !== 'ollama' && (
                  <Form.Item label="API Key">
                    <Input.Password
                      value={draft.api_key}
                      onChange={(event) => patchDraft({ api_key: event.target.value })}
                      placeholder={item.api_key_configured ? '已配置；留空表示不修改' : '输入后只会发送到本机后端'}
                      autoComplete="new-password"
                    />
                  </Form.Item>
                )}
              </Form>
              <Space wrap>
                <Button type="primary" loading={busy === 'save'} onClick={() => void save()}>
                  保存
                </Button>
                <Button loading={busy === 'test'} onClick={() => void test()}>
                  保存并测试连接
                </Button>
                {item.provider_id !== 'ollama' && item.api_key_configured && item.api_key_source === 'saved' && (
                  <Button danger loading={busy === 'clear'} onClick={() => void clearKey()}>
                    清除保存的 Key
                  </Button>
                )}
                <Button onClick={() => void load()} loading={loading}>
                  刷新
                </Button>
              </Space>
            </div>
          ),
        }))}
      />
    </Modal>
  );
}
