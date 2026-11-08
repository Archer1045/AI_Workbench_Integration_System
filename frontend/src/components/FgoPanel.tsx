import { useEffect, useRef, useState } from 'react';
import { Button, Input, Tag, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';

type ServantSkill = {
  name: string;
  detail: string;
};

type ServantNP = {
  name: string;
  rank: string;
  card: string;
  detail: string;
};

type Servant = {
  id: number;
  name: string;
  original_name: string;
  class_name: string;
  rarity: number;
  atk_max: number;
  hp_max: number;
  cost: number;
  face: string;
  skills: ServantSkill[];
  noble_phantasms: ServantNP[];
};

type ServantBrief = {
  id: number;
  name: string;
  class_name: string;
  rarity: number;
  face: string;
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  servant?: Servant;
  servants?: ServantBrief[];
  listLabel?: string;
};

const EXAMPLES = ['阿尔托莉雅', '吉尔伽美什', '玛修', '斯卡哈'];

const RARITY_COLOR: Record<number, string> = {
  0: 'default',
  1: 'default',
  2: 'default',
  3: 'blue',
  4: 'purple',
  5: 'gold',
};

export default function FgoPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const query = async (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || loading) return;
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: q }]);
    setLoading(true);

    const placeholderIndex = { current: -1 };
    setMessages((prev) => {
      placeholderIndex.current = prev.length;
      return [...prev, { role: 'assistant' as const, content: '' }];
    });

    const patchLast = (patch: Partial<Message>) => {
      setMessages((prev) => {
        const idx = placeholderIndex.current;
        if (idx < 0 || idx >= prev.length) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      });
    };

    const appendText = (chunk: string) => {
      setMessages((prev) => {
        const idx = placeholderIndex.current;
        if (idx < 0 || idx >= prev.length) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx], content: (next[idx].content || '') + chunk };
        return next;
      });
    };

    try {
      const resp = await fetch('/api/fgo/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep = buffer.indexOf('\n\n');
        while (sep >= 0) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          sep = buffer.indexOf('\n\n');

          for (const line of frame.split('\n')) {
            if (!line.startsWith('data: ')) continue;
            let evt: any;
            try {
              evt = JSON.parse(line.slice(6));
            } catch {
              continue;
            }
            if (evt.type === 'meta') {
              if (evt.servant) {
                patchLast({ servant: evt.servant });
              }
              if (evt.servants) {
                patchLast({ servants: evt.servants, listLabel: evt.list_label });
              }
            } else if (evt.type === 'delta' && evt.content) {
              appendText(evt.content);
            } else if (evt.type === 'error') {
              appendText(`\n[出错了：${evt.message}]`);
            }
          }
        }
      }
    } catch (err) {
      message.error(`查询失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mc-chat">
      <div className="mc-head">
        <div>
          <h2>FGO 助手</h2>
          <p>查从者属性、技能、宝具，共 461 名从者</p>
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
            <div className="mc-avatar">{item.role === 'user' ? '你' : '迦'}</div>
            <div className="mc-body">
              <div className="mc-text">{item.content}</div>

              {item.servant ? (
                <div className="ak-op">
                  <div className="ak-op-head">
                    {item.servant.face ? (
                      <img className="ak-avatar" src={item.servant.face} alt={item.servant.name} />
                    ) : (
                      <div className="ak-avatar ak-avatar-empty" />
                    )}
                    <div className="ak-op-info">
                      <div className="ak-op-name">
                        {item.servant.name}
                        <Tag color={RARITY_COLOR[item.servant.rarity] || 'default'}>
                          {item.servant.rarity} 星
                        </Tag>
                      </div>
                      <div className="ak-op-sub">{item.servant.class_name}</div>
                      <div className="ak-op-en">{item.servant.original_name}</div>
                    </div>
                  </div>

                  <div className="ak-stats">
                    <div className="ak-stat">
                      <span className="ak-stat-label">满级 ATK</span>
                      <span className="ak-stat-value">{item.servant.atk_max}</span>
                    </div>
                    <div className="ak-stat">
                      <span className="ak-stat-label">满级 HP</span>
                      <span className="ak-stat-value">{item.servant.hp_max}</span>
                    </div>
                    <div className="ak-stat">
                      <span className="ak-stat-label">费用</span>
                      <span className="ak-stat-value">{item.servant.cost}</span>
                    </div>
                  </div>

                  {item.servant.skills.length ? (
                    <div className="ak-skills">
                      {item.servant.skills.map((s, si) => (
                        <div key={si} className="ak-skill-row">
                          <span className="ak-skill-idx">{si + 1}</span>
                          <div className="ak-skill-body">
                            <b>{s.name}</b>
                            <span className="ak-skill-desc">{s.detail}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {item.servant.noble_phantasms.length ? (
                    <div className="ak-talents">
                      <span className="ak-label">宝具</span>
                      {item.servant.noble_phantasms.map((np, ni) => (
                        <div key={ni} className="ak-talent">
                          <b>
                            {np.name}
                            {np.rank ? <Tag style={{ marginLeft: 6 }}>{np.rank}</Tag> : null}
                            {np.card ? <Tag>{np.card}</Tag> : null}
                          </b>
                          <span>{np.detail}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {item.servants?.length ? (
                <div className="ak-op-grid">
                  {item.servants.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className="ak-op-chip"
                      onClick={() => void query(s.name)}
                    >
                      {s.face ? <img src={s.face} alt={s.name} /> : null}
                      <span>{s.name}</span>
                      <span className="ak-op-chip-rarity">{s.rarity}★</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="mc-msg assistant">
            <div className="mc-avatar">迦</div>
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
          placeholder="输入从者名，例如「阿尔托莉雅」「吉尔伽美什」"
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void query()}>
          查询
        </Button>
      </div>
      <div className="mc-hint">数据来自 Atlas Academy（CN 服），头像为灵基再临一</div>
    </div>
  );
}
