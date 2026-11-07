// 情感陪伴状态：人设、会话、消息、记忆、设置
import { Modal } from 'antd';
import useStore from 'resso';
import {
  api,
  type CompanionMemory,
  type CompanionMessage,
  type CompanionPersona,
  type CompanionSession,
  type CompanionSettings,
} from '../api';

interface CompanionState {
  personas: CompanionPersona[];
  currentPersonaId: number;
  sessions: CompanionSession[];
  currentSessionId: number;
  messages: CompanionMessage[];
  memories: CompanionMemory[];
  settings: CompanionSettings | null;
  streaming: boolean;
  status: string;
  [key: string]: unknown;
}

export const companionStore = useStore<CompanionState>({
  personas: [],
  currentPersonaId: 0,
  sessions: [],
  currentSessionId: 0,
  messages: [],
  memories: [],
  settings: null,
  streaming: false,
  status: '',
});

export async function loadCompanionData(): Promise<void> {
  const [personasRes, settingsRes] = await Promise.all([
    api.get<{ items: CompanionPersona[] }>('/companion/personas'),
    api.get<CompanionSettings>('/companion/settings'),
  ]);
  companionStore.personas = personasRes.data.items || [];
  companionStore.settings = settingsRes.data;
  if (companionStore.personas.length > 0) {
    await switchCompanionPersona(companionStore.currentPersonaId || companionStore.personas[0].id);
  }
}

export async function switchCompanionPersona(personaId: number): Promise<void> {
  companionStore.currentPersonaId = personaId;
  companionStore.currentSessionId = 0;
  companionStore.messages = [];
  const res = await api.get<{ items: CompanionSession[] }>('/companion/sessions', {
    params: { persona_id: personaId },
  });
  companionStore.sessions = res.data.items || [];
  if (companionStore.sessions.length === 0) {
    await createCompanionSession();
  } else {
    await openCompanionSession(companionStore.sessions[0].id);
  }
  api
    .get<{ items: CompanionMemory[] }>('/companion/memories', { params: { persona_id: personaId } })
    .then((res2) => {
      companionStore.memories = res2.data.items || [];
    })
    .catch(() => undefined);
}

export async function createCompanionSession(): Promise<void> {
  const { data } = await api.post<{ ok: boolean; item: CompanionSession }>('/companion/sessions', {
    persona_id: companionStore.currentPersonaId,
    title: `会话 ${new Date().toLocaleDateString()}`,
  });
  companionStore.sessions = [data.item, ...companionStore.sessions];
  await openCompanionSession(data.item.id);
}

export async function openCompanionSession(sessionId: number): Promise<void> {
  companionStore.currentSessionId = sessionId;
  const res = await api.get<CompanionMessage[]>('/companion/messages', { params: { session_id: sessionId } });
  companionStore.messages = Array.isArray(res.data) ? res.data : [];
}

export async function deleteCompanionSession(sessionId: number): Promise<void> {
  await api.delete(`/companion/sessions/${sessionId}`);
  companionStore.sessions = companionStore.sessions.filter((item) => item.id !== sessionId);
  if (companionStore.currentSessionId === sessionId) {
    if (companionStore.sessions.length > 0) await openCompanionSession(companionStore.sessions[0].id);
    else await createCompanionSession();
  }
}

export async function sendCompanionMessage(message: string, imageBase64?: string): Promise<void> {
  if (!companionStore.currentSessionId || !companionStore.currentPersonaId || companionStore.streaming) return;
  const text = message.trim();
  const image = (imageBase64 || '').trim();
  if (!text && !image) return;
  companionStore.streaming = true;
  companionStore.status = '';
  const now = new Date().toISOString();
  const userMessage: CompanionMessage = {
    id: Date.now(),
    session_id: companionStore.currentSessionId,
    persona_id: companionStore.currentPersonaId,
    role: 'user',
    content: text || '[图片]',
    image_url: image || undefined,
    created_at: now,
  };
  const assistantMessage: CompanionMessage = {
    id: Date.now() + 1,
    session_id: companionStore.currentSessionId,
    persona_id: companionStore.currentPersonaId,
    role: 'assistant',
    content: '',
    created_at: now,
  };
  companionStore.messages = [...companionStore.messages, userMessage, assistantMessage];
  try {
    const response = await fetch('/api/companion/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        image_base64: image || undefined,
        session_id: companionStore.currentSessionId,
        persona_id: companionStore.currentPersonaId,
        client_time: new Date().toISOString(),
      }),
    });
    if (!response.ok || !response.body) {
      throw new Error(`请求失败：${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let errorMsg = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const raw = trimmed.slice(5).trim();
        if (!raw) continue;
        try {
          const event = JSON.parse(raw);
          if (event.kind === 'answer' || event.kind === 'thinking') {
            companionStore.messages = companionStore.messages.map((item, index) =>
              index === companionStore.messages.length - 1 ? { ...item, content: item.content + event.delta } : item,
            );
          } else if (event.kind === 'search_empty') {
            companionStore.status = event.delta || '未检索到相关内容';
          } else if (event.kind === 'error') {
            errorMsg = event.delta || '模型调用失败';
            companionStore.status = errorMsg;
            Modal.error({ title: '模型调用失败', content: errorMsg });
          } else if (event.kind === 'done') {
            companionStore.status = errorMsg || (event.emotion ? `情绪：${event.emotion}` : '');
          }
        } catch {
          // 忽略解析失败
        }
      }
    }
  } catch (e) {
    companionStore.messages = companionStore.messages.map((item, index) =>
      index === companionStore.messages.length - 1
        ? { ...item, content: `（发送失败：${(e as Error).message}）` }
        : item,
    );
  } finally {
    companionStore.streaming = false;
  }
}

export async function loadCompanionSettings(): Promise<void> {
  const { data } = await api.get<CompanionSettings>('/companion/settings');
  companionStore.settings = data;
}

export async function saveCompanionSettings(patch: Partial<CompanionSettings>): Promise<void> {
  const { data } = await api.put<CompanionSettings>('/companion/settings', patch);
  companionStore.settings = data;
}

export async function summarizeCompanion(): Promise<void> {
  await api.post('/companion/summarize', { persona_id: companionStore.currentPersonaId });
  const res = await api.get<{ items: CompanionMemory[] }>('/companion/memories', {
    params: { persona_id: companionStore.currentPersonaId },
  });
  companionStore.memories = res.data.items || [];
}

export async function deleteCompanionMemory(memoryId: number): Promise<void> {
  await api.delete(`/companion/memories/${memoryId}`);
  companionStore.memories = companionStore.memories.filter((item) => item.id !== memoryId);
}

export async function generateCompanionPersona(description: string): Promise<Record<string, unknown>> {
  const { data } = await api.post<{ item: Record<string, unknown> }>('/companion/personas/generate', { description });
  return data.item;
}
