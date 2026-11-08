import { useEffect, useRef, useState } from 'react';
import { Button, Input, Tag, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';

type HsrSkill = {
  name: string;
  type: string;
  effect: string;
  simple_desc: string;
  desc: string;
};

type HsrRank = {
  index: number;
  name: string;
  desc: string;
};

type HsrMaterial = {
  promotion: number;
  name: string;
  amount: number;
};

type HsrCharacter = {
  id: string;
  name: string;
  rarity: number;
  path: string;
  element: string;
  icon: string;
  stats: {
    atk: number | null;
    hp: number | null;
    def: number | null;
    spd: number | null;
  };
  skills: HsrSkill[];
  ranks: HsrRank[];
  materials: HsrMaterial[];
};

type HsrBrief = {
  id: string;
  name: string;
  path: string;
  element: string;
  rarity: number;
  icon: string;
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  character?: HsrCharacter;
  characters?: HsrBrief[];
  listLabel?: string;
};

const EXAMPLES = ['三月七', '希儿', '姬子', '布洛妮娅'];

export default function HsrPanel() {
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
      const resp = await fetch('/api/hsr/chat/stream', {
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
              if (evt.character) patchLast({ character: evt.character });
              if (evt.characters) patchLast({ characters: evt.characters, listLabel: evt.list_label });
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
          <h2>崩坏：星穹铁道助手</h2>
          <p>查角色属性、技能、星魂、晋阶材料，共 98 名角色</p>
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
            <div className="mc-avatar">{item.role === 'user' ? '你' : '星'}</div>
            <div className="mc-body">
              <div className="mc-text">{item.content}</div>

              {item.character ? (
                <div className="ak-op">
                  <div className="ak-op-head">
                    {item.character.icon ? (
                      <img className="ak-avatar" src={item.character.icon} alt={item.character.name} />
                    ) : (
                      <div className="ak-avatar ak-avatar-empty" />
                    )}
                    <div className="ak-op-info">
                      <div className="ak-op-name">
                        {item.character.name}
                        <Tag color={item.character.rarity >= 5 ? 'gold' : 'purple'}>
                          {item.character.rarity} 星
                        </Tag>
                      </div>
                      <div className="ak-op-sub">
                        {item.character.path} · {item.character.element}
                      </div>
                    </div>
                  </div>

                  <div className="ak-stats">
                    {[
                      ['攻击', item.character.stats.atk],
                      ['生命', item.character.stats.hp],
                      ['防御', item.character.stats.def],
                      ['速度', item.character.stats.spd],
                    ].map(([label, value]) =>
                      value !== null && value !== undefined ? (
                        <div key={String(label)} className="ak-stat">
                          <span className="ak-stat-label">{label}</span>
                          <span className="ak-stat-value">{String(value)}</span>
                        </div>
                      ) : null,
                    )}
                  </div>

                  {item.character.skills.length ? (
                    <div className="ak-skills">
                      {item.character.skills
                        .filter((s) => s.name)
                        .map((s, si) => (
                          <div key={si} className="ak-skill-row">
                            <span className="ak-skill-idx">{si + 1}</span>
                            <div className="ak-skill-body">
                              <b>
                                {s.name}
                                {s.type ? <Tag style={{ marginLeft: 6 }}>{s.type}</Tag> : null}
                              </b>
                              <span className="ak-skill-desc">{s.simple_desc}</span>
                            </div>
                          </div>
                        ))}
                    </div>
                  ) : null}

                  {item.character.ranks.length ? (
                    <div className="ak-talents">
                      <span className="ak-label">星魂</span>
                      {item.character.ranks.map((r) => (
                        <div key={r.index} className="ak-talent">
                          <b>
                            {r.index}. {r.name}
                          </b>
                          <span>{r.desc}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {item.characters?.length ? (
                <div className="ak-op-grid">
                  {item.characters.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className="ak-op-chip"
                      onClick={() => void query(c.name)}
                    >
                      {c.icon ? <img src={c.icon} alt={c.name} /> : null}
                      <span>{c.name}</span>
                      <span className="ak-op-chip-rarity">{c.rarity}★</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="mc-msg assistant">
            <div className="mc-avatar">星</div>
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
          placeholder="输入角色名，例如「三月七」「希儿」"
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void query()}>
          查询
        </Button>
      </div>
      <div className="mc-hint">数据来自 StarRailRes（中文索引）</div>
    </div>
  );
}
