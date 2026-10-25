import { api } from '../api';

export type ConfidenceState = 'confirmed' | 'candidate' | 'unknown';

export interface ServantRecord {
  record_id: string;
  name: string;
  class_name: string;
  rarity: number | null;
  level: number | null;
  max_level: number | null;
  np_level: number | null;
  skill_1: number | null;
  skill_2: number | null;
  skill_3: number | null;
  append_2: number | null;
  source: string;
  confidence: ConfidenceState;
  notes: string;
  updated_at: string;
}

export interface MaterialRecord {
  record_id: string;
  name: string;
  category: string;
  quantity: number;
  reserve_quantity: number;
  source: string;
  confidence: ConfidenceState;
  notes: string;
  updated_at: string;
}

export interface AccountSnapshotSummary {
  servants: number;
  materials: number;
  confirmed_servants: number;
  candidate_servants: number;
}

export async function listAccountServants(): Promise<ServantRecord[]> {
  const { data } = await api.get<ServantRecord[]>('/game-assistant/fgo/account/servants');
  return data;
}

export async function saveAccountServant(
  record: Partial<ServantRecord> & { name: string },
): Promise<ServantRecord> {
  const payload = {
    name: record.name,
    class_name: record.class_name || '',
    rarity: record.rarity ?? null,
    level: record.level ?? null,
    max_level: record.max_level ?? null,
    np_level: record.np_level ?? null,
    skill_1: record.skill_1 ?? null,
    skill_2: record.skill_2 ?? null,
    skill_3: record.skill_3 ?? null,
    append_2: record.append_2 ?? null,
    source: record.source || 'manual',
    confidence: record.confidence || 'confirmed',
    notes: record.notes || '',
  };
  if (record.record_id && !record.record_id.startsWith('draft-')) {
    const { data } = await api.put<ServantRecord>(
      `/game-assistant/fgo/account/servants/${record.record_id}`,
      payload,
    );
    return data;
  }
  const { data } = await api.post<ServantRecord>(
    '/game-assistant/fgo/account/servants',
    payload,
  );
  return data;
}

export async function deleteAccountServant(recordId: string): Promise<void> {
  await api.delete(`/game-assistant/fgo/account/servants/${recordId}`);
}

export async function listAccountMaterials(): Promise<MaterialRecord[]> {
  const { data } = await api.get<MaterialRecord[]>('/game-assistant/fgo/account/materials');
  return data;
}

export async function saveAccountMaterial(
  record: Partial<MaterialRecord> & { name: string },
): Promise<MaterialRecord> {
  const payload = {
    name: record.name,
    category: record.category || '',
    quantity: record.quantity ?? 0,
    reserve_quantity: record.reserve_quantity ?? 0,
    source: record.source || 'manual',
    confidence: record.confidence || 'confirmed',
    notes: record.notes || '',
  };
  if (record.record_id && !record.record_id.startsWith('draft-')) {
    const { data } = await api.put<MaterialRecord>(
      `/game-assistant/fgo/account/materials/${record.record_id}`,
      payload,
    );
    return data;
  }
  const { data } = await api.post<MaterialRecord>(
    '/game-assistant/fgo/account/materials',
    payload,
  );
  return data;
}

export async function deleteAccountMaterial(recordId: string): Promise<void> {
  await api.delete(`/game-assistant/fgo/account/materials/${recordId}`);
}

export async function loadAccountSummary(): Promise<AccountSnapshotSummary> {
  const { data } = await api.get<AccountSnapshotSummary>('/game-assistant/fgo/account/summary');
  return data;
}
export interface CraftEssenceRecord {
  record_id: string;
  name: string;
  rarity: number;
  level: number;
  max_level: number;
  limit_break: number;
  attack: number;
  hp: number;
  cost: number;
  effects: Array<Record<string, unknown>>;
  source: string;
  confidence: ConfidenceState;
  notes: string;
  updated_at: string;
}

export interface MysticCodeSkill {
  skill_id: string;
  name: string;
  level: number;
  cooldown: number;
  effects: Array<Record<string, unknown>>;
}

export interface MysticCodeRecord {
  record_id: string;
  name: string;
  level: number;
  skills: MysticCodeSkill[];
  source: string;
  confidence: ConfidenceState;
  notes: string;
  updated_at: string;
}

export interface SupportPreferenceRecord {
  record_id: string;
  name: string;
  class_name: string;
  np_level: number | null;
  skill_1: number | null;
  skill_2: number | null;
  skill_3: number | null;
  append_2: number | null;
  craft_essence_name: string;
  friend_only: boolean;
  source: string;
  confidence: ConfidenceState;
  notes: string;
  updated_at: string;
}

export async function listCraftEssences(): Promise<CraftEssenceRecord[]> {
  const { data } = await api.get<CraftEssenceRecord[]>('/game-assistant/fgo/account/craft-essences');
  return data;
}

export async function saveCraftEssence(record: Partial<CraftEssenceRecord> & { name: string }): Promise<CraftEssenceRecord> {
  const payload = {
    name: record.name,
    rarity: record.rarity ?? 0,
    level: record.level ?? 1,
    max_level: record.max_level ?? 1,
    limit_break: record.limit_break ?? 0,
    attack: record.attack ?? 0,
    hp: record.hp ?? 0,
    cost: record.cost ?? 0,
    effects: record.effects || [],
    source: record.source || 'manual',
    confidence: record.confidence || 'confirmed',
    notes: record.notes || '',
  };
  if (record.record_id && !record.record_id.startsWith('draft-')) {
    const { data } = await api.put<CraftEssenceRecord>('/game-assistant/fgo/account/craft-essences/' + record.record_id, payload);
    return data;
  }
  const { data } = await api.post<CraftEssenceRecord>('/game-assistant/fgo/account/craft-essences', payload);
  return data;
}

export async function deleteCraftEssence(recordId: string): Promise<void> {
  await api.delete('/game-assistant/fgo/account/craft-essences/' + recordId);
}

export async function listMysticCodes(): Promise<MysticCodeRecord[]> {
  const { data } = await api.get<MysticCodeRecord[]>('/game-assistant/fgo/account/mystic-codes');
  return data;
}

export async function saveMysticCode(record: Partial<MysticCodeRecord> & { name: string }): Promise<MysticCodeRecord> {
  const payload = {
    name: record.name,
    level: record.level ?? 1,
    skills: record.skills || [],
    source: record.source || 'manual',
    confidence: record.confidence || 'confirmed',
    notes: record.notes || '',
  };
  if (record.record_id && !record.record_id.startsWith('draft-')) {
    const { data } = await api.put<MysticCodeRecord>('/game-assistant/fgo/account/mystic-codes/' + record.record_id, payload);
    return data;
  }
  const { data } = await api.post<MysticCodeRecord>('/game-assistant/fgo/account/mystic-codes', payload);
  return data;
}

export async function deleteMysticCode(recordId: string): Promise<void> {
  await api.delete('/game-assistant/fgo/account/mystic-codes/' + recordId);
}

export async function listSupportPreferences(): Promise<SupportPreferenceRecord[]> {
  const { data } = await api.get<SupportPreferenceRecord[]>('/game-assistant/fgo/account/support-preferences');
  return data;
}

export async function saveSupportPreference(record: Partial<SupportPreferenceRecord> & { name: string }): Promise<SupportPreferenceRecord> {
  const payload = {
    name: record.name,
    class_name: record.class_name || '',
    np_level: record.np_level ?? null,
    skill_1: record.skill_1 ?? null,
    skill_2: record.skill_2 ?? null,
    skill_3: record.skill_3 ?? null,
    append_2: record.append_2 ?? null,
    craft_essence_name: record.craft_essence_name || '',
    friend_only: record.friend_only ?? false,
    source: record.source || 'manual',
    confidence: record.confidence || 'confirmed',
    notes: record.notes || '',
  };
  if (record.record_id && !record.record_id.startsWith('draft-')) {
    const { data } = await api.put<SupportPreferenceRecord>('/game-assistant/fgo/account/support-preferences/' + record.record_id, payload);
    return data;
  }
  const { data } = await api.post<SupportPreferenceRecord>('/game-assistant/fgo/account/support-preferences', payload);
  return data;
}

export async function deleteSupportPreference(recordId: string): Promise<void> {
  await api.delete('/game-assistant/fgo/account/support-preferences/' + recordId);
}
