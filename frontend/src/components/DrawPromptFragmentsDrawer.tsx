import {
  PlusOutlined,
  SearchOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons';
import {
  Button,
  Drawer,
  Empty,
  Input,
  List,
  Select,
  Space,
  Tag,
  Tooltip,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import {
  DRAW_PROMPT_FRAGMENTS,
  type DrawPromptFragment,
} from '../drawPromptFragments';

const FAVORITES_KEY = 'rider-studio:draw-prompt-fragment-favorites-v1';

function loadFavorites(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]');
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === 'string')
      : [];
  } catch {
    return [];
  }
}

export default function DrawPromptFragmentsDrawer({
  open,
  onClose,
  onInsert,
}: {
  open: boolean;
  onClose: () => void;
  onInsert: (fragment: DrawPromptFragment) => void;
}) {
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState('');
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [favorites, setFavorites] = useState<string[]>(loadFavorites);

  useEffect(() => {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites));
  }, [favorites]);

  const categories = useMemo(
    () => Array.from(new Set(DRAW_PROMPT_FRAGMENTS.map((item) => item.category))),
    [],
  );
  const items = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return DRAW_PROMPT_FRAGMENTS.filter((item) => {
      if (favoritesOnly && !favorites.includes(item.id)) return false;
      if (category && item.category !== category) return false;
      return (
        !query ||
        [item.label, item.description, item.category, ...item.tags]
          .join(' ')
          .toLowerCase()
          .includes(query)
      );
    });
  }, [category, favorites, favoritesOnly, keyword]);

  const toggleFavorite = (id: string) => {
    setFavorites((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [id, ...current],
    );
  };

  return (
    <Drawer
      title="提示词片段"
      width="min(760px, 96vw)"
      open={open}
      onClose={onClose}
      className="draw-fragment-drawer"
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <div className="draw-fragment-toolbar">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索片段、说明或标签"
            aria-label="搜索提示词片段"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <Select
            allowClear
            placeholder="分类"
            value={category || undefined}
            options={categories.map((value) => ({ label: value, value }))}
            onChange={(value) => setCategory(value || '')}
          />
          <Button
            type={favoritesOnly ? 'primary' : 'default'}
            icon={favoritesOnly ? <StarFilled /> : <StarOutlined />}
            aria-label="只看收藏片段"
            onClick={() => setFavoritesOnly((value) => !value)}
          >
            收藏 {favorites.length}
          </Button>
          <Tag>{items.length} 个片段</Tag>
        </div>

        {items.length ? (
          <List
            dataSource={items}
            renderItem={(item) => {
              const favorite = favorites.includes(item.id);
              return (
                <List.Item className="draw-fragment-item">
                  <div className="draw-fragment-copy">
                    <div className="draw-fragment-title">
                      <strong>{item.label}</strong>
                      <Tag color="blue">{item.category}</Tag>
                    </div>
                    <div className="draw-fragment-description">
                      {item.description}
                    </div>
                    <Space size={[4, 4]} wrap>
                      {item.tags.map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </Space>
                  </div>
                  <Space>
                    <Tooltip title={favorite ? '取消收藏' : '收藏'}>
                      <Button
                        icon={favorite ? <StarFilled /> : <StarOutlined />}
                        aria-label={favorite ? '取消收藏片段' : '收藏片段'}
                        onClick={() => toggleFavorite(item.id)}
                      />
                    </Tooltip>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      aria-label={`插入片段 ${item.label}`}
                      onClick={() => onInsert(item)}
                    >
                      插入
                    </Button>
                  </Space>
                </List.Item>
              );
            }}
          />
        ) : (
          <Empty description="没有符合条件的提示词片段" />
        )}
      </Space>
    </Drawer>
  );
}
