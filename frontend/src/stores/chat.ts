// 招聘 Agent 对话状态与流式请求
import useStore from 'resso';
import { api } from '../api';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  source?: string;
}

export interface AgentSession {
  session_id: string;
  last_at: string;
  message_count: number;
  last_message?: string;
}

interface ChatState {
  messages: ChatMessage[];
  sessionId: string;
  sessions: AgentSession[];
  sending: boolean;
  [key: string]: unknown;
}

export const chatStore = useStore<ChatState>({
  messages: [],
  sessionId: '',
  sessions: [],
  sending: false,
});

// 更新最后一条消息
function updateLastMessage(updater: (msg: ChatMessage) => ChatMessage): void {
  const messages = [...chatStore.messages];
  const last = messages.length - 1;
  messages[last] = updater(messages[last]);
  chatStore.messages = messages;
}

// 发送消息并消费 SSE 流：先展示思考过程，再展示正式回答
export async function sendChat(text: string): Promise<void> {
  const message = text.trim();
  if (!message || chatStore.sending) return;
  chatStore.messages = [...chatStore.messages, { role: 'user', content: message }];
  chatStore.messages = [...chatStore.messages, { role: 'assistant', content: '' }];
  chatStore.sending = true;
  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: chatStore.sessionId }),
    });
    if (!response.ok || !response.body) throw new Error('stream unavailable');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let thinking = '';
    let content = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';
      for (const block of blocks) {
        const line = block.split('\n').find((item) => item.startsWith('data: '));
        if (!line) continue;
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(line.slice(6));
        } catch (e) {
          continue;
        }
        if (data.kind === 'thinking') {
          thinking += String(data.delta || '');
          updateLastMessage((msg) => ({ ...msg, thinking }));
        } else if (data.kind === 'answer') {
          content += String(data.delta || '');
          updateLastMessage((msg) => ({ ...msg, content }));
        } else if (data.kind === 'done') {
          chatStore.sessionId = String(data.session_id || chatStore.sessionId);
          updateLastMessage((msg) => ({ ...msg, source: String(data.source || '') }));
          void loadChatSessions();
        } else if (data.kind === 'error') {
          content = String(data.error || '出错了');
          updateLastMessage((msg) => ({ ...msg, content }));
        }
      }
    }
  } catch (e) {
    updateLastMessage((msg) => ({ ...msg, content: `请求失败：${(e as Error).message}` }));
  } finally {
    chatStore.sending = false;
  }
}

export async function loadChatSessions(): Promise<void> {
  try {
    const { data } = await api.get<{ items: AgentSession[] }>('/chat/sessions');
    chatStore.sessions = data.items || [];
  } catch {
    // 列表加载失败不影响当前对话
  }
}

export async function switchChatSession(sessionId: string): Promise<void> {
  chatStore.sessionId = sessionId;
  try {
    const { data } = await api.get<{ items: Record<string, unknown>[] }>('/chat/messages', {
      params: { session_id: sessionId },
    });
    chatStore.messages = (data.items || []).map((item) => ({
      role: item.sender === 'user' ? ('user' as const) : ('assistant' as const),
      content: String(item.content || ''),
      source: item.source ? String(item.source) : undefined,
    }));
  } catch {
    chatStore.messages = [];
  }
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await api.delete(`/chat/sessions/${sessionId}`);
  chatStore.sessions = chatStore.sessions.filter((item) => item.session_id !== sessionId);
  if (chatStore.sessionId === sessionId) {
    chatStore.sessionId = '';
    chatStore.messages = [];
  }
}
