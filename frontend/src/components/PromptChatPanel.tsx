import { useState, useRef, useEffect } from 'react';
import { Button, Input, Space, Tag, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { uiStore } from '../stores/ui';
import { api } from '../api';

type Message = {
  role: 'user' | 'assistant';
  content: string;
  prompt?: string;
  promptTranslation?: string;
  tags?: { tag: string; category: string; post_count: number; exists: boolean }[];
  toolCalls?: { tool: string; args: Record<string, unknown>; result: Record<string, unknown> }[];
  elapsedMs?: number;
  marks?: Record<string, number>;
};

const EXAMPLES = [
  '配一个企业的提示词',
  '伊蕾娜 魔女装',
  '给我配个办公室风格的角色',
  '查一下 grey_hair 这个 tag',
];

export default function PromptChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || loading) return;
    setInput('');
    const nextMessages: Message[] = [...messages, { role: 'user', content }];
    setMessages(nextMessages);
    setLoading(true);
    try {
      const response = await api.post('/prompt-agent/chat', {
        messages: nextMessages.map((item) => ({ role: item.role, content: item.content })),
      });
      const data = response.data;
      const assistantMessage: Message = {
        role: 'assistant',
        content: String(data.reply ?? ''),
        prompt: data.prompt || undefined,
        promptTranslation: data.prompt_translation || undefined,
        tags: data.tags || [],
        toolCalls: data.tool_calls || [],
        elapsedMs: Number(data.elapsed_ms) || 0,
        marks: data.marks || {},
      };
      setMessages([...nextMessages, assistantMessage]);

      // 翻译异步补齐，不阻塞主回复
      if (assistantMessage.prompt) {
        const promptText = assistantMessage.prompt;
        void api
          .post('/prompt-agent/translate', { text: promptText })
          .then((translated) => {
            const value = String(translated.data?.translation ?? '').trim();
            if (!value) return;
            setMessages((prev) =>
              prev.map((item) =>
                item.prompt === promptText ? { ...item, promptTranslation: value } : item,
              ),
            );
          })
          .catch(() => {
            /* 翻译失败不影响主流程 */
          });
      }
    } catch (error) {
      message.error(`请求失败：${error instanceof Error ? error.message : String(error)}`);
      setMessages(nextMessages);
    } finally {
      setLoading(false);
    }
  };

  const applyToDraw = (prompt?: string) => {
    if (!prompt) return;
    window.localStorage.setItem('prompt-agent:last-prompt', prompt);
    message.success('已保存，去绘画页点「应用提示词」即可填入');
  };

  return (
    <div className="prompt-chat">
      <div className="prompt-chat-head">
        <div>
          <h2>提示词 Agent</h2>
          <p>说角色名或描述，我会查库并拼好提示词</p>
        </div>
        <Space>
          <Button size="small" onClick={() => setMessages([])} disabled={!messages.length || loading}>
            清空对话
          </Button>
        </Space>
      </div>

      <div className="prompt-chat-list" ref={listRef}>
        {messages.length === 0 ? (
          <div className="prompt-chat-empty">
            <p>试着这样说：</p>
            <Space wrap>
              {EXAMPLES.map((item) => (
                <Tag key={item} className="prompt-chat-example" onClick={() => void send(item)}>
                  {item}
                </Tag>
              ))}
            </Space>
          </div>
        ) : null}

        {messages.map((item, index) => (
          <div key={index} className={`prompt-msg ${item.role}`}>
            <div className="prompt-msg-avatar">{item.role === 'user' ? '你' : '渔'}</div>
            <div className="prompt-msg-body">
              <div className="prompt-msg-text">{item.content}</div>

              {item.toolCalls?.length ? (
                <div className="prompt-tool-calls">
                  {item.toolCalls.map((call, callIndex) => (
                    <div key={callIndex} className="prompt-tool-call">
                      <b>{call.tool}</b>
                      <span>({JSON.stringify(call.args)})</span>
                    </div>
                  ))}
                </div>
              ) : null}

              {item.role === 'assistant' && item.elapsedMs ? (
                <div className="prompt-elapsed" title={Object.entries(item.marks || {})
                  .map(([key, value]) => `${key}: ${value}ms`)
                  .join('\n')}>
                  查库 {(item.elapsedMs / 1000).toFixed(2)}s
                  {item.prompt && !item.promptTranslation ? ' · 翻译中…' : ''}
                </div>
              ) : null}

              {item.prompt ? (
                <div className="prompt-result">
                  <div className="prompt-result-row">
                    <span>提示词</span>
                    <Button size="small" type="link" onClick={() => void navigator.clipboard.writeText(item.prompt ?? '')}>
                      复制
                    </Button>
                  </div>
                  <code>{item.prompt}</code>
                  {item.promptTranslation ? (
                    <>
                      <div className="prompt-result-row" style={{ marginTop: 6 }}>
                        <span>翻译</span>
                      </div>
                      <code className="prompt-translation">{item.promptTranslation}</code>
                    </>
                  ) : null}
                  {item.tags?.length ? (
                    <div className="prompt-tag-list">
                      {item.tags.map((tag) => (
                        <Tag
                          key={tag.tag}
                          color={tag.exists ? 'blue' : 'red'}
                          title={tag.exists ? `${tag.category} · ${tag.post_count} 帖` : '库中不存在'}
                        >
                          {tag.tag}
                        </Tag>
                      ))}
                    </div>
                  ) : null}
                  <Space style={{ marginTop: 8 }}>
                    <Button size="small" type="primary" onClick={() => applyToDraw(item.prompt)}>
                      应用到绘画页
                    </Button>
                    <Button size="small" onClick={() => void navigator.clipboard.writeText(item.prompt ?? '')}>
                      复制提示词
                    </Button>
                  </Space>
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="prompt-msg assistant">
            <div className="prompt-msg-avatar">渔</div>
            <div className="prompt-msg-body">
              <div className="prompt-msg-text prompt-thinking">正在查库…</div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="prompt-chat-composer">
        <Input.TextArea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
          placeholder="说角色名或描述，例如「企业 办公室风格」"
          autoSize={{ minRows: 1, maxRows: 4 }}
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void send()}>
          发送
        </Button>
      </div>
      <div className="prompt-chat-hint">
        提示：说角色名会自动查外貌与服装；天气、股价这类实时信息我拿不到，会直接说明。
      </div>
    </div>
  );
}
