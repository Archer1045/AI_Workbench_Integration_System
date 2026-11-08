import { useEffect, useRef, useState } from 'react';
import { Button, Input, Spin, Tag, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { api } from '../api';

type Operator = {
  id: string;
  name: string;
  name_en: string;
  rarity: number;
  profession: string;
  sub_profession: string;
  nation: string;
  position: string;
  tags: string[];
  description: string;
  usage: string;
  obtain: string;
  avatar: string | null;
  stats: {
    hp: number | null;
    atk: number | null;
    def: number | null;
    res: number | null;
    cost: number | null;
    block: number | null;
    atk_interval: number | null;
  };
  skills: { skill_id: string; skill_index: number }[];
  talents: { talent_index: number; name: string; description: string; unlock_phase: string }[];
};

type Skill = {
  id: string;
  name: string;
  sp_cost: number | null;
  init_sp: number | null;
  duration: number | null;
  description: string;
};

type OperatorBrief = {
  id: string;
  name: string;
  rarity: number;
  profession: string;
  avatar: string | null;
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  operator?: Operator;
  skills?: Skill[];
  focusSkill?: Skill;
  operators?: OperatorBrief[];
  listLabel?: string;
};

const EXAMPLES = ['银灰', '艾雅法拉', '能天使', '史尔特尔'];

const RARITY_COLOR: Record<number, string> = {
  1: 'default',
  2: 'default',
  3: 'blue',
  4: 'purple',
  5: 'gold',
  6: 'orange',
};

export default function AkPanel() {
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
    try {
      // 走对话接口：后端做意图路由 + 实体提取 + LLM 润色
      const r = await api.post('/ak/chat', { query: q });
      const d = r.data;

      // 对话接口返回的 operator 是精简版，需要补全详情
      let op: Operator | undefined;
      if (d.operator?.name) {
        try {
          const detail = await api.get(`/ak/operator/${encodeURIComponent(d.operator.name)}`);
          op = detail.data;
        } catch {
          /* 忽略 */
        }
      }

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: d.text || '没有找到相关内容。',
          operator: op,
          skills: d.skills || undefined,
          focusSkill: d.focus_skill || undefined,
          operators: d.operators || undefined,
          listLabel: d.list_label || undefined,
        },
      ]);
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
          <h2>明日方舟助手</h2>
          <p>查干员属性、技能、天赋，共 467 名干员</p>
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
            <div className="mc-avatar">{item.role === 'user' ? '你' : '舟'}</div>
            <div className="mc-body">
              <div className="mc-text">{item.content}</div>

              {item.operator ? (
                <div className="ak-op">
                  <div className="ak-op-head">
                    {item.operator.avatar ? (
                      <img
                        className="ak-avatar"
                        src={item.operator.avatar}
                        alt={item.operator.name}
                      />
                    ) : (
                      <div className="ak-avatar ak-avatar-empty" />
                    )}
                    <div className="ak-op-info">
                      <div className="ak-op-name">
                        {item.operator.name}
                        <Tag color={RARITY_COLOR[item.operator.rarity] || 'default'}>
                          {item.operator.rarity} 星
                        </Tag>
                      </div>
                      <div className="ak-op-sub">
                        {item.operator.profession} · {item.operator.position}
                        {item.operator.nation ? ` · ${item.operator.nation}` : ''}
                      </div>
                      <div className="ak-op-en">{item.operator.name_en}</div>
                    </div>
                  </div>

                  {item.operator.tags.length ? (
                    <div className="ak-tags">
                      {item.operator.tags.map((t) => (
                        <Tag key={t}>{t}</Tag>
                      ))}
                    </div>
                  ) : null}

                  {item.operator.description ? (
                    <div className="ak-section">
                      <span className="ak-label">特性</span>
                      <span>{item.operator.description}</span>
                    </div>
                  ) : null}

                  <div className="ak-stats">
                    {[
                      ['生命', item.operator.stats.hp],
                      ['攻击', item.operator.stats.atk],
                      ['防御', item.operator.stats.def],
                      ['法抗', item.operator.stats.res],
                      ['部署', item.operator.stats.cost],
                      ['阻挡', item.operator.stats.block],
                    ].map(([label, value]) =>
                      value !== null && value !== undefined ? (
                        <div key={String(label)} className="ak-stat">
                          <span className="ak-stat-label">{label}</span>
                          <span className="ak-stat-value">{String(value)}</span>
                        </div>
                      ) : null,
                    )}
                  </div>

                  {item.operator.talents.length ? (
                    <div className="ak-talents">
                      <span className="ak-label">天赋</span>
                      {item.operator.talents.map((t, ti) => (
                        <div key={ti} className="ak-talent">
                          <b>{t.name}</b>
                          <span>{t.description}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {item.focusSkill ? (
                <div className="ak-skill-focus">
                  <div className="ak-skill-name">{item.focusSkill.name}</div>
                  <div className="ak-skill-meta">
                    技力 {item.focusSkill.sp_cost ?? '-'} · 初始 {item.focusSkill.init_sp ?? '-'} · 持续{' '}
                    {item.focusSkill.duration ?? '-'} 秒
                  </div>
                  <div className="ak-skill-desc">{item.focusSkill.description}</div>
                </div>
              ) : null}

              {item.skills?.length && !item.focusSkill ? (
                <div className="ak-skills">
                  {item.skills.map((s, si) => (
                    <div key={si} className="ak-skill-row">
                      <span className="ak-skill-idx">{si + 1}</span>
                      <div className="ak-skill-body">
                        <b>{s.name}</b>
                        <span className="ak-skill-meta">
                          技力 {s.sp_cost ?? '-'} · 持续 {s.duration ?? '-'} 秒
                        </span>
                        <span className="ak-skill-desc">{s.description}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}

              {item.operators?.length ? (
                <div className="ak-op-grid">
                  {item.operators.map((o) => (
                    <button
                      key={o.id}
                      type="button"
                      className="ak-op-chip"
                      onClick={() => void query(o.name)}
                    >
                      {o.avatar ? <img src={o.avatar} alt={o.name} /> : null}
                      <span>{o.name}</span>
                      <span className="ak-op-chip-rarity">{o.rarity}星</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="mc-msg assistant">
            <div className="mc-avatar">舟</div>
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
          placeholder="输入干员名，例如「银灰」「能天使」"
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void query()}>
          查询
        </Button>
      </div>
      <div className="mc-hint">数据来自游戏数据仓库，头像来自 PRTS</div>
    </div>
  );
}
