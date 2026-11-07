// 双语标签对照：hover 显示中文翻译，点击复制英文标签；不做插入/删除
import { CopyOutlined } from '@ant-design/icons';
import { Button, Input, message, Segmented, Space, Tag, Tooltip } from 'antd';
import { useMemo, useState } from 'react';

export interface TagCompareRow {
  tag: string;
  translation: string;
}

interface TagCompareTableProps {
  rows: TagCompareRow[];
  originalText?: string;
}

export default function TagCompareTable({ rows, originalText }: TagCompareTableProps) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'translated' | 'missing'>('all');
  const [mode, setMode] = useState<'tags' | 'original'>('tags');
  const [activeTag, setActiveTag] = useState('');

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    const seen = new Set<string>();
    return rows.filter((row) => {
      if (seen.has(row.tag)) return false;
      seen.add(row.tag);
      const matchSearch =
        !keyword ||
        row.tag.toLowerCase().includes(keyword) ||
        row.translation.toLowerCase().includes(keyword);
      const matchFilter =
        filter === 'all' ? true : filter === 'translated' ? !!row.translation : !row.translation;
      return matchSearch && matchFilter;
    });
  }, [rows, search, filter]);

  const tagMap = useMemo(() => {
    const map = new Map<string, string>();
    rows.forEach((row) => {
      const key = row.tag.toLowerCase();
      if (!map.has(key)) map.set(key, row.translation);
    });
    return map;
  }, [rows]);

  const segments = useMemo(
    () =>
      (originalText || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    [originalText],
  );

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制');
    } catch {
      message.error('复制失败');
    }
  };

  const pickTag = async (tag: string) => {
    setActiveTag(activeTag.toLowerCase() === tag.toLowerCase() ? '' : tag);
    await copyText(tag);
  };

  return (
    <div className="tag-compare">
      <Space wrap style={{ marginBottom: 6 }}>
        {originalText !== undefined ? (
          <Segmented
            size="small"
            value={mode}
            options={[
              { label: '标签对照', value: 'tags' },
              { label: '原文高亮', value: 'original' },
            ]}
            onChange={(value) => setMode(value as 'tags' | 'original')}
          />
        ) : null}
        {mode === 'tags' ? (
          <>
            <Input.Search
              allowClear
              size="small"
              placeholder="搜索标签"
              style={{ width: 180 }}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Segmented
              size="small"
              value={filter}
              options={[
                { label: '全部', value: 'all' },
                { label: '已翻译', value: 'translated' },
                { label: '未翻译', value: 'missing' },
              ]}
              onChange={(value) => setFilter(value as 'all' | 'translated' | 'missing')}
            />
            <Button size="small" onClick={() => void copyText(filtered.map((row) => row.tag).join(', '))}>
              复制全部英文
            </Button>
            <Button
              size="small"
              onClick={() => void copyText(filtered.map((row) => row.translation).filter(Boolean).join(', '))}
            >
              复制全部中文
            </Button>
          </>
        ) : null}
      </Space>
      {mode === 'tags' ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, maxHeight: 260, overflowY: 'auto', alignContent: 'flex-start' }}>
          {filtered.map((row, index) => (
            <Tooltip key={`${row.tag}-${index}`} title={row.translation || '暂无翻译'}>
              <Tag
                style={{ cursor: 'pointer', margin: 0 }}
                icon={<CopyOutlined />}
                onClick={() => void pickTag(row.tag)}
              >
                {row.tag}
              </Tag>
            </Tooltip>
          ))}
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            maxHeight: 260,
            overflowY: 'auto',
            alignContent: 'flex-start',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            padding: 8,
            minWidth: 0,
          }}
        >
          {segments.map((segment, index) => {
            const lower = segment.toLowerCase();
            const isKnown = tagMap.has(lower);
            const isActive = activeTag && lower === activeTag.toLowerCase();
            return (
              <Tooltip key={`${segment}-${index}`} title={tagMap.get(lower) || (isKnown ? '已匹配' : '未匹配')}>
                <span
                  onClick={() => void pickTag(segment)}
                  style={{
                    display: 'inline-flex',
                    maxWidth: '100%',
                    cursor: 'pointer',
                    borderRadius: 4,
                    padding: '3px 7px',
                    fontSize: 12,
                    lineHeight: 1.5,
                    wordBreak: 'break-word',
                    whiteSpace: 'normal',
                    background: isActive ? '#2563eb' : isKnown ? '#dbeafe' : '#f3f4f6',
                    color: isActive ? '#ffffff' : isKnown ? '#1e40af' : '#4b5563',
                  }}
                >
                  {segment}
                </span>
              </Tooltip>
            );
          })}
          {segments.length === 0 ? <span style={{ color: '#9ca3af', fontSize: 12 }}>暂无原文内容</span> : null}
        </div>
      )}
    </div>
  );
}
