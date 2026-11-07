import type { PromptDocumentMode, PromptDocumentV1 } from './api';
import { normalizePromptDocument } from './promptDocument';

const HISTORY_KEY = 'rider-studio:draw-prompt-history-v1';

export interface DrawPromptVersion {
  id: string;
  createdAt: string;
  mode: PromptDocumentMode;
  prompt: string;
  document: PromptDocumentV1 | null;
}

export type DrawPromptHistory = Record<string, DrawPromptVersion[]>;

function normalizeVersion(raw: unknown): DrawPromptVersion | null {
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as Partial<DrawPromptVersion>;
  const id = String(data.id || '').trim();
  const createdAt = String(data.createdAt || '').trim();
  if (!id || !createdAt) return null;
  return {
    id,
    createdAt,
    mode: data.mode === 'legacy' ? 'legacy' : 'structured',
    prompt: String(data.prompt || ''),
    document:
      data.document && typeof data.document === 'object'
        ? normalizePromptDocument(data.document)
        : null,
  };
}

export function loadDrawPromptHistory(): DrawPromptHistory {
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).map(([groupId, raw]) => [
        groupId,
        (Array.isArray(raw) ? raw : [])
          .map(normalizeVersion)
          .filter((item): item is DrawPromptVersion => Boolean(item)),
      ]),
    );
  } catch {
    return {};
  }
}

export function saveDrawPromptHistory(history: DrawPromptHistory): void {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
}

function versionFingerprint(
  mode: PromptDocumentMode,
  prompt: string,
  document: PromptDocumentV1 | null,
): string {
  return JSON.stringify({
    mode,
    prompt: prompt.trim(),
    document: document ? normalizePromptDocument(document) : null,
  });
}

export function recordDrawPromptVersion(
  history: DrawPromptHistory,
  groupId: string,
  input: {
    mode: PromptDocumentMode;
    prompt: string;
    document: PromptDocumentV1 | null;
  },
  options: { limit?: number; now?: Date } = {},
): DrawPromptHistory {
  const document = input.document
    ? normalizePromptDocument(input.document)
    : null;
  const prompt = input.prompt.trim();
  if (!prompt && !document) return history;
  const versions = history[groupId] || [];
  const latest = versions[0];
  if (
    latest &&
    versionFingerprint(latest.mode, latest.prompt, latest.document) ===
      versionFingerprint(input.mode, prompt, document)
  ) {
    return history;
  }
  const now = options.now || new Date();
  const version: DrawPromptVersion = {
    id: `${now.getTime()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: now.toISOString(),
    mode: input.mode,
    prompt,
    document,
  };
  return {
    ...history,
    [groupId]: [version, ...versions].slice(0, Math.max(1, options.limit || 20)),
  };
}

export function diffPromptTags(
  before: string,
  after: string,
): { added: string[]; removed: string[] } {
  const parse = (value: string) =>
    value
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
  const beforeTags = new Set(parse(before));
  const afterTags = new Set(parse(after));
  return {
    added: [...afterTags].filter((tag) => !beforeTags.has(tag)),
    removed: [...beforeTags].filter((tag) => !afterTags.has(tag)),
  };
}
