// 招聘 Agent 对话工作区
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Collapse, Input, List, Popconfirm, Space, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';
import {
  chatStore,
  deleteChatSession,
  loadChatSessions,
  sendChat,
  switchChatSession,
  type ChatMessage,
} from '../stores/chat';

const quickPrompts = ['介绍一下工作', '薪资多少', '入职有什么要求', '朝阳区有哪些站点'];

export default function AgentChat() {
  const { messages, sending, sessions, sessionId } = chatStore;
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadChatSessions();
  }, []);

  // 新消息自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    void sendChat(input);
    setInput('');
  };

  const handleNewSession = () => {
    chatStore.sessionId = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`;
    chatStore.messages = [];
  };

  return (
    <div className="agent-chat-layout">
      <div className="agent-session-side panel-box">
        <div className="train-section-title">会话</div>
        <Button size="small" block icon={<PlusOutlined />} onClick={handleNewSession}>
          新会话
        </Button>
        <List
          size="small"
          dataSource={sessions}
          renderItem={(item) => (
            <List.Item
              onClick={() => void switchChatSession(item.session_id)}
              style={{ cursor: 'pointer' }}
            >
              <span style={{ color: sessionId === item.session_id ? '#2563eb' : undefined }}>
                {item.last_message || '新会话'}
              </span>
              <Popconfirm title="确认删除该会话？" onConfirm={() => void deleteChatSession(item.session_id)}>
                <Button
                  size="small"
                  type="link"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()}
                />
              </Popconfirm>
            </List.Item>
          )}
        />
      </div>
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
    </div>
  );
}
