// 提示词集管理：抽屉列表 + 新建/编辑/导入/复制/插入/删除
import { BranchesOutlined, CheckCircleOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, EyeOutlined, ImportOutlined, InsertRowAboveOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Button,
  DatePicker,
  Drawer,
  Input,
  message,
  Modal,
  Popconfirm,
  Popover,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';
import {
  api,
  type PromptDocumentResolveResult,
  type PromptDocumentV1,
  type PresetCompositionResult,
  type PromptSet,
  type PromptSetList,
  type PromptValidation,
} from '../api';
import { parsePresetComposition } from '../presetComposition';
import { normalizePromptDocument } from '../promptDocument';
import { settingsStore } from '../stores/settings';
import {
  drawStore,
  setGroupMode,
  updateGroupDocument,
  updateGroupPrompt,
} from '../stores/draw';
import { getRuntimeConfig } from '../stores/runtimeConfig';

const TYPE_OPTIONS = ['角色', '服装', '场景', '画风', '动作', '模板', '组合', '其他'];

function parsePromptDocumentRecord(raw?: string): PromptDocumentV1 | null {
  const text = String(raw || '').trim();
  if (!text || text === '{}') return null;
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const documentKeys = ['version', 'mode', 'global', 'characters', 'interaction', 'custom', 'negative', 'raw_override'];
    if (!documentKeys.some((key) => key in parsed)) return null;
    return normalizePromptDocument(parsed);
  } catch {
    return null;
  }
}

function describePromptDocument(document: PromptDocumentV1): string {
  const characterCount = document.characters.filter((character) => character.enabled !== false).length;
  return `${document.mode === 'structured' ? '结构化' : '旧文档'} · ${characterCount || 1} 个角色`;
}

export default function PromptSetsDrawer({
  open,
  onClose,
  activeGroupId,
}: {
  open: boolean;
  onClose: () => void;
  activeGroupId?: string;
}) {
  const { restrictionEnabled } = settingsStore;
  const groups = drawStore.groups;
  const queryConfig = getRuntimeConfig().query;
  const [items, setItems] = useState<PromptSet[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(queryConfig.prompt_set_page_size_default);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PromptSet | null>(null);
  const [detailItem, setDetailItem] = useState<PromptSet | null>(null);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [formType, setFormType] = useState('角色');
  const [content, setContent] = useState('');
  const [translation, setTranslation] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [compositionJson, setCompositionJson] = useState('{}');
  const [formDocument, setFormDocument] = useState<PromptDocumentV1 | null>(null);
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [translating, setTranslating] = useState(false);

  const [importOpen, setImportOpen] = useState(false);
  const [importLines, setImportLines] = useState<string[]>([]);
  const [importRaw, setImportRaw] = useState('');
  const [importFileType, setImportFileType] = useState('');
  const [importing, setImporting] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<number[]>([]);
  const [batchTypeOpen, setBatchTypeOpen] = useState(false);
  const [batchType, setBatchType] = useState('角色');
  const [batchSaving, setBatchSaving] = useState(false);
  const [checkItem, setCheckItem] = useState<PromptSet | null>(null);
  const [checkResult, setCheckResult] = useState<PromptValidation | null>(null);
  const [checkTranslations, setCheckTranslations] = useState<Record<string, string>>({});
  const [checking, setChecking] = useState(false);

  const currentGroup =
    groups.find((group) => group.id === activeGroupId) || groups[0];

  const parseItemDocument = (item: PromptSet): PromptDocumentV1 | null =>
    parsePromptDocumentRecord(item.prompt_document_json);

  const loadList = () => {
    setLoading(true);
    api
      .get<PromptSetList>('/prompt-sets', {
        params: {
          keyword: keyword || undefined,
          type: typeFilter || undefined,
          date_from: dateRange?.[0] || undefined,
          date_to: dateRange?.[1] || undefined,
          page,
          page_size: pageSize,
        },
      })
      .then((res) => {
        setItems(res.data.items || []);
        setTotal(res.data.total || 0);
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open) loadList();
  }, [open, page, pageSize, keyword, typeFilter, dateRange]);

  const openCreate = () => {
    setEditing(null);
    setName('');
    setFormType('角色');
    setContent('');
    setTranslation('');
    setDescription('');
    setTags('');
    setCompositionJson('{}');
    setFormDocument(null);
    setFormOpen(true);
  };

  const openEdit = (item: PromptSet) => {
    setEditing(item);
    setName(item.name);
    setFormType(item.type);
    setContent(item.content);
    setTranslation(item.translation || '');
    setDescription(item.description || '');
    setTags(item.tags || '');
    setCompositionJson(item.composition_json || '{}');
    setFormDocument(parsePromptDocumentRecord(item.prompt_document_json));
    setFormOpen(true);
  };

  const attachCurrentStructuredDocument = () => {
    if (!currentGroup || currentGroup.mode !== 'structured' || !currentGroup.prompt_document) {
      message.warning('当前组不是结构化模式');
      return;
    }
    const document = normalizePromptDocument(currentGroup.prompt_document);
    setFormDocument(document);
    if (!content.trim() && currentGroup.prompt.trim()) setContent(currentGroup.prompt.trim());
    message.success('已读取当前组结构化文档');
  };

  const handleConvertToStructured = async (item: PromptSet) => {
    setConvertingId(item.id);
    try {
      const { data } = await api.post<{ document: PromptDocumentV1 }>(
        '/prompt-agent/normalize-prompt-document',
        { text: item.content },
      );
      setDetailItem(null);
      openEdit({ ...item, prompt_document_json: JSON.stringify(data.document) });
      message.success('已生成结构化草稿，请确认后保存');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '转换为结构化失败');
    } finally {
      setConvertingId(null);
    }
  };

  const confirmConvertToStructured = (item: PromptSet) => {
    Modal.confirm({
      title: '转换为结构化提示词？',
      content: '转换会保留原文并生成可编辑的结构化草稿，确认后进入编辑窗口。',
      okText: '转换并编辑',
      cancelText: '取消',
      onOk: () => handleConvertToStructured(item),
    });
  };

  const handleAutoTranslate = async () => {
    if (!content.trim()) {
      message.warning('请先填写内容');
      return;
    }
    setTranslating(true);
    try {
      const { data } = await api.post<{ translation: string }>('/translate', { text: content });
      setTranslation(data.translation || '');
    } catch {
      message.error('翻译失败，可手动填写');
    } finally {
      setTranslating(false);
    }
  };

  const handleSave = async () => {
    if (!name.trim() || !content.trim()) {
      message.warning('名称和内容不能为空');
      return;
    }
    try {
      const { data: validation } = await api.post<PromptValidation>('/prompt/validate', { prompt: content.trim() });
      const firstIssue = validation.errors[0] || validation.warnings[0];
      if (firstIssue) {
        message.warning(`提示词检查：${firstIssue.message}`);
      }
    } catch {
      // 校验接口失败不阻止保存
    }
    setSaving(true);
    const payload = {
      name: name.trim(),
      type: formType,
      content: content.trim(),
      translation: translation.trim(),
      description: description.trim(),
      tags: tags.trim(),
      composition_json:
        editing?.type === '组合' && formType === '组合' && content.trim() === editing.content.trim()
          ? compositionJson || '{}'
          : '{}',
      ...(formDocument ? { prompt_document_json: JSON.stringify(formDocument) } : {}),
    };
    try {
      if (editing) {
        await api.put(`/prompt-sets/${editing.id}`, payload);
        message.success('已保存');
      } else {
        await api.post('/prompt-sets', payload);
        message.success('已新增');
      }
      setFormOpen(false);
      setPage(1);
      loadList();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleCheck = async (item: PromptSet) => {
    setCheckItem(item);
    setCheckResult(null);
    setCheckTranslations({});
    setChecking(true);
    try {
      const document = parseItemDocument(item);
      if (document) {
        const { data } = await api.post<PromptDocumentResolveResult>('/prompt-agent/resolve-prompt-document', {
          document,
        });
        setCheckResult({
          errors: data.errors.map((issue) => ({ type: 'error' as const, message: issue })),
          warnings: data.warnings.map((issue) => ({ type: 'warning' as const, message: issue })),
          suggestions:
            data.rating === 'R18'
              ? [{ type: 'suggestion' as const, message: '当前结构化文档包含 R18 内容' }]
              : [],
        });
        return;
      }
      const { data } = await api.post<PromptValidation>('/prompt/validate', { prompt: item.content });
      setCheckResult(data);
      const tags = [
        ...data.errors.flatMap((issue) => issue.tags || []),
        ...data.warnings.flatMap((issue) => issue.tags || []),
      ];
      const unique = Array.from(new Set(tags));
      if (unique.length > 0) {
        const res = await api.post<{ items: { tag: string; translation: string }[] }>('/translate/tags', {
          text: unique.join(', '),
        });
        const map: Record<string, string> = {};
        for (const row of res.data.items || []) map[row.tag] = row.translation;
        setCheckTranslations(map);
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '校验失败');
    } finally {
      setChecking(false);
    }
  };

  const handleRemoveTag = async (tag: string) => {
    if (!checkItem) return;
    const parts = checkItem.content
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean);
    const next = parts.filter((part) => part !== tag).join(', ');
    try {
      await api.put(`/prompt-sets/${checkItem.id}`, {
        name: checkItem.name,
        type: checkItem.type,
        content: next,
        translation: checkItem.translation || '',
        description: checkItem.description || '',
        tags: checkItem.tags || '',
        composition_json: checkItem.type === '组合' ? '{}' : checkItem.composition_json || '{}',
      });
      message.success(`已删除标签 ${tag}`);
      loadList();
      await handleCheck({ ...checkItem, content: next });
    } catch {
      message.error('删除标签失败');
    }
  };

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制');
    } catch {
      message.error('复制失败');
    }
  };

  const handleInsert = async (item: PromptSet) => {
    const target =
      groups.find((group) => group.id === activeGroupId) || groups[0];
    if (!target) {
      message.warning('请先添加提示词组');
      return;
    }
    const document = parseItemDocument(item);
    if (document) {
      updateGroupDocument(target.id, document);
      void api.post(`/prompt-sets/${item.id}/use`).catch(() => undefined);
      message.success('已载入当前组结构化文档');
      return;
    }
    if (item.type === '组合') {
      const composition = parsePresetComposition(item.composition_json);
      if (!composition) {
        message.warning('组合元数据无效，请编辑后重新保存组合');
        return;
      }
      try {
        const { data } = await api.post<PresetCompositionResult>('/prompt-agent/compose-presets', composition);
        if (data.blocked || (restrictionEnabled && data.rating === 'R18')) {
          message.error('内容限制已开启，已阻止 R18 组合');
          return;
        }
        setGroupMode(target.id, 'legacy');
        updateGroupPrompt(target.id, data.prompt);
        message.success('已按最新预设重算并替换当前组');
      } catch (e: unknown) {
        const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        message.error(detail || '组合重算失败');
        return;
      }
      void api.post(`/prompt-sets/${item.id}/use`).catch(() => undefined);
      return;
    }
    if (item.type === '模板') {
      setGroupMode(target.id, 'legacy');
      updateGroupPrompt(target.id, item.content);
      message.success('已替换当前组提示词（模板）');
    } else {
      updateGroupPrompt(target.id, target.prompt ? `${target.prompt}, ${item.content}` : item.content);
      message.success('已插入到当前组');
    }
    void api.post(`/prompt-sets/${item.id}/use`).catch(() => undefined);
  };

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/prompt-sets/${id}`);
      message.success('已删除');
      if (items.length === 1 && page > 1) setPage(page - 1);
      else loadList();
    } catch {
      message.error('删除失败');
    }
  };

  const handleImportFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || '');
      const ext = file.name.toLowerCase().split('.').pop() || '';
      if (ext === 'json' || ext === 'csv') {
        setImportRaw(text);
        setImportFileType(ext);
        setImportLines([]);
        return;
      }
      setImportRaw('');
      setImportFileType('');
      const lines = text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      setImportLines(lines);
    };
    reader.readAsText(file, 'utf-8');
  };

  const handleImportConfirm = async () => {
    if (importRaw) {
      setImporting(true);
      try {
        const { data } = await api.post<{ inserted: number; skipped: number; errors: string[] }>('/prompt-sets/import', {
          format: importFileType,
          content: importRaw,
        });
        message.success(`导入完成：成功 ${data.inserted}，跳过 ${data.skipped}`);
        if (data.errors.length > 0) message.warning(data.errors[0]);
        setImportOpen(false);
        setImportRaw('');
        setImportFileType('');
        setPage(1);
        loadList();
      } catch (e: unknown) {
        const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        message.error(detail || '导入失败');
      } finally {
        setImporting(false);
      }
      return;
    }
    if (importLines.length === 0) {
      message.warning('没有可导入的内容');
      return;
    }
    setImporting(true);
    let ok = 0;
    let failed = 0;
    for (let index = 0; index < importLines.length; index += 1) {
      const line = importLines[index];
      try {
        await api.post('/prompt-sets', {
          name: line.slice(0, 30) || `提示词集 ${index + 1}`,
          type: '其他',
          content: line,
        });
        ok += 1;
      } catch {
        failed += 1;
      }
    }
    message.success(`导入完成：成功 ${ok}，失败 ${failed}`);
    setImportOpen(false);
    setImportLines([]);
    setImportRaw('');
    setImportFileType('');
    setPage(1);
    loadList();
    setImporting(false);
  };

  const handleBatchType = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择记录');
      return;
    }
    setBatchSaving(true);
    try {
      const { data } = await api.put<{ ok: boolean; updated: number }>('/prompt-sets/batch-type', {
        ids: selectedRowKeys,
        type: batchType,
      });
      message.success(`已修改 ${data.updated} 条记录类型`);
      setBatchTypeOpen(false);
      setSelectedRowKeys([]);
      loadList();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '批量修改失败');
    } finally {
      setBatchSaving(false);
    }
  };

  const handleExport = async (format: 'json' | 'csv') => {
    try {
      const res = await api.get('/prompt-sets/export', {
        params: {
          format,
          keyword: keyword || undefined,
          type: typeFilter || undefined,
          date_from: dateRange?.[0] || undefined,
          date_to: dateRange?.[1] || undefined,
        },
        responseType: 'blob',
      });
      const url = URL.createObjectURL(res.data as Blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `prompt-sets.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
      message.success('导出完成');
    } catch {
      message.error('导出失败');
    }
  };

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) return;
    try {
      const { data } = await api.post<{ deleted: number }>('/prompt-sets/batch-delete', { ids: selectedRowKeys });
      message.success(`已删除 ${data.deleted} 条记录`);
      setSelectedRowKeys([]);
      loadList();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '批量删除失败');
    }
  };

  const columns: ColumnsType<PromptSet> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 220,
      minWidth: 160,
      ellipsis: { showTitle: false },
      render: (value: string) => (
        <Tooltip title={value}>
          <span className="prompt-set-name">{value}</span>
        </Tooltip>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 80,
      render: (value: string) =>
        value === '模板' ? (
          <Tooltip title="经过验证、可以直接复用的成熟提示词组合">
            <Tag color="blue">{value}</Tag>
          </Tooltip>
        ) : (
          <Tag>{value}</Tag>
        ),
    },
    {
      title: '内容',
      dataIndex: 'content',
      key: 'content',
      width: 320,
      ellipsis: true,
      render: (value: string) => (
        <Popover title="内容" content={<div className="popover-text">{value}</div>} trigger="hover">
          <span>{value}</span>
        </Popover>
      ),
    },
    {
      title: '结构',
      key: 'prompt_document',
      width: 90,
      render: (_, record) => {
        const document = parseItemDocument(record);
        return document ? (
          <Tooltip title={describePromptDocument(document)}>
            <Tag color="purple">结构化</Tag>
          </Tooltip>
        ) : (
          <Tag>文本</Tag>
        );
      },
    },
    {
      title: '中文翻译',
      dataIndex: 'translation',
      key: 'translation',
      width: 180,
      ellipsis: true,
      render: (value: string) => (
        <Popover title="中文翻译" content={<div className="popover-text">{value || '暂无翻译'}</div>} trigger="hover">
          <span>{value || '暂无翻译'}</span>
        </Popover>
      ),
    },
    { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 150, render: (value: string) => String(value).slice(0, 16) },
    { title: '使用次数', dataIndex: 'use_count', key: 'use_count', width: 80 },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="AI 校验">
            <Button
              size="small"
              icon={<CheckCircleOutlined />}
              loading={checking && checkItem?.id === record.id}
              onClick={() => void handleCheck(record)}
            />
          </Tooltip>
          <Tooltip title="详情">
            <Button size="small" icon={<EyeOutlined />} onClick={() => setDetailItem(record)} />
          </Tooltip>
          <Tooltip title="复制内容">
            <Button size="small" icon={<CopyOutlined />} onClick={() => void handleCopy(record.content)} />
          </Tooltip>
          {parseItemDocument(record) ? (
            <Tooltip title="复制结构化 JSON">
              <Button
                size="small"
                icon={<BranchesOutlined />}
                onClick={() => void handleCopy(record.prompt_document_json || '')}
              />
            </Tooltip>
          ) : (
            <Tooltip title="转换为结构化">
              <Button
                size="small"
                icon={<BranchesOutlined />}
                loading={convertingId === record.id}
                onClick={() => confirmConvertToStructured(record)}
              />
            </Tooltip>
          )}
          <Tooltip title={record.type === '模板' ? '替换当前组' : '插入当前组'}>
            <Button size="small" icon={<InsertRowAboveOutlined />} onClick={() => void handleInsert(record)} />
          </Tooltip>
          <Tooltip title="编辑">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Tooltip title="删除">
            <Popconfirm title={`确认删除「${record.name}」？`} onConfirm={() => void handleDelete(record.id)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Drawer
        title="提示词集"
        width={typeof window !== 'undefined' && window.innerWidth < 768 ? '100vw' : 900}
        open={open}
        onClose={onClose}
        className="prompt-sets-drawer"
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Tooltip title="按名称、内容或标签关键词搜索。">
            <Input.Search
              allowClear
              placeholder="搜索名称/内容/标签"
              style={{ width: 240 }}
              onSearch={(value) => {
                setKeyword(value.trim());
                setPage(1);
              }}
            />
          </Tooltip>
          <Tooltip title="按提示词集类型筛选。">
            <Select
              allowClear
              placeholder="类型"
              style={{ width: 130 }}
              value={typeFilter || undefined}
              options={TYPE_OPTIONS.map((value) => ({ label: value, value }))}
              onChange={(value) => {
                setTypeFilter(value || '');
                setPage(1);
              }}
            />
          </Tooltip>
          <Tooltip title="按创建时间范围筛选。">
            <DatePicker.RangePicker
              onChange={(dates: [Dayjs | null, Dayjs | null] | null) => {
                setDateRange(dates?.[0] && dates[1] ? [dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')] : null);
                setPage(1);
              }}
            />
          </Tooltip>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              setKeyword('');
              setTypeFilter('');
              setDateRange(null);
              setPage(1);
            }}
          >
            重置
          </Button>
          <Button icon={<ReloadOutlined />} onClick={loadList}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增
          </Button>
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
            导入 (.txt/JSON/CSV)
          </Button>
          <Button icon={<DownloadOutlined />} onClick={() => void handleExport('json')}>
            导出 JSON
          </Button>
          <Button icon={<DownloadOutlined />} onClick={() => void handleExport('csv')}>
            导出 CSV
          </Button>
          <Button icon={<EditOutlined />} disabled={selectedRowKeys.length === 0} onClick={() => setBatchTypeOpen(true)}>
            批量修改类型（已选 {selectedRowKeys.length}）
          </Button>
          <Popconfirm title={`确认删除选中的 ${selectedRowKeys.length} 条提示词集？`} onConfirm={() => void handleBatchDelete()}>
            <Button danger icon={<DeleteOutlined />} disabled={selectedRowKeys.length === 0}>
              批量删除
            </Button>
          </Popconfirm>
        </Space>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          size="small"
          scroll={{ x: 1150 }}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys as number[]),
          }}
          expandable={{
            expandedRowRender: (record) => (
              <div className="prompt-set-detail">
                <div>
                  <b>内容：</b>
                  {record.content}
                </div>
                <div>
                  <b>中文翻译：</b>
                  {record.translation || '暂无翻译'}
                </div>
                {record.description ? (
                  <div>
                    <b>备注：</b>
                    {record.description}
                  </div>
                ) : null}
                {record.tags ? (
                  <div>
                    <b>标签：</b>
                    {record.tags}
                  </div>
                ) : null}
                {parseItemDocument(record) ? (
                  <div>
                    <b>结构化：</b>
                    {describePromptDocument(parseItemDocument(record) as PromptDocumentV1)}
                  </div>
                ) : null}
                <Space style={{ marginTop: 8 }}>
                  <Button size="small" icon={<CopyOutlined />} onClick={() => void handleCopy(record.content)}>
                    复制内容
                  </Button>
                  <Button size="small" icon={<CopyOutlined />} onClick={() => void handleCopy(record.translation)}>
                    复制翻译
                  </Button>
                  <Button size="small" icon={<InsertRowAboveOutlined />} onClick={() => void handleInsert(record)}>
                    {record.type === '模板' ? '替换' : '插入'}
                  </Button>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
                    编辑
                  </Button>
                  {parseItemDocument(record) ? (
                    <Button
                      size="small"
                      icon={<BranchesOutlined />}
                      onClick={() => void handleCopy(record.prompt_document_json || '')}
                    >
                      复制结构化 JSON
                    </Button>
                  ) : (
                    <Button
                      size="small"
                      icon={<BranchesOutlined />}
                      loading={convertingId === record.id}
                      onClick={() => confirmConvertToStructured(record)}
                    >
                      转换为结构化
                    </Button>
                  )}
                </Space>
              </div>
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: Array.from(
              new Set([queryConfig.prompt_set_page_size_default, queryConfig.prompt_set_page_size_max]),
            ),
            showTotal: (value) => <Tag>共 {value} 条</Tag>,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      </Drawer>

      <Modal
        title={detailItem ? detailItem.name : '详情'}
        open={!!detailItem}
        onCancel={() => setDetailItem(null)}
        footer={
          detailItem ? (
            <Space>
              <Button icon={<CopyOutlined />} onClick={() => void handleCopy(detailItem.content)}>
                复制内容
              </Button>
              <Button icon={<CopyOutlined />} onClick={() => void handleCopy(detailItem.translation)}>
                复制翻译
              </Button>
              {parseItemDocument(detailItem) ? (
                <Button
                  icon={<BranchesOutlined />}
                  onClick={() => void handleCopy(detailItem.prompt_document_json || '')}
                >
                  复制结构化 JSON
                </Button>
              ) : (
                <Button
                  icon={<BranchesOutlined />}
                  loading={convertingId === detailItem.id}
                  onClick={() => confirmConvertToStructured(detailItem)}
                >
                  转换为结构化
                </Button>
              )}
              <Button icon={<InsertRowAboveOutlined />} onClick={() => void handleInsert(detailItem)}>
                {detailItem.type === '模板' ? '替换' : '插入'}
              </Button>
              <Button
                type="primary"
                icon={<EditOutlined />}
                onClick={() => {
                  openEdit(detailItem);
                  setDetailItem(null);
                }}
              >
                编辑
              </Button>
            </Space>
          ) : null
        }
        width={640}
      >
        {detailItem ? (
          <div className="prompt-set-detail">
            <div>
              <b>类型：</b>
              {detailItem.type}
            </div>
            <div>
              <b>内容：</b>
              {detailItem.content}
            </div>
            <div>
              <b>中文翻译：</b>
              {detailItem.translation || '暂无翻译'}
            </div>
            {detailItem.description ? (
              <div>
                <b>备注：</b>
                {detailItem.description}
              </div>
            ) : null}
            {detailItem.tags ? (
              <div>
                <b>标签：</b>
                {detailItem.tags}
              </div>
            ) : null}
            {parseItemDocument(detailItem) ? (
              <div>
                <b>结构化文档：</b>
                {describePromptDocument(parseItemDocument(detailItem) as PromptDocumentV1)}
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        title={editing ? '编辑提示词集' : '新增提示词集'}
        open={formOpen}
        onOk={() => void handleSave()}
        onCancel={() => setFormOpen(false)}
        confirmLoading={saving}
        width={640}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space>
            <span>名称</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} style={{ width: 220 }} placeholder="例如：黑丝兔女郎" />
            <span>类型</span>
            <Select value={formType} style={{ width: 120 }} options={TYPE_OPTIONS.map((value) => ({ label: value, value }))} onChange={setFormType} />
          </Space>
          <div>
            <span>内容</span>
            <Input.TextArea rows={5} value={content} onChange={(e) => setContent(e.target.value)} placeholder="逗号分隔的英文标签或提示词" />
          </div>
          <Space>
            <span>中文翻译</span>
            <Input.TextArea rows={3} value={translation} onChange={(e) => setTranslation(e.target.value)} style={{ width: 420 }} />
            <Button loading={translating} onClick={() => void handleAutoTranslate()}>
              自动翻译
            </Button>
          </Space>
          <Space>
            <span>备注</span>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: 300 }} placeholder="可选" />
            <span>标签</span>
            <Input value={tags} onChange={(e) => setTags(e.target.value)} style={{ width: 200 }} placeholder="逗号分隔，可选" />
          </Space>
          <div>
            <Space wrap>
              <span>结构化文档</span>
              {formDocument ? (
                <>
                  <Tag color="purple">{describePromptDocument(formDocument)}</Tag>
                  <Button
                    size="small"
                    icon={<CopyOutlined />}
                    onClick={() => void handleCopy(JSON.stringify(formDocument))}
                  >
                    复制 JSON
                  </Button>
                </>
              ) : (
                <Tag>未关联</Tag>
              )}
              <Button size="small" onClick={attachCurrentStructuredDocument}>
                读取当前组
              </Button>
            </Space>
          </div>
        </Space>
      </Modal>

      <Modal
        title={`提示词校验：${checkItem?.name || ''}`}
        open={!!checkItem}
        onCancel={() => setCheckItem(null)}
        footer={<Button onClick={() => setCheckItem(null)}>关闭</Button>}
        width={640}
      >
        {checkResult ? (
          <div className="prompt-set-detail">
            {[...checkResult.errors, ...checkResult.warnings, ...checkResult.suggestions].map((issue, index) => (
              <div key={index} style={{ marginBottom: 6 }}>
                <Tag color={issue.type === 'error' ? 'red' : issue.type === 'warning' ? 'orange' : 'default'}>
                  {issue.type === 'error' ? '错误' : issue.type === 'warning' ? '提醒' : '建议'}
                </Tag>
                {issue.message}
                {issue.tags && issue.tags.length > 0 ? (
                  <Space wrap style={{ marginTop: 4 }}>
                    {issue.tags.map((tag, tagIndex) => (
                      <Tooltip key={`${tag}-${tagIndex}`} title={checkTranslations[tag] || '暂无翻译'}>
                        <Tag style={{ cursor: 'pointer' }} onClick={() => void handleRemoveTag(tag)}>
                          {tag} ✕
                        </Tag>
                      </Tooltip>
                    ))}
                  </Space>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="train-status-text">校验中…</div>
        )}
      </Modal>

      <Modal
        title="导入提示词集"
        open={importOpen}
        onOk={() => void handleImportConfirm()}
        onCancel={() => {
          setImportOpen(false);
          setImportLines([]);
          setImportRaw('');
          setImportFileType('');
        }}
        confirmLoading={importing}
        width={640}
      >
        <input type="file" accept=".txt,.json,.csv,text/plain,application/json,text/csv" onChange={(e) => handleImportFile(e.target.files?.[0])} />
        {importFileType ? (
          <div className="train-status-text" style={{ marginTop: 8 }}>
            已选择 {importFileType.toUpperCase()} 文件，将按 {importFileType.toUpperCase()} 格式导入
          </div>
        ) : null}
        {importLines.length > 0 ? (
          <div className="train-log" style={{ marginTop: 10 }}>
            {importLines.map((line, index) => (
              <div key={index} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{line}</span>
                <Button
                  size="small"
                  type="link"
                  danger
                  onClick={() => setImportLines((prev) => prev.filter((_, i) => i !== index))}
                >
                  移除
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ color: '#6b7280', fontSize: 13, marginTop: 8 }}>支持 .txt（每行一个）、.json（数组）、.csv（带表头）</div>
        )}
      </Modal>

      <Modal
        title="批量修改类型"
        open={batchTypeOpen}
        onOk={() => void handleBatchType()}
        onCancel={() => setBatchTypeOpen(false)}
        confirmLoading={batchSaving}
      >
        <Space>
          <span>将修改 {selectedRowKeys.length} 条记录的类型为：</span>
          <Select
            value={batchType}
            style={{ width: 140 }}
            options={TYPE_OPTIONS.map((value) => ({ label: value, value }))}
            onChange={setBatchType}
          />
        </Space>
      </Modal>
    </>
  );
}
