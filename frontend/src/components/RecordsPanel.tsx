// 数据看板：按日筛选、分页、导出 Excel
import { Button, DatePicker, message, Popover, Select, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect } from 'react';
import { recordsStore, loadRecords, exportExcel, type RecordsKind } from '../stores/records';

const kindOptions = [
  { label: '招聘 Agent 对话', value: 'agent' },
  { label: 'AI 绘画', value: 'draw' },
  { label: '提示词 Agent', value: 'prompt' },
];

// 数据库字段名到中文表头的映射
const headerMap: Record<RecordsKind, Record<string, string>> = {
  agent: {
    id: 'ID',
    session_id: '会话ID',
    created_at: '对话时间',
    sender: '发送人',
    content: '对话内容',
    retrieval_score: '检索匹配度',
    source: '来源',
  },
  draw: {
    id: 'ID',
    batch_id: '批次ID',
    group_index: '组号',
    started_at: '任务开始时间',
    finished_at: '任务结束时间',
    duration_seconds: '任务耗时(秒)',
    prompt: '提示词',
    prompt_translation: '提示词翻译',
    negative_prompt: '负面提示词',
    negative_translation: '负面提示词翻译',
    width: '宽度',
    height: '高度',
    steps: '步数',
    cfg: 'CFG',
    model: '模型',
    lora_anima_turbo: 'anima-turbo-lora-v0.2',
    lora_high_contrast: 'high-contrast aesthetic',
    image_path: '图片路径',
    image_url: '图片地址',
    seed: '随机种子',
    status: '状态',
    error: '错误信息',
  },
  prompt: {
    id: 'ID',
    started_at: '任务开始时间',
    finished_at: '任务结束时间',
    duration_seconds: '任务耗时(秒)',
    mode: '模式',
    user_input: '用户输入',
    image_path: '图片路径',
    description: '原始描述',
    prompt_result: '生成提示词',
    model: '模型',
    status: '状态',
  },
};

// 把英文枚举值显示成中文
function formatValue(key: string, value: unknown): string {
  if (key === 'sender') return value === 'assistant' ? '大模型' : value === 'user' ? '用户' : String(value ?? '');
  if (key === 'source') return value === 'llm' ? '大模型回答' : value === 'fallback' ? '检索回答' : String(value ?? '');
  if (key === 'status') return value === 'success' ? '成功' : value === 'running' ? '进行中' : value === 'error' ? '失败' : String(value ?? '');
  if (key === 'mode') return value === 'image' ? '图片' : value === 'text' ? '文字' : String(value ?? '');
  if (key === 'lora_anima_turbo' || key === 'lora_high_contrast') return value === 1 || value === '1' ? '是' : '否';
  return String(value ?? '');
}

// 长文本字段需要换行显示
const wrapKeys = new Set([
  'prompt',
  'prompt_translation',
  'negative_prompt',
  'negative_translation',
  'content',
  'description',
  'prompt_result',
  'user_input',
  'image_path',
  'image_url',
  'error',
]);

// 一键复制到剪贴板
async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    message.success('已复制');
  } catch (e) {
    message.error('复制失败');
  }
}

export default function RecordsPanel() {
  const { kind, page, pageSize, dateFrom, dateTo, data, loading } = recordsStore;

  useEffect(() => {
    void loadRecords();
  }, [kind, page, pageSize, dateFrom, dateTo]);

  // 动态生成表格列：表头中文、长文本换行、提示词可复制
  const keys = data?.items?.[0] ? Object.keys(data.items[0]) : [];
  const columns: ColumnsType<Record<string, unknown>> = keys.map((key) => {
    const isWrap = wrapKeys.has(key);
    return {
      title: headerMap[kind][key] || key,
      dataIndex: key,
      key,
      ellipsis: !isWrap,
      render: (value: unknown) => {
        const text = formatValue(key, value);
        if (!isWrap) return text;
        return (
          <div className="cell-action">
            <Popover
              trigger="hover"
              placement="topLeft"
              title={headerMap[kind][key] || key}
              content={<div className="popover-text">{text}</div>}
            >
              <span className="cell-ellipsis">{text}</span>
            </Popover>
            {key === 'prompt' && (
              <Button size="small" type="link" onClick={() => void copyText(String(value ?? ''))}>
                复制
              </Button>
            )}
          </div>
        );
      },
    };
  });

  return (
    <div className="panel-box records-box">
      <div className="records-bar">
        <Select
          value={kind}
          options={kindOptions}
          onChange={(value) => {
            recordsStore.kind = value as RecordsKind;
            recordsStore.page = 1;
          }}
          style={{ width: 160 }}
        />
        <DatePicker.RangePicker
          value={[dateFrom ? dayjs(dateFrom) : null, dateTo ? dayjs(dateTo) : null]}
          onChange={(dates: [Dayjs | null, Dayjs | null] | null) => {
            recordsStore.dateFrom = dates?.[0] ? dates[0].format('YYYY-MM-DD') : '';
            recordsStore.dateTo = dates?.[1] ? dates[1].format('YYYY-MM-DD') : '';
            recordsStore.page = 1;
          }}
        />
        <Select
          value={pageSize}
          options={[10, 20, 50, 100].map((value) => ({ label: `${value} 条/页`, value }))}
          onChange={(value) => {
            recordsStore.pageSize = value;
            recordsStore.page = 1;
          }}
          style={{ width: 120 }}
        />
        <Button onClick={exportExcel}>导出 Excel</Button>
      </div>
      <Table
        rowKey={(record) => String(record.id ?? '')}
        columns={columns}
        dataSource={data?.items || []}
        loading={loading}
        size="small"
        scroll={{ x: true }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total || 0,
          showSizeChanger: false,
          showTotal: (total) => <Tag>共 {total} 条</Tag>,
          onChange: (nextPage) => {
            recordsStore.page = nextPage;
          },
        }}
      />
    </div>
  );
}
