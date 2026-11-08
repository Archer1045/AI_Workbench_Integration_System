import { useEffect, useRef, useState } from 'react';
import { Button, Input, Modal, Space, Tag, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { api } from '../api';
import McTimeline from './McTimeline';
import MermaidDiagram from './MermaidDiagram';

type RecipeRow = (string | null)[];

type Recipe = {
  version: string;
  type: string;
  shape: RecipeRow[] | null;
  ingredients: (string | null)[] | null;
  result_count: number;
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  kind?: 'text' | 'entity' | 'recipe' | 'diff' | 'clarify';
  entity?: {
    id: string;
    name_zh: string | null;
    name_en: string;
    icon_url: string | null;
    first_version: string | null;
    last_version: string | null;
    versions: string[];
  };
  recipes?: Recipe[];
  materialIcons?: Record<string, string>;
  diff?: { from: string; to: string; count: number; items: any[] };
  diagram?: string;
  candidates?: {
    id: string;
    name_zh: string | null;
    name_en: string;
    type: string;
    icon_url: string | null;
  }[];
};

const EXAMPLES = ['钻石剑', '下界合金锭', '工作台', '幽匿'];

/** 3x3 合成格 */
function CraftGrid({ shape, icons }: { shape: RecipeRow[]; icons: Record<string, string> }) {
  const rows = 3;
  const cols = Math.max(3, ...shape.map((r) => r.length));
  const cells: (string | null)[][] = [];
  for (let r = 0; r < rows; r++) {
    const row: (string | null)[] = [];
    for (let c = 0; c < cols; c++) {
      row.push(shape[r]?.[c] ?? null);
    }
    cells.push(row);
  }
  return (
    <div className="mc-grid" style={{ ['--mc-cols' as string]: String(cols) }}>
      {cells.flat().map((mat, idx) => (
        <div key={idx} className={`mc-cell ${mat ? 'filled' : ''}`}>
          {mat && icons[mat] ? <img src={icons[mat]} alt={mat} title={mat} /> : null}
        </div>
      ))}
    </div>
  );
}

export default function McPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState('1.21');
  const [showTimeline, setShowTimeline] = useState(false);
  const [planGoal, setPlanGoal] = useState('');
  const [planOpen, setPlanOpen] = useState(false);
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

    // 先占一条空消息，随后逐步填充
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
      const resp = await fetch('/api/mc/chat/stream', {
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
              const entity = evt.entity
                ? {
                    id: evt.entity.id,
                    name_zh: evt.entity.name_zh,
                    name_en: evt.entity.name_en,
                    icon_url: evt.entity.icon_url,
                    first_version: evt.entity.first_version,
                    last_version: null,
                    versions: [] as string[],
                  }
                : undefined;

              patchLast({
                kind: evt.candidates?.length
                  ? 'clarify'
                  : evt.diff
                    ? 'diff'
                    : evt.recipes?.length
                      ? 'recipe'
                      : 'text',
                entity,
                recipes: evt.recipes || [],
                materialIcons: evt.material_icons || {},
                candidates: evt.candidates || [],
                diff: evt.diff
                  ? { from: evt.diff.from, to: evt.diff.to, count: evt.diff.total, items: evt.diff.items }
                  : undefined,
              });

              if (entity) {
                api
                  .get(`/mc/entity/${encodeURIComponent(entity.id)}`)
                  .then((detail) =>
                    patchLast({
                      entity: {
                        ...entity,
                        versions: detail.data.versions || [],
                        last_version: detail.data.last_version,
                      },
                    }),
                  )
                  .catch(() => undefined);
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

  const generatePlan = async () => {
    const goal = planGoal.trim();
    if (!goal || loading) return;
    setPlanOpen(false);
    setMessages((prev) => [...prev, { role: 'user', content: `规划：${goal}` }]);
    setLoading(true);
    try {
      const r = await api.post('/mc/plan', { goal });
      const d = r.data;
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: d.text || '已生成规划图。',
          kind: 'text',
          diagram: d.diagram || undefined,
        },
      ]);
    } catch (err) {
      message.error(`生成规划图失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
      setPlanGoal('');
    }
  };

  const loadDiff = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const r = await api.get('/mc/version-diff', {
        params: { from: '1.7.10', to: '1.21', limit: 20 },
      });
      const d = r.data;
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `1.7.10 → 1.21 共新增 ${d.added_count} 个物品/方块，先看前 ${d.added.length} 个：`,
          kind: 'diff',
          diff: { from: d.from, to: d.to, count: d.added_count, items: d.added },
        },
      ]);
    } catch (err) {
      message.error('查询版本差异失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mc-chat">
      <div className="mc-head">
        <div>
          <h2>我的世界助手</h2>
          <p>查物品、方块、合成表，支持 1.7.10 → 1.21 版本对比</p>
        </div>
        <Space>
          <Tag color="green">当前 {version}</Tag>
          <Button size="small" onClick={() => setPlanOpen(true)}>
            发育路线
          </Button>
          <Button size="small" onClick={() => setShowTimeline(true)}>
            版本时间线
          </Button>
          <Button size="small" onClick={() => void loadDiff()}>
            版本跨度
          </Button>
          <Button size="small" onClick={() => setMessages([])} disabled={!messages.length}>
            清空
          </Button>
        </Space>
      </div>

      <Modal
        title="生成发育路线"
        open={planOpen}
        onCancel={() => setPlanOpen(false)}
        onOk={() => void generatePlan()}
        okText="生成"
        cancelText="取消"
        width={480}
      >
        <p className="mc-plan-tip">说明你想规划的目标，例如「生存路线」「钻石流程」「下界准备」。</p>
        <Input
          value={planGoal}
          onChange={(e) => setPlanGoal(e.target.value)}
          onPressEnter={() => void generatePlan()}
          placeholder="例如：从零到击败末影龙"
        />
      </Modal>

      {showTimeline ? <McTimeline onBack={() => setShowTimeline(false)} /> : null}

      {showTimeline ? null : (
      <>
      <div className="mc-list" ref={listRef}>
        {messages.length === 0 ? (
          <div className="mc-empty">
            <p>试试这些：</p>
            <Space wrap>
              {EXAMPLES.map((x) => (
                <Tag key={x} className="mc-example" onClick={() => void query(x)}>
                  {x}
                </Tag>
              ))}
            </Space>
          </div>
        ) : null}

        {messages.map((item, index) => (
          <div key={index} className={`mc-msg ${item.role} ${item.diagram ? 'has-diagram' : ''}`}>
            <div className="mc-avatar">{item.role === 'user' ? '你' : '麦'}</div>
            <div className="mc-body">
              <div className="mc-text">{item.content}</div>

              {item.entity ? (
                <div className="mc-entity">
                  {item.entity.icon_url ? (
                    <img
                      className="mc-entity-icon"
                      src={item.entity.icon_url}
                      alt={item.entity.name_zh || item.entity.id}
                    />
                  ) : null}
                  <div className="mc-entity-info">
                    <b>{item.entity.name_zh || item.entity.name_en}</b>
                    <span>{item.entity.name_en}</span>
                    {item.entity.versions.length ? (
                      <div className="mc-versions">
                        {item.entity.versions.map((v) => (
                          <Tag key={v} color={v === '1.21' ? 'blue' : 'default'}>
                            {v}
                          </Tag>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {item.candidates?.length ? (
                <div className="mc-candidates">
                  {item.candidates.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className="mc-candidate"
                      onClick={() => void query(c.name_zh || c.name_en)}
                    >
                      {c.icon_url ? <img src={c.icon_url} alt={c.name_zh || c.id} /> : null}
                      <span>{c.name_zh || c.name_en}</span>
                    </button>
                  ))}
                </div>
              ) : null}

              {item.recipes?.length ? (
                <div className="mc-recipes">
                  {item.recipes.slice(0, 3).map((rec, ri) => (
                    <div key={ri} className="mc-recipe">
                      <div className="mc-recipe-head">
                        <Tag>{rec.version}</Tag>
                        <span>{rec.type === 'shaped' ? '有序合成' : rec.type === 'shapeless' ? '无序合成' : rec.type}</span>
                        <span className="mc-result-count">×{rec.result_count}</span>
                      </div>
                      {rec.shape ? (
                        <CraftGrid shape={rec.shape} icons={item.materialIcons || {}} />
                      ) : rec.ingredients ? (
                        <div className="mc-ingredients">
                          {rec.ingredients
                            .filter(Boolean)
                            .map((mat, mi) => (
                              <div key={mi} className="mc-ingredient">
                                {mat && item.materialIcons?.[mat] ? (
                                  <img src={item.materialIcons[mat]} alt={mat} title={mat} />
                                ) : null}
                              </div>
                            ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}

              {item.diagram ? <MermaidDiagram code={item.diagram} /> : null}

              {item.diff ? (
                <div className="mc-diff">
                  {item.diff.items.map((x: any) => (
                    <div key={x.id} className="mc-diff-item">
                      {x.icon_url ? <img src={x.icon_url} alt={x.id} title={x.id} /> : <span className="mc-diff-noimg" />}
                      <span>{x.name_zh || x.id}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="mc-msg assistant">
            <div className="mc-avatar">麦</div>
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
          placeholder="输入物品/方块名，例如「钻石剑」「下界合金锭」"
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void query()}>
          查询
        </Button>
      </div>
      <div className="mc-hint">
        提示：图标来自 Minecraft Wiki，配方覆盖 1.7.10 ~ 1.21 六个版本
      </div>
      </>
      )}
    </div>
  );
}
