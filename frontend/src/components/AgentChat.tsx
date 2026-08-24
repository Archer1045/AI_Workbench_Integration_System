// 招聘 Agent 对话工作区
import { Button, Collapse, Input, Space, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { chatStore, sendChat, type ChatMessage } from '../stores/chat';

const quickPrompts = ['介绍一下工作', '薪资多少', '入职有什么要求', '朝阳区有哪些站点'];

export default function AgentChat() {
  const { messages, sending } = chatStore;
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  // 新消息自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    void sendChat(input);
    setInput('');
  };

  return (
    <div className="panel-box chat-box">
      <div className="messages">
        {messages.length === 0 && (
          <div className="bubble agent">你好，我是骑手招聘助手。可以问我薪资待遇、入职要求、站点位置。</div>
        )}
        {messages.map((msg: ChatMessage, index: number) => (
          <div key={index} className={msg.role === 'user' ? 'bubble user' : 'bubble agent'}>
            {msg.thinking ? (
              <Collapse
                ghost
                size="small"
                items={[{ key: 'thinking', label: '思考过程', children: <div className="thinking-text">{msg.thinking}</div> }]}
              />
            ) : null}
            <div>{msg.content}</div>
            {msg.source ? (
              <Tag color="blue">{msg.source === 'llm' ? '大模型回答' : '知识库检索回答'}</Tag>
            ) : null}
          </div>
        ))}
        {sending && <div className="bubble agent">正在输入…</div>}
        <div ref={bottomRef} />
      </div>
      <Space wrap className="quick">
        {quickPrompts.map((prompt) => (
          <Button key={prompt} size="small" onClick={() => void sendChat(prompt)}>
            {prompt}
          </Button>
        ))}
      </Space>
      <div className="composer">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={handleSend}
          placeholder="输入你的问题..."
        />
        <Button type="primary" onClick={handleSend} loading={sending}>
          发送
        </Button>
      </div>
    </div>
  );
}
