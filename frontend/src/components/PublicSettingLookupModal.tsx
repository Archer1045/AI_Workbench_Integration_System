import { Alert, Button, Checkbox, Empty, Input, List, Modal, Space, Tag, message } from 'antd';
import { useEffect, useState } from 'react';
import { api } from '../api';

interface PublicSettingItem {
  title: string;
  url: string;
  summary: string;
  date: string | null;
  authority: number | null;
  site_name: string | null;
}

interface Props {
  open: boolean;
  initialQuery?: string;
  onClose: () => void;
  onUse: (text: string) => void;
}

export default function PublicSettingLookupModal({ open, initialQuery = '', onClose, onUse }: Props) {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<PublicSettingItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    if (!open) return;
    setQuery(initialQuery);
    setItems([]);
    setSelected([]);
    setSearched(false);
  }, [open, initialQuery]);

  const lookup = async () => {
    const value = query.trim();
    if (!value) {
      message.warning('请输入角色名和作品');
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post<{ results: PublicSettingItem[] }>('/prompt-agent/public-setting-lookup', {
        query: value,
        count: 6,
      });
      setItems(data.results || []);
      setSelected([]);
      setSearched(true);
      if (!(data.results || []).length) message.warning('没有找到可用的公开设定候选');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '公开设定查询失败');
    } finally {
      setLoading(false);
    }
  };

  const useSelected = () => {
    const chosen = items.filter((item) => selected.includes(item.url));
    if (!chosen.length) {
      message.warning('请先勾选要参考的候选');
      return;
    }
    onUse(
      chosen
        .map((item) => `${item.title}：${item.summary}（来源：${item.url}）`)
        .join('\n'),
    );
    onClose();
  };

  return (
    <Modal
      title="查询公开设定"
      open={open}
      onCancel={onClose}
      width={780}
      footer={[
        <Button key="close" onClick={onClose}>
          取消
        </Button>,
        <Button key="use" type="primary" disabled={!selected.length} onClick={useSelected}>
          使用选中设定
        </Button>,
      ]}
    >
      <Alert
        type="info"
        showIcon
        message="只查询作品、官方名称、服装和文字设定"
        description="候选不会自动覆盖已有角色预设，也不会把搜索结果当图片参考。确认后会填入左侧描述框，仍需你重新生成提示词。"
      />
      <Space.Compact style={{ width: '100%', marginTop: 12 }}>
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onPressEnter={() => void lookup()}
          placeholder="角色名 + 作品，例如：流萤 崩坏：星穹铁道"
        />
        <Button type="primary" loading={loading} onClick={() => void lookup()}>
          查询
        </Button>
      </Space.Compact>
      {searched && items.length === 0 ? <Empty description="没有找到候选设定" /> : null}
      <List
        style={{ marginTop: 12, maxHeight: 430, overflow: 'auto' }}
        dataSource={items}
        renderItem={(item) => (
          <List.Item key={item.url}>
            <Space direction="vertical" size={4} style={{ width: '100%', minWidth: 0 }}>
              <Checkbox
                checked={selected.includes(item.url)}
                onChange={(event) =>
                  setSelected((previous) =>
                    event.target.checked ? [...previous, item.url] : previous.filter((url) => url !== item.url),
                  )
                }
              >
                <strong>{item.title || item.url}</strong>
              </Checkbox>
              <Space wrap size={4}>
                <Tag>{item.authority == null ? '权威度未知' : `权威度 ${item.authority}`}</Tag>
                {item.date ? <Tag>{item.date}</Tag> : null}
                {item.site_name ? <Tag>{item.site_name}</Tag> : null}
              </Space>
              <div className="public-setting-summary">{item.summary}</div>
              <a href={item.url} target="_blank" rel="noreferrer">
                {item.url}
              </a>
            </Space>
          </List.Item>
        )}
      />
    </Modal>
  );
}
