import { useEffect, useRef, useState } from 'react';
import { Button, Input, Tag, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';

type Candidate = {
  capability_id: string;
  display_name: string;
  confidence: number;
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  capability?: string;
  capabilityName?: string;
  candidates?: Candidate[];
  needsClarify?: boolean;
};

const EXAMPLES = [
  '钻石剑怎么合成',
  '银灰的天赋是什么',
  '阿尔托莉雅的技能',
  '三月七的技能',
  '企业的属性',
  '达妮娅的瞳色是什么',
];

const CAPABILITY_COLORS: Record<string, string> = {
  'game:minecraft': 'green',
  'game:arknights': 'blue',
  'game:fgo': 'gold',
  'game:hsr': 'purple',
  'game:azur': 'geekblue',
  prompt: 'cyan',
};

export default function AgentPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const query = async (text?: string, forcedCapability?: string) => {
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
      const resp = await fetch('/api/agent/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, capability_id: forcedCapability || '' }),
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
              patchLast({
                capability: evt.capability_id || undefined,
                capabilityName: evt.display_name || undefined,
                needsClarify: evt.needs_clarify || false,
                candidates: evt.candidates || undefined,
              });
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
          <h2>总助手</h2>
          <p>一个入口，自动识别游戏和意图 · 支持我的世界 / 明日方舟 / FGO / 星穹铁道 / 提示词</p>
        </div>
        <Button size="small" onClick={() => setMessages([])} disabled={!messages.length}>
          清空
        </Button>
      </div>

      <div className="mc-list" ref={listRef}>
        {messages.length === 0 ? (
          <div className="mc-empty">
            <p>试试这些（不用说明是哪个游戏）：</p>
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
            <div className="mc-avatar">{item.role === 'user' ? '你' : '总'}</div>
            <div className="mc-body">
              {item.role === 'assistant' && item.capabilityName ? (
                <div style={{ marginBottom: 6 }}>
                  <Tag color={CAPABILITY_COLORS[item.capability || ''] || 'default'}>
                    {item.capabilityName}
                  </Tag>
                </div>
              ) : null}
              <div className="mc-text">{item.content}</div>

              {item.candidates?.length ? (
                <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {item.candidates.map((c) => (
                    <Button
                      key={c.capability_id}
                      size="small"
                      onClick={() => {
                        const lastUser = [...messages]
                          .slice(0, index)
                          .reverse()
                          .find((m) => m.role === 'user');
                        if (lastUser) {
                          void query(lastUser.content, c.capability_id);
                        }
                      }}
                    >
                      查「{c.display_name}」
                    </Button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="mc-msg assistant">
            <div className="mc-avatar">总</div>
            <div className="mc-body">
              <div className="mc-text">正在识别…</div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="mc-composer">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={() => void query()}
          placeholder="问什么都行，例如「钻石剑怎么合成」「银灰的天赋」"
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void query()}>
          提问
        </Button>
      </div>
      <div className="mc-hint">自动路由到对应游戏知识包，不需要指定游戏</div>
    </div>
  );
}
