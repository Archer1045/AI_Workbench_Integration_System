import { useEffect, useRef, useState } from 'react';
import { Button, Input, Tag, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';

type ShipSkin = {
  id: string;
  name: string;
  painting: string;
  icon: string | null;
};

type Ship = {
  id: string;
  name: string;
  english_name: string;
  type: string;
  star: number;
  rarity: number;
  nationality: number;
  icon: string | null;
  painting: string;
  attrs: Record<string, number>;
  attrs_max: Record<string, number>;
  skins: ShipSkin[];
};

type ShipBrief = {
  id: string;
  name: string;
  type: string;
  star: number;
  rarity: number;
  icon: string | null;
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  ship?: Ship;
  ships?: ShipBrief[];
};

const EXAMPLES = ['企业', '拉菲', '胡德', '贝尔法斯特', '信浓'];

// 主要属性展示顺序
const ATTR_ORDER = ['耐久', '炮击', '雷击', '防空', '航空', '装填', '命中', '机动', '航速', '反潜'];

export default function AzurPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const loadShip = async (name: string, baseContent: string) => {
    try {
      const resp = await fetch(`/api/azur/ship/${encodeURIComponent(name)}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const ship: Ship = await resp.json();
      setMessages((prev) => {
        const next = [...prev];
        // 替换最后一条空回复
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === 'assistant' && !next[i].content) {
            next[i] = { ...next[i], content: baseContent, ship };
            return next;
          }
        }
        return [...next, { role: 'assistant', content: baseContent, ship }];
      });
    } catch (err) {
      message.error(`加载舰船失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const query = async (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || loading) return;
    setInput('');
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: q },
      { role: 'assistant', content: '' },
    ]);
    setLoading(true);

    try {
      // 先搜索，命中就加载详情
      const resp = await fetch(`/api/azur/search?q=${encodeURIComponent(q)}&limit=8`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const results: ShipBrief[] = data.results || [];

      if (!results.length) {
        setMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === 'assistant' && !next[i].content) {
              next[i] = { ...next[i], content: `没有找到「${q}」，换个名字试试？` };
              return next;
            }
          }
          return next;
        });
        setLoading(false);
        return;
      }

      if (results.length === 1) {
        await loadShip(results[0].name, `${results[0].name}（${results[0].type}，${results[0].star} 星）`);
      } else {
        // 多个结果，列出候选
        setMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === 'assistant' && !next[i].content) {
              next[i] = {
                ...next[i],
                content: `找到 ${results.length} 个相关舰船，点击查看：`,
                ships: results,
              };
              return next;
            }
          }
          return next;
        });
      }
    } catch (err) {
      message.error(`查询失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const renderAttrs = (ship: Ship) => {
    const max = ship.attrs_max || {};
    const items = ATTR_ORDER.filter((k) => max[k] !== undefined && max[k] > 0);
    if (!items.length) return null;
    return (
      <div className="ak-stats">
        {items.map((k) => (
          <div key={k} className="ak-stat">
            <span className="ak-stat-label">{k}</span>
            <span className="ak-stat-value">{Math.round(max[k])}</span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="mc-chat">
      <div className="mc-head">
        <div>
          <h2>碧蓝航线助手</h2>
          <p>查舰船属性、皮肤、装备，共 945 艘舰船</p>
        </div>
        <Button size="small" onClick={() => setMessages([])} disabled={!messages.length}>
          清空
        </Button>
      </div>

      <div className="mc-list" ref={listRef}>
        {messages.length === 0 ? (
          <div className="mc-empty">
            <p>试试这些：</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
              {EXAMPLES.map((x) => (
                <Tag key={x} className="mc-example" onClick={() => void query(x)}>
                  {x}
                </Tag>
              ))}
            </div>
          </div>
        ) : null}

        {messages.map((item, index) => (
          <div key={index} className={`mc-msg ${item.role}`}>
            <div className="mc-avatar">{item.role === 'user' ? '你' : '舰'}</div>
            <div className="mc-body">
              <div className="mc-text">{item.content}</div>

              {item.ship ? (
                <div className="ak-op">
                  <div className="ak-op-head">
                    {item.ship.icon ? (
                      <img className="ak-avatar" src={item.ship.icon} alt={item.ship.name} />
                    ) : (
                      <div className="ak-avatar ak-avatar-empty" />
                    )}
                    <div className="ak-op-info">
                      <div className="ak-op-name">
                        {item.ship.name}
                        <Tag color={item.ship.star >= 6 ? 'gold' : item.ship.star >= 5 ? 'purple' : 'blue'}>
                          {item.ship.star} 星
                        </Tag>
                      </div>
                      <div className="ak-op-sub">{item.ship.type}</div>
                      <div className="ak-op-en">{item.ship.english_name}</div>
                    </div>
                  </div>

                  {renderAttrs(item.ship)}

                  {item.ship.skins.length > 1 ? (
                    <div className="ak-talents">
                      <span className="ak-label">皮肤（{item.ship.skins.length}）</span>
                      {item.ship.skins.slice(0, 6).map((s) => (
                        <div key={s.id} className="ak-talent">
                          <b>{s.name || '默认皮肤'}</b>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {item.ships?.length ? (
                <div className="ak-op-grid">
                  {item.ships.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className="ak-op-chip"
                      onClick={() => void query(s.name)}
                    >
                      {s.icon ? <img src={s.icon} alt={s.name} /> : null}
                      <span>{s.name}</span>
                      <span className="ak-op-chip-rarity">{s.star}★</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="mc-msg assistant">
            <div className="mc-avatar">舰</div>
            <div className="mc-body">
              <div className="mc-text">正在查询…</div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="mc-composer">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={() => void query()}
          placeholder="输入舰船名，例如「企业」「拉菲」"
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void query()}>
          查询
        </Button>
      </div>
      <div className="mc-hint">数据来自 AzurLaneData（CN 服），图标来自 AzurAssets</div>
    </div>
  );
}
