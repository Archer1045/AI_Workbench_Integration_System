// 图片库：按时间/模型/状态筛选，缩略图预览与删除
import { DeleteOutlined, DownloadOutlined, EyeOutlined, FolderOpenOutlined, ImportOutlined, PictureOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, DatePicker, Drawer, Input, message, Popconfirm, Segmented, Select, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect, useState, type Key } from 'react';
import { api, type DrawImageRecord, type ImageLibrary, type ModelItem } from '../api';
import { visibleDrawLoras } from '../drawLoras';
import { getRuntimeConfig } from '../stores/runtimeConfig';

interface BatchGroup {
  batch_id: string;
  count: number;
  success_count: number;
  error_count: number;
  last_at?: string;
  image_url?: string;
}

export default function ImageLibraryDrawer({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect?: (record: DrawImageRecord) => void;
}) {
  const queryConfig = getRuntimeConfig().query;
  const [items, setItems] = useState<DrawImageRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(queryConfig.image_library_page_size_default);
  const [loading, setLoading] = useState(false);
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const [modelFilter, setModelFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [models, setModels] = useState<ModelItem[]>([]);
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [view, setView] = useState<'list' | 'batches'>('list');
  const [keyword, setKeyword] = useState('');
  const [batchId, setBatchId] = useState('');
  const [batches, setBatches] = useState<BatchGroup[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .get<ImageLibrary>('/images/library', {
        params: {
          date_from: dateRange?.[0] || undefined,
          date_to: dateRange?.[1] || undefined,
          model: modelFilter || undefined,
          status: statusFilter || undefined,
          keyword: keyword || undefined,
          batch_id: batchId || undefined,
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
    if (open) load();
  }, [open, page, pageSize, dateRange, modelFilter, statusFilter, keyword, batchId]);

  useEffect(() => {
    if (open && view === 'batches') {
      setBatchesLoading(true);
      api
        .get<{ items: BatchGroup[] }>('/images/library/batches', {
          params: {
            date_from: dateRange?.[0] || undefined,
            date_to: dateRange?.[1] || undefined,
            model: modelFilter || undefined,
            status: statusFilter || undefined,
            keyword: keyword || undefined,
          },
        })
        .then((res) => setBatches(res.data.items || []))
        .catch(() => setBatches([]))
        .finally(() => setBatchesLoading(false));
    }
  }, [open, view, dateRange, modelFilter, statusFilter, keyword]);

  useEffect(() => {
    api
      .get<{ models: ModelItem[] }>('/models')
      .then((res) => setModels(res.data.models || []))
      .catch(() => setModels([]));
  }, []);

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/images/library/${id}`);
      message.success('已删除');
      if (items.length === 1 && page > 1) setPage(page - 1);
      else load();
    } catch {
      message.error('删除失败');
    }
  };

  const handleImportToDataset = async () => {
    if (selectedRowKeys.length === 0) return;
    try {
      const { data } = await api.post<{ ok: boolean; imported: string[]; skipped: string[] }>('/train/dataset/import-images', {
        filenames: selectedRowKeys,
      });
      message.success(`已导入 ${data.imported.length} 张${data.skipped.length ? `，跳过 ${data.skipped.length} 张` : ''}`);
      setSelectedRowKeys([]);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '导入失败');
    }
  };

  const handleExport = async () => {
    if (selectedRowKeys.length === 0) return;
    try {
      const res = await api.post('/images/library/export', { ids: selectedRowKeys }, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'image-library.zip';
      anchor.click();
      URL.revokeObjectURL(url);
      message.success('导出完成');
    } catch {
      message.error('导出失败');
    }
  };

  const handleOpenLibrary = () => {
    api.post('/images/open-library').catch(() => message.error('打开图库失败'));
  };

  const columns: ColumnsType<DrawImageRecord> = [
    {
      title: '预览',
      key: 'preview',
      width: 80,
      render: (_, record) =>
        record.image_url ? (
          <img
            className="library-thumb"
            loading="lazy"
            src={record.image_url}
            alt=""
            onClick={() => record.image_url && window.open(record.image_url, '_blank')}
          />
        ) : (
          <span>无</span>
        ),
    },
    { title: '时间', dataIndex: 'started_at', key: 'started_at', width: 170, render: (value: string) => String(value).slice(0, 16) },
    { title: '模型', dataIndex: 'model', key: 'model', width: 220, ellipsis: true },
    {
      title: 'LoRA',
      key: 'loras',
      width: 260,
      render: (_, record) => {
        const { visible, hiddenCount, tooltip } = visibleDrawLoras(record);
        if (visible.length === 0) return <span>无</span>;
        return (
          <Tooltip title={tooltip}>
            <Space size={[4, 4]} wrap>
              {visible.map((name) => (
                <Tag key={name}>{name}</Tag>
              ))}
              {hiddenCount > 0 ? <Tag>+{hiddenCount}</Tag> : null}
            </Space>
          </Tooltip>
        );
      },
    },
    {
      title: '尺寸',
      key: 'size',
      width: 110,
      render: (_, record) => `${record.width || 0}x${record.height || 0}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (value: string) => (
        <Tag color={value === 'success' ? 'green' : value === 'running' ? 'processing' : value === 'error' ? 'red' : 'default'}>
          {value || 'unknown'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: onSelect ? 240 : 150,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          {onSelect ? (
            <Button
              size="small"
              icon={<PictureOutlined />}
              disabled={!record.image_url}
              onClick={() => onSelect(record)}
            >
              作为底图
            </Button>
          ) : null}
          <Button
            size="small"
            icon={<EyeOutlined />}
            disabled={!record.image_url}
            onClick={() => record.image_url && window.open(record.image_url, '_blank')}
          >
            查看
          </Button>
          <Popconfirm title="确认删除该图片记录？" onConfirm={() => void handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const batchColumns: ColumnsType<BatchGroup> = [
    { title: '批次ID', dataIndex: 'batch_id', key: 'batch_id', ellipsis: true },
    { title: '张数', dataIndex: 'count', key: 'count', width: 80 },
    {
      title: '成功',
      dataIndex: 'success_count',
      key: 'success_count',
      width: 80,
      render: (value: number) => <Tag color="green">{value || 0}</Tag>,
    },
    {
      title: '失败',
      dataIndex: 'error_count',
      key: 'error_count',
      width: 80,
      render: (value: number) => <Tag color={value ? 'red' : 'default'}>{value || 0}</Tag>,
    },
    { title: '最近时间', dataIndex: 'last_at', key: 'last_at', width: 170, render: (value: string) => String(value || '').slice(0, 16) },
    {
      title: '操作',
      key: 'action',
      width: 110,
      render: (_, record) => (
        <Button
          size="small"
          onClick={() => {
            setBatchId(record.batch_id);
            setView('list');
            setPage(1);
          }}
        >
          查看批次
        </Button>
      ),
    },
  ];

  return (
    <Drawer title="图片库" width={1120} open={open} onClose={onClose}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          value={view}
          options={[
            { label: '列表', value: 'list' },
            { label: '批次分组', value: 'batches' },
          ]}
          onChange={(value) => {
            setView(value as 'list' | 'batches');
            setPage(1);
          }}
        />
        <Input.Search
          allowClear
          placeholder="搜索提示词/文件名"
          style={{ width: 220 }}
          onSearch={(value) => {
            setKeyword(value.trim());
            setPage(1);
          }}
        />
        <DatePicker.RangePicker
          onChange={(dates: [Dayjs | null, Dayjs | null] | null) => {
            setDateRange(dates?.[0] && dates[1] ? [dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')] : null);
            setPage(1);
          }}
        />
        <Tooltip title="按绘画底模筛选图片。">
          <Select
            allowClear
            placeholder="模型"
            style={{ width: 260 }}
            value={modelFilter || undefined}
            options={models.map((item) => ({ label: item.name, value: item.name }))}
            onChange={(value) => {
              setModelFilter(value || '');
              setPage(1);
            }}
          />
        </Tooltip>
        <Tooltip title="按生成状态筛选图片（成功/运行中/失败/已停止）。">
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={statusFilter || undefined}
            options={['success', 'running', 'error', 'stopped'].map((value) => ({ label: value, value }))}
            onChange={(value) => {
              setStatusFilter(value || '');
              setPage(1);
            }}
          />
        </Tooltip>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => {
            setDateRange(null);
            setModelFilter('');
            setStatusFilter('');
            setPage(1);
          }}
        >
          重置
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
        <Button icon={<DownloadOutlined />} disabled={selectedRowKeys.length === 0} onClick={() => void handleExport()}>
          导出选中
        </Button>
        <Button icon={<FolderOpenOutlined />} onClick={handleOpenLibrary}>
          打开本地图库
        </Button>
        <Button type="primary" icon={<ImportOutlined />} disabled={selectedRowKeys.length === 0} onClick={() => void handleImportToDataset()}>
          加入训练集（{selectedRowKeys.length}）
        </Button>
      </Space>
      {view === 'batches' ? (
        <Table
          rowKey="batch_id"
          columns={batchColumns}
          dataSource={batches}
          loading={batchesLoading}
          size="small"
          scroll={{ x: true }}
          pagination={false}
        />
      ) : (
        <Table
          rowKey="id"
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
          }}
          columns={columns}
          dataSource={items}
          loading={loading}
          size="small"
          scroll={{ x: true }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: Array.from(
              new Set([queryConfig.image_library_page_size_default, queryConfig.image_library_page_size_max]),
            ),
            showTotal: (value) => <Tag>共 {value} 条</Tag>,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      )}
    </Drawer>
  );
}
