// 情感陪伴：人设切换、会话、聊天、记忆与设置
import { CloseOutlined, DeleteOutlined, PictureOutlined, PlusOutlined, ReloadOutlined, SendOutlined, SettingOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { Button, Input, List, message, Modal, Popconfirm, Radio, Select, Space, Switch, Tag, Tooltip, Upload } from 'antd';
import { useEffect, useState } from 'react';
import {
  companionStore,
  createCompanionSession,
  deleteCompanionMemory,
  deleteCompanionSession,
  generateCompanionPersona,
  loadCompanionData,
  openCompanionSession,
  saveCompanionSettings,
  sendCompanionMessage,
  summarizeCompanion,
  switchCompanionPersona,
} from '../stores/companion';
import { busyBlockMessage, showBusyWarning } from '../stores/busy';
import { api, type CompanionPersona } from '../api';

const IDENTITY_OPTIONS = [
  '恋人', '男朋友 / 女朋友', '老公 / 老婆', '爸爸 / 妈妈', '青梅竹马',
  '哥哥 / 妹妹', '姐姐 / 弟弟', '闺蜜 / 挚友', '知心好友', '守护者 / 保镖',
  '老师 / 前辈', '室友', '搭档 / 队友', '神秘旅伴', '虚拟主播 / 助手',
];
const GENDER_OPTIONS = ['女', '男', '中性 / 无性别', '不设置'];

export default function CompanionPanel() {
  const { personas, currentPersonaId, sessions, currentSessionId, messages, memories, settings, streaming, status } = companionStore;
  const [input, setInput] = useState('');
  const [personaModalOpen, setPersonaModalOpen] = useState(false);
  const [editingPersona, setEditingPersona] = useState<CompanionPersona | null>(null);
  const [form, setForm] = useState({
    name: '',
    source: '',
    relationship: '恋人',
    gender: '',
    personality: '',
    tone: '',
    appearance: '',
    catchphrases: '',
  });
  const [generating, setGenerating] = useState(false);
  const [generateText, setGenerateText] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [cloudTesting, setCloudTesting] = useState(false);
  const [pendingImage, setPendingImage] = useState('');

  useEffect(() => {
    void loadCompanionData().catch(() => undefined);
  }, []);

  const openCreate = () => {
    setEditingPersona(null);
    setForm({ name: '', source: '', relationship: '恋人', gender: '', personality: '', tone: '', appearance: '', catchphrases: '' });
    setGenerateText('');
    setPersonaModalOpen(true);
  };

  const openEdit = (persona: CompanionPersona) => {
    setEditingPersona(persona);
    setForm({
      name: persona.name,
      source: persona.source,
      relationship: persona.relationship,
      gender: persona.gender || '',
      personality: persona.personality,
      tone: persona.tone,
      appearance: persona.appearance || '',
      catchphrases: persona.catchphrases,
    });
    setPersonaModalOpen(true);
  };

  const handleGenerate = async () => {
    if (!generateText.trim()) {
      message.warning('请输入角色描述');
      return;
    }
    setGenerating(true);
    try {
      const item = await generateCompanionPersona(generateText);
      if (item.notice) message.info(String(item.notice));
      setForm({
        name: String(item.name || ''),
        source: String(item.source || ''),
        relationship: String(item.relationship || '恋人'),
        gender: String(item.gender || ''),
        personality: String(item.personality || ''),
        tone: String(item.tone || ''),
        appearance: String(item.appearance || ''),
        catchphrases: Array.isArray(item.catchphrases) ? item.catchphrases.join('，') : String(item.catchphrases || ''),
      });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleSavePersona = async () => {
    if (!form.name.trim()) {
      message.warning('请填写人设名称');
      return;
    }
    try {
      if (editingPersona) {
        await api.put(`/companion/personas/${editingPersona.id}`, form);
      } else {
        await api.post('/companion/personas', form);
      }
      setPersonaModalOpen(false);
      await loadCompanionData();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '保存失败');
    }
  };

  const handleDeletePersona = async (persona: CompanionPersona) => {
    try {
      await api.delete(`/companion/personas/${persona.id}`);
      await loadCompanionData();
    } catch {
      message.error('删除失败');
    }
  };

  const readImageFile = (file: File) => {
    if (!file.type.startsWith('image/')) {
      message.warning('请选择图片文件');
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      message.error('图片不能超过 15MB');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setPendingImage(String(reader.result || ''));
    reader.onerror = () => message.error('读取图片失败');
    reader.readAsDataURL(file);
  };

  const handleSend = async () => {
    if (!input.trim() && !pendingImage) return;
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    void sendCompanionMessage(input, pendingImage || undefined);
    setInput('');
    setPendingImage('');
  };

  const handleTestCloud = async () => {
    if (!settings) return;
    setCloudTesting(true);
    try {
      const { data } = await api.post<{ ok: boolean; reply?: string; error?: string }>('/companion/test-cloud', {
        base_url: settings.cloud_base_url,
        api_key: settings.cloud_api_key,
        model: settings.cloud_model,
      });
      if (data.ok) message.success(`连接成功：${data.reply}`);
      else message.error(data.error || '连接失败');
    } catch {
      message.error('测试失败');
    } finally {
      setCloudTesting(false);
    }
  };

  return (
    <div className="companion-layout">
      <div className="companion-side panel-box">
        <div className="train-section-title">人设</div>
        <Select
          style={{ width: '100%' }}
          value={currentPersonaId || undefined}
          options={personas.map((item) => ({ label: `${item.name}（${item.relationship}${item.gender ? ` · ${item.gender}` : ''}）`, value: item.id }))}
          onChange={(value) => void switchCompanionPersona(value)}
        />
        <Space style={{ marginTop: 8 }}>
          <Button size="small" icon={<PlusOutlined />} onClick={openCreate}>
            新建
          </Button>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => currentPersonaId && openEdit(personas.find((item) => item.id === currentPersonaId) as CompanionPersona)}
            disabled={!currentPersonaId}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除该人设？"
            onConfirm={() => currentPersonaId && personas.find((item) => item.id === currentPersonaId) && handleDeletePersona(personas.find((item) => item.id === currentPersonaId) as CompanionPersona)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} disabled={!currentPersonaId}>
              删除
            </Button>
          </Popconfirm>
        </Space>

        <div className="train-section-title" style={{ marginTop: 16 }}>
          会话
        </div>
        <List
          size="small"
          dataSource={sessions}
          renderItem={(item) => (
            <List.Item
              onClick={() => void openCompanionSession(item.id)}
              style={{ cursor: 'pointer' }}
            >
              <span style={{ color: currentSessionId === item.id ? '#2563eb' : undefined }}>{item.title}</span>
              <Button
                size="small"
                type="link"
                danger
                onClick={(e) => {
                  e.stopPropagation();
                  void deleteCompanionSession(item.id);
                }}
              >
                删除
              </Button>
            </List.Item>
          )}
        />
        <Button size="small" block icon={<PlusOutlined />} onClick={() => void createCompanionSession()}>
          新会话
        </Button>

        <Space style={{ marginTop: 16 }}>
          <Button size="small" icon={<ThunderboltOutlined />} onClick={() => setMemoryOpen(true)}>
            记忆
          </Button>
          <Button size="small" icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>
            设置
          </Button>
        </Space>
      </div>

      <div className="companion-main panel-box">
        <div className="companion-messages">
          {messages.length === 0 ? (
            <div className="companion-empty">选择一个会话开始聊天吧</div>
          ) : (
            messages.map((item, index) => (
              <div key={`${item.id}-${index}`} className={item.role === 'user' ? 'bubble user' : 'bubble agent'}>
                {item.image_url ? <img className="companion-message-image" src={item.image_url} alt="聊天图片" /> : null}
                {item.content ? <div className="companion-message-text">{item.content}</div> : null}
              </div>
            ))
          )}
          {streaming ? <div className="bubble agent">正在输入…</div> : null}
          {status ? <div className="companion-status">{status}</div> : null}
        </div>
        <div className="companion-composer">
          <div className="companion-composer-left">
            <Upload
              accept="image/*"
              showUploadList={false}
              beforeUpload={() => false}
              onChange={(info) => {
                const file = info.file.originFileObj;
                if (file) readImageFile(file);
              }}
            >
              <Tooltip title="上传图片让角色看看">
                <Button icon={<PictureOutlined />} disabled={streaming} />
              </Tooltip>
            </Upload>
            {pendingImage ? (
              <div className="companion-pending-image">
                <img src={pendingImage} alt="待发送图片" />
                <Button size="small" type="text" icon={<CloseOutlined />} onClick={() => setPendingImage('')} />
              </div>
            ) : null}
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={handleSend}
              placeholder={pendingImage ? '给这张图补充一句话（可留空）…' : '说点什么…'}
              disabled={streaming}
            />
          </div>
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={streaming} disabled={!input.trim() && !pendingImage}>
            发送
          </Button>
        </div>
      </div>

      <Modal
        title={editingPersona ? '编辑人设' : '新建人设'}
        open={personaModalOpen}
        onOk={() => void handleSavePersona()}
        onCancel={() => setPersonaModalOpen(false)}
        width={560}
      >
        <div className="companion-persona-form">
          <div className="form-row">
            <span className="form-label">AI 生成</span>
            <Input
              className="form-control"
              value={generateText}
              onChange={(e) => setGenerateText(e.target.value)}
              placeholder="描述角色，例如：温柔猫娘恋人"
            />
            <Button loading={generating} onClick={() => void handleGenerate()}>
              生成
            </Button>
          </div>
          <div className="form-row split">
            <div className="form-field">
              <span className="form-label">名称</span>
              <Input className="form-control" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="form-field">
              <span className="form-label">出处</span>
              <Input className="form-control" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
            </div>
          </div>
          <div className="form-row split">
            <div className="form-field">
              <span className="form-label">身份</span>
              <Select
                className="form-control"
                value={form.relationship}
                options={IDENTITY_OPTIONS.map((item) => ({ label: item, value: item }))}
                onChange={(value) => setForm({ ...form, relationship: value })}
              />
            </div>
            <div className="form-field">
              <span className="form-label">性别</span>
              <Select
                className="form-control"
                value={form.gender || undefined}
                placeholder="不设置"
                options={GENDER_OPTIONS.map((item) => ({
                  label: item === '不设置' ? '不设置（不主动假设）' : item,
                  value: item === '不设置' ? '' : item,
                }))}
                onChange={(value) => setForm({ ...form, gender: value || '' })}
              />
            </div>
          </div>
          <div className="form-field">
            <span className="form-label">性格</span>
            <Input className="form-control" value={form.personality} onChange={(e) => setForm({ ...form, personality: e.target.value })} />
          </div>
          <div className="form-field">
            <span className="form-label">语气</span>
            <Input className="form-control" value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })} />
          </div>
          <div className="form-field">
            <span className="form-label">外观特征</span>
            <Input.TextArea
              className="form-control"
              rows={2}
              value={form.appearance}
              onChange={(e) => setForm({ ...form, appearance: e.target.value })}
              placeholder="用于角色识别图片是否本人，例如发色、瞳色、体型；服装不算"
            />
          </div>
          <div className="form-field">
            <span className="form-label">代表台词</span>
            <Input.TextArea className="form-control" rows={2} value={form.catchphrases} onChange={(e) => setForm({ ...form, catchphrases: e.target.value })} />
          </div>
        </div>
      </Modal>

      <Modal title="情感陪伴设置" open={settingsOpen} onCancel={() => setSettingsOpen(false)} footer={null} width={480}>
        {settings ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Tooltip title="跟随顶部全局开关；开启后拦截 NSFW 关键词，未成年相关内容始终拦截。">
                <span>内容限制</span>
              </Tooltip>
              <Tag color={settings.content_restriction === '1' ? 'green' : 'default'}>
                {settings.content_restriction === '1' ? '已开启（跟随全局）' : '已关闭（跟随全局）'}
              </Tag>
            </Space>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Tooltip title="默认开启；模型不做医疗/心理诊断，只做陪伴式共情。">
                <span>医疗诊断禁用</span>
              </Tooltip>
              <Switch checked={settings.medical_disabled === '1'} onChange={(checked) => void saveCompanionSettings({ medical_disabled: checked ? '1' : '0' })} />
            </Space>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Tooltip title="长期高频聊天时，模型会温和提醒注意现实社交。">
                <span>情感依赖提醒</span>
              </Tooltip>
              <Switch checked={settings.dependency_reminder === '1'} onChange={(checked) => void saveCompanionSettings({ dependency_reminder: checked ? '1' : '0' })} />
            </Space>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Tooltip title="识别到未成年人时调整对话边界，不提供不当内容。">
                <span>未成年人保护</span>
              </Tooltip>
              <Switch checked={settings.minor_protection === '1'} onChange={(checked) => void saveCompanionSettings({ minor_protection: checked ? '1' : '0' })} />
            </Space>
            {settings.content_restriction === '1' ? (
              <>
                <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                  <Tooltip title="内容限制开启时可选择本地模型或云端模型；云端会把消息发送到外部服务。">
                    <span>对话模型</span>
                  </Tooltip>
                  <Radio.Group
                    value={settings.model_provider || 'local'}
                    onChange={(e) => void saveCompanionSettings({ model_provider: e.target.value })}
                    options={[
                      { label: '本地模型', value: 'local' },
                      { label: '云端模型', value: 'cloud' },
                    ]}
                    optionType="button"
                  />
                </Space>
                {settings.model_provider === 'cloud' ? (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Space>
                      <Tooltip title="OpenAI 兼容接口地址，例如 https://api.openai.com/v1。">
                        <span>Base URL</span>
                      </Tooltip>
                      <Input
                        value={settings.cloud_base_url}
                        style={{ width: 300 }}
                        placeholder="https://api.openai.com/v1"
                        onChange={(e) => void saveCompanionSettings({ cloud_base_url: e.target.value })}
                      />
                    </Space>
                    <Space>
                      <Tooltip title="云端 API Key，本地明文保存，注意保护。">
                        <span>API Key</span>
                      </Tooltip>
                      <Input.Password
                        value={settings.cloud_api_key}
                        style={{ width: 300 }}
                        onChange={(e) => void saveCompanionSettings({ cloud_api_key: e.target.value })}
                      />
                    </Space>
                    <Space>
                      <Tooltip title="云端模型名称，例如 gpt-4o-mini。">
                        <span>模型</span>
                      </Tooltip>
                      <Input
                        value={settings.cloud_model}
                        style={{ width: 300 }}
                        placeholder="gpt-4o-mini"
                        onChange={(e) => void saveCompanionSettings({ cloud_model: e.target.value })}
                      />
                    </Space>
                    <Space>
                      <Button size="small" loading={cloudTesting} onClick={() => void handleTestCloud()}>
                        测试连接
                      </Button>
                      <Tag>云端对话会发送到外部服务；内容限制关闭时强制使用本地模型。</Tag>
                    </Space>
                  </Space>
                ) : null}
              </>
            ) : (
              <Tag>内容限制关闭时仅支持本地模型（云端不支持成人内容）。</Tag>
            )}
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Tooltip title="开启后，涉及实时/新闻类问题会触发联网搜索；用户消息可能发送给搜索服务。">
                <span>联网搜索</span>
              </Tooltip>
              <Switch checked={settings.online_search_enabled === '1'} onChange={(checked) => void saveCompanionSettings({ online_search_enabled: checked ? '1' : '0' })} />
            </Space>
            <Space>
              <Tooltip title="搜索 Provider、API Key、缓存和限流在「全局设置 → 联网搜索」中统一配置。">
                <span>搜索配置</span>
              </Tooltip>
              <Tag color="blue">全局设置</Tag>
            </Space>
            <Tag>联网搜索开启后，用户消息可能发送给搜索服务，请谨慎使用。</Tag>
          </Space>
        ) : null}
      </Modal>

      <Modal title="长期记忆" open={memoryOpen} onCancel={() => setMemoryOpen(false)} footer={null} width={560}>
        <Button size="small" icon={<ThunderboltOutlined />} onClick={() => void summarizeCompanion()}>
          生成记忆总结
        </Button>
        <List
          style={{ marginTop: 10 }}
          size="small"
          dataSource={memories}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button key="del" size="small" type="link" danger onClick={() => void deleteCompanionMemory(item.id)}>
                  删除
                </Button>,
              ]}
            >
              {item.content}
            </List.Item>
          )}
        />
      </Modal>
    </div>
  );
}
