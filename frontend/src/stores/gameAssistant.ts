import { api } from '../api';
import { runbookRequestErrorMessage } from '../runbookErrors';

export type GuideProvider = 'template' | 'local' | 'deepseek' | 'openai_compatible';

export interface SourceCitation {
  source_id: string;
  title: string;
  url: string;
  source_type: string;
  publisher: string;
  fetched_at: string;
  confidence: number;
  verification_status: string;
}

export interface EventPhase {
  phase_id: string;
  name: string;
  phase_type: string;
  opens_at: string | null;
  unlock_condition: string;
  summary: string;
  quest_ids: string[];
  source_ids: string[];
}

export interface QuestSummary {
  quest_id: string;
  name: string;
  type?: string;
  quest_type?: string;
  location: string;
  ap?: number;
  ap_cost?: number;
  level?: string;
  recommended_level?: string;
  unlock?: string;
  unlock_condition?: string;
  available_from?: string | null;
  repeatable: boolean;
  tags?: string[];
  source_ids?: string[];
}

export interface MechanicNote {
  title: string;
  detail: string;
  kind: string;
  source_ids: string[];
}

export interface EventBundle {
  event_id: string;
  revision: number;
  server: string;
  title: string;
  subtitle: string;
  starts_at: string;
  ends_at: string;
  exchange_ends_at?: string | null;
  participation_requirement: string;
  location: string;
  tags: string[];
  mechanics: MechanicNote[];
  phases: EventPhase[];
  quests: QuestSummary[];
  missions: Array<Record<string, unknown>>;
  shop_items: Array<Record<string, unknown>>;
  sources: SourceCitation[];
  observations: Array<Record<string, unknown>>;
}

export type EventStatus = 'running' | 'ended_shop_open' | 'closed';

/** 交换所倒计时。`state`：open（还开着）/ closed（已关闭）/ none（这个活动没有交换所）。 */
export interface EventShopState {
  ends_at: string | null;
  state: 'open' | 'closed' | 'none';
  days_left: number | null;
  /** 不足 24 小时：界面写「今天 HH:MM 截止」，不写「剩余 0 天」。 */
  ends_today: boolean;
}

export interface EventView {
  event: EventBundle;
  /** 活动生命周期：进行中 / 已结束但交换所还开 / 已完全关闭（后端算，前端只渲染）。 */
  event_status?: EventStatus;
  /** ready：事实包已发布；missing_bundle：日程已开始但资料尚未导入。 */
  data_status?: 'ready' | 'missing_bundle';
  schedule_event?: Record<string, unknown> | null;
  /** 副本（自由本）关闭的时刻，折叠区里标注用。 */
  quests_closed_at?: string | null;
  shop?: EventShopState;
  current_phase: EventPhase | null;
  next_phase: EventPhase | null;
  available_quests: QuestSummary[];
  upcoming_quests: QuestSummary[];
  server_time: string;
}

export interface ProviderStatus {
  provider: GuideProvider;
  available: boolean;
  model: string;
  detail: string;
}

export interface ProviderSettingsView {
  provider_id: 'deepseek' | 'openai_compatible' | 'ollama';
  label: string;
  base_url: string;
  model: string;
  api_key_configured: boolean;
  api_key_source: 'saved' | 'environment' | 'none';
  available: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_message: string;
}

export interface ProviderTestResult {
  provider_id: string;
  ok: boolean;
  message: string;
  tested_at: string;
}

export interface SourceRecord {
  source_id: string;
  url: string;
  final_url: string;
  source_type: string;
  title: string;
  publisher: string;
  fetched_at: string;
  fetched_via: 'url' | 'manual';
  content_type: string;
  http_status: number | null;
  content_hash: string;
  text_length: number;
  excerpt: string;
  text: string;
  images: string[];
  image_assets: SourceImageAsset[];
  warnings: string[];
  event_id: string | null;
  base_revision: number | null;
  extraction: SourceExtractionResult | null;
  published_revision: number | null;
}

export interface SourceDiscoverItem {
  title: string;
  url: string;
  summary: string;
  date: string | null;
  authority: number | null;
  site_name: string | null;
  source_type: string;
}

export interface SourceDiscoverResult {
  provider: string;
  cached: boolean;
  query: string;
  results: SourceDiscoverItem[];
  filtered_out: number;
}

export interface RevisionDiff {
  added: Record<string, number>;
  updated: Record<string, number>;
  conflicts: string[];
  summary: string;
}

export interface EventRevisionPatch {
  event: Record<string, unknown>;
  mechanics: Array<Record<string, unknown>>;
  bonus_servants: Array<Record<string, unknown>>;
  phases: Array<Record<string, unknown>>;
  quests: Array<Record<string, unknown>>;
  missions: Array<Record<string, unknown>>;
  shop_items: Array<Record<string, unknown>>;
  notes: string[];
  warnings: string[];
}

export interface CombatFoundation {
  status: string;
  contracts: string[];
  combat_profiles: number;
  team_plans: number;
  mock_profiles: number;
  simulator: {
    available: boolean;
    accuracy: string;
    supports: string[];
  };
}

export interface SourceExtractionResult {
  source_id: string;
  provider_used: string;
  model: string;
  patch: EventRevisionPatch;
  diff: RevisionDiff;
  warnings: string[];
  created_at: string;
}

export interface GuideSection {
  heading: string;
  summary: string;
  bullets: string[];
  citation_ids: string[];
}

export interface GuideDraft {
  title: string;
  summary: string;
  current_phase: string;
  sections: GuideSection[];
  warnings: string[];
  citation_ids: string[];
}

export interface PlanStep {
  step_id: string;
  phase_id: string | null;
  title: string;
  action: string;
  availability: 'current' | 'upcoming' | 'conditional' | 'final';
  condition: string;
  expected_cost: string;
  stop_condition: string;
  citation_ids: string[];
}

export interface PlanCandidate {
  title: string;
  objective: string;
  current_phase: string;
  steps: PlanStep[];
  stop_conditions: string[];
  warnings: string[];
  citation_ids: string[];
}

export interface GuideGenerationResult {
  generation_id: string;
  event_id: string;
  event_revision: number;
  provider_requested: GuideProvider;
  provider_used: GuideProvider;
  model: string;
  prompt_version: string;
  fallback_reason?: string | null;
  guide: GuideDraft;
  markdown: string;
  plan: PlanCandidate;
  warnings: string[];
  created_at: string;
}

export interface BootstrapResponse {
  event_view: EventView | null;
  event_data_status?: 'ready' | 'missing_bundle' | 'no_current_event';
  providers: ProviderStatus[];
  latest_generation: GuideGenerationResult | null;
  boundaries: {
    account_connected: boolean;
    executor_connected: boolean;
    plan_mode: string;
  };
}

export async function loadGameAssistantBootstrap(): Promise<BootstrapResponse> {
  const { data } = await api.get<BootstrapResponse>('/game-assistant/fgo/bootstrap');
  return data;
}

export async function generateFgoGuide(payload: {
  provider: GuideProvider;
  goal: string;
  event_id?: string;
  revision?: number;
}): Promise<GuideGenerationResult> {
  const { data } = await api.post<GuideGenerationResult>(
    '/game-assistant/fgo/guides/generate',
    payload,
  );
  return data;
}

export function questAp(quest: QuestSummary): number {
  return quest.ap ?? quest.ap_cost ?? 0;
}

export function questLevel(quest: QuestSummary): string {
  return quest.level ?? quest.recommended_level ?? '未标注';
}

export function questUnlock(quest: QuestSummary): string {
  return quest.unlock ?? quest.unlock_condition ?? '';
}
export async function listProviderSettings(): Promise<ProviderSettingsView[]> {
  const { data } = await api.get<ProviderSettingsView[]>('/game-assistant/fgo/settings/providers');
  return data;
}

export async function updateProviderSettings(
  providerId: ProviderSettingsView['provider_id'],
  payload: { base_url?: string; model?: string; api_key?: string; clear_api_key?: boolean },
): Promise<ProviderSettingsView> {
  const { data } = await api.put<ProviderSettingsView>(
    `/game-assistant/fgo/settings/providers/${providerId}`,
    payload,
  );
  return data;
}

export async function deleteProviderSettings(providerId: ProviderSettingsView['provider_id']): Promise<ProviderSettingsView> {
  const { data } = await api.delete<ProviderSettingsView>(
    `/game-assistant/fgo/settings/providers/${providerId}`,
  );
  return data;
}

export async function testProviderSettings(providerId: ProviderSettingsView['provider_id']): Promise<ProviderTestResult> {
  const { data } = await api.post<ProviderTestResult>(
    `/game-assistant/fgo/settings/providers/${providerId}/test`,
  );
  return data;
}

export async function listSources(limit = 50): Promise<SourceRecord[]> {
  const { data } = await api.get<SourceRecord[]>('/game-assistant/fgo/sources', { params: { limit } });
  return data;
}

export async function discoverSources(payload: {
  query: string;
  count?: number;
  days?: number;
}): Promise<SourceDiscoverResult> {
  const { data } = await api.post<SourceDiscoverResult>('/game-assistant/fgo/sources/discover', payload);
  return data;
}

export async function ingestDiscoveredSource(payload: {
  url: string;
  source_type: string;
  title?: string;
  event_id?: string;
  revision?: number;
}): Promise<SourceRecord> {
  const { data } = await api.post<SourceRecord>('/game-assistant/fgo/sources/discover/ingest', payload);
  return data;
}

export async function ingestSource(payload: {
  url?: string;
  text?: string;
  source_type: string;
  title?: string;
  publisher?: string;
  event_id?: string;
  revision?: number;
}): Promise<SourceRecord> {
  const { data } = await api.post<SourceRecord>('/game-assistant/fgo/sources/ingest', payload);
  return data;
}

export async function extractSource(sourceId: string, provider: GuideProvider): Promise<SourceExtractionResult> {
  const { data } = await api.post<SourceExtractionResult>(
    `/game-assistant/fgo/sources/${sourceId}/extract`,
    { provider },
  );
  return data;
}

export async function publishSource(sourceId: string, confirm: boolean): Promise<{ published: boolean; event_id: string; revision: number }> {
  const { data } = await api.post(`/game-assistant/fgo/sources/${sourceId}/publish`, { confirm });
  return data;
}

export async function loadCombatFoundation(): Promise<CombatFoundation> {
  const { data } = await api.get<CombatFoundation>('/game-assistant/fgo/3t/foundation');
  return data;
}

export interface CombatAssumptions {
  assume_required_craft_essences: boolean;
  craft_essence_confirmation_complete: boolean;
  mystic_codes_default_max_level: boolean;
  current_event_mystic_code_name: string;
  current_event_mystic_code_level: number | null;
  current_event_mystic_code_confirmed: boolean;
  notes: string;
}

export async function loadCombatAssumptions(): Promise<CombatAssumptions> {
  const { data } = await api.get<CombatAssumptions>('/game-assistant/fgo/3t/assumptions');
  return data;
}

export async function saveCombatAssumptions(payload: CombatAssumptions): Promise<CombatAssumptions> {
  const { data } = await api.put<CombatAssumptions>('/game-assistant/fgo/3t/assumptions', payload);
  return data;
}

export interface SourceImageAsset {
  image_id: string;
  url: string;
  local_path: string;
  mime_type: string;
  byte_size: number;
  sha256: string;
  status: 'pending' | 'downloaded' | 'failed';
  error: string;
  analysis_status: 'pending' | 'completed' | 'failed';
  analysis_text: string;
  analysis_facts: Array<Record<string, unknown>>;
  analysis_error: string;
}

export interface SourceImagePrepareResult {
  source_id: string;
  total: number;
  downloaded: number;
  failed: number;
  images: SourceImageAsset[];
}

export interface SourceImageAnalysisResult {
  source_id: string;
  model: string;
  completed: number;
  failed: number;
  combined_text: string;
  images: SourceImageAsset[];
}

export async function prepareSourceImages(sourceId: string): Promise<SourceImagePrepareResult> {
  const { data } = await api.post<SourceImagePrepareResult>('/game-assistant/fgo/sources/' + sourceId + '/images/prepare');
  return data;
}

export async function analyzeSourceImages(sourceId: string, model = ''): Promise<SourceImageAnalysisResult> {
  const { data } = await api.post<SourceImageAnalysisResult>('/game-assistant/fgo/sources/' + sourceId + '/images/analyze', { model });
  return data;
}

// --- 3T 关卡数据、推荐、预检与礼装确认 -----------------------------------

export interface CombatEnemyUnit {
  enemy_id: string;
  name: string;
  class_name: string;
  level: number;
  hp: number;
  count: number;
  notes: string[];
}

export interface CombatEnemyWave {
  wave_id: string;
  wave_index: number;
  units: CombatEnemyUnit[];
  notes: string[];
}

export interface CombatProfile {
  quest_id: string;
  event_id: string;
  quest_name: string;
  ap_cost: number;
  waves: CombatEnemyWave[];
  verified: boolean;
  mock: boolean;
  source_ids: string[];
  notes: string[];
}

export interface RecommendedServant {
  name: string;
  class_name: string;
  level: number | null;
  np_level: number | null;
  skills: number[];
  attack: number;
  attack_source: 'atlas' | 'class_rarity_median';
  role: 'main_dps' | 'support' | 'bond';
  damage_multiplier: number;
  np_multiplier: number;
  np_card: string;
  np_target_type: string;
  notes: string[];
}

export interface DamageGate {
  enemy_id: string;
  required_damage: number;
  expected_min_damage: number;
  expected_avg_damage: number;
  passed: boolean;
}

export interface SimulatedAction {
  action_id: string;
  order: number;
  turn: number;
  actor_slot: number;
  action_type: string;
  target_enemy_ids: string[];
  damage_min: number;
  damage_avg: number;
  damage_max: number;
  np_after: number;
}

export interface SimulatedTurn {
  turn: number;
  actions: SimulatedAction[];
  enemies_remaining: number;
  total_enemy_hp_remaining: number;
}

export interface SimulationResult {
  status: 'success' | 'failed' | 'invalid';
  cleared_by_turn: number | null;
  total_turns: number;
  total_damage_min: number;
  total_damage_avg: number;
  total_damage_max: number;
  turns: SimulatedTurn[];
  damage_gates: DamageGate[];
  errors: string[];
  warnings: string[];
}

export interface TeamPlanCombatant {
  actor_slot: number;
  name: string;
  class_name: string;
  attack: number;
  class_relation: string;
  np_multiplier: number;
}

export interface TeamPlanAction {
  action_id: string;
  order: number;
  turn: number;
  actor_slot: number;
  action_type: string;
  notes: string[];
}

export interface TeamPlan {
  plan_id: string;
  quest_id: string;
  title: string;
  combatants: TeamPlanCombatant[];
  actions: TeamPlanAction[];
  assumptions: string[];
  warnings: string[];
  source_ids: string[];
  confidence: number;
}

export interface RecommendationOption {
  option_id: string;
  title: string;
  confidence: number;
  required_servants: RecommendedServant[];
  bond_slots: number;
  assumed_craft_essences: string[];
  required_craft_essences: string[];
  plan: TeamPlan;
  simulation: SimulationResult;
  minimum_investment: string[];
  alternatives: string[];
  failure_conditions: string[];
  missing_data: string[];
  assumptions: string[];
}

export interface RecommendationResult {
  quest_id: string;
  quest_name: string;
  profile_mock: boolean;
  profile_verified: boolean;
  dominant_enemy_class: string;
  constraints: Record<string, unknown>;
  options: RecommendationOption[];
  notes: string[];
  generated_at: string;
}

export interface CraftEssenceConfirmation {
  plan_id: string;
  quest_id: string;
  required_essences: string[];
  available_essences: string[];
  confirmed: boolean;
  confirmed_by: string;
  notes: string;
  updated_at: string;
}

export interface PreflightCheck {
  check_id: string;
  label: string;
  status: 'ok' | 'warning' | 'blocked';
  detail: string;
  required_for_dry_run: boolean;
  required_for_execution: boolean;
}

export interface PreflightResult {
  status: 'ready_for_dry_run' | 'blocked' | 'ready_for_execution';
  quest_id: string;
  plan_id: string;
  simulation_status: 'success' | 'failed' | 'invalid';
  clears_by_turn: number | null;
  checks: PreflightCheck[];
  can_dry_run: boolean;
  can_execute: boolean;
  summary: string;
}

export async function listCombatProfiles(): Promise<CombatProfile[]> {
  const { data } = await api.get<CombatProfile[]>('/game-assistant/fgo/3t/combat-profiles');
  return data;
}

/** 从 Mooncell 关卡配置表导入一份战斗档案（落盘时 mock=false / verified=false，仍需人工确认）。 */
export interface CombatProfileImportPayload {
  quest_id: string;
  quest_name: string;
  heading_id: string;
  event_id?: string;
  url?: string;
  html?: string;
  source_ids?: string[];
  overwrite?: boolean;
}

export interface CombatProfileImportResult {
  profile: CombatProfile;
  warnings: string[];
  note: string;
}

export async function importCombatProfile(
  payload: CombatProfileImportPayload,
): Promise<CombatProfileImportResult> {
  const { data } = await api.post<CombatProfileImportResult>(
    '/game-assistant/fgo/3t/combat-profiles/import',
    payload,
  );
  return data;
}

export async function recommendTeam(
  questId: string,
  constraints?: {
    max_required_servants?: number;
    target_bond_slots?: number;
    include_friend_support?: boolean;
    exclude_servants?: string[];
    max_options?: number;
  },
): Promise<RecommendationResult> {
  const { data } = await api.post<RecommendationResult>('/game-assistant/fgo/3t/recommend', {
    quest_id: questId,
    ...(constraints ? { constraints } : {}),
  });
  return data;
}

export async function runExecutionPreflight(questId: string, planId: string): Promise<PreflightResult> {
  const { data } = await api.post<PreflightResult>('/game-assistant/fgo/3t/preflight', {
    quest_id: questId,
    plan_id: planId,
  });
  return data;
}

export async function loadCraftEssenceConfirmation(planId: string): Promise<CraftEssenceConfirmation | null> {
  try {
    const { data } = await api.get<CraftEssenceConfirmation>(
      `/game-assistant/fgo/3t/craft-essence-confirmation/${encodeURIComponent(planId)}`,
    );
    return data;
  } catch (error) {
    // 404 表示这个方案还没有确认记录，不是错误状态。
    const status = (error as { response?: { status?: number } }).response?.status;
    if (status === 404) return null;
    throw error;
  }
}

export async function saveCraftEssenceConfirmation(payload: {
  plan_id: string;
  quest_id: string;
  required_essences: string[];
  available_essences: string[];
  confirmed: boolean;
  notes?: string;
}): Promise<CraftEssenceConfirmation> {
  const { data } = await api.put<CraftEssenceConfirmation>(
    '/game-assistant/fgo/3t/craft-essence-confirmation',
    payload,
  );
  return data;
}

// ---------- 执行器（后端起 battle_runner 子进程，进度读 runs/<run_id> 的证据） ----------

/** runbook 的可用性：绑的活动结束了就不能跑（副本已经不在游戏里，硬跑会点到别的关卡）。 */
export interface RunbookOption {
  name: string;
  quest_id: string;
  title: string;
  availability: 'usable' | 'event_ended' | 'unknown';
  event_id: string;
  event_status: string;
  reason: string;
}

export interface ExecutionOptions {
  runbooks: string[];
  runbook_items?: RunbookOption[];
  archived_runbooks?: string[];
  layouts: string[];
  registered_support_keys: string[];
  registered_buttons: string[];
  note: string;
}

export interface ExecutionStepSummary {
  index?: number | null;
  round?: number | null;
  kind?: string | null;
  label?: string | null;
  verdict?: string | null;
  note?: string | null;
}

export interface ExecutionProgress {
  steps_total: number;
  by_verdict: Record<string, number>;
  last_steps: ExecutionStepSummary[];
  log_tail: string[];
  quest_id?: string | null;
  support?: { key?: string; forced_row?: number | null; picked_row?: number | null } | null;
  latest_evidence?: { name: string; mtime: number } | null;
}

export interface ExecutionStatus {
  running: boolean;
  run_id: string;
  run_dir: string;
  started_at: string;
  rounds: number;
  auto_apple: number;
  enter_quest: boolean;
  pid: number | null;
  exit_code: number | null;
  stop_requested: boolean;
  progress: ExecutionProgress;
  log_path: string;
}

export interface ExecutionRunResult {
  run_id: string;
  pid: number;
  rounds: number;
  auto_apple: number;
  enter_quest: boolean;
  run_dir: string;
  log_path: string;
  note: string;
}

export interface ExecutionStopResult {
  stopped: boolean;
  run_id?: string;
  exit_code?: number | null;
  note?: string;
  reason?: string;
}

const EXECUTION_BASE = '/game-assistant/fgo/execution';

export async function loadExecutionOptions(): Promise<ExecutionOptions> {
  const { data } = await api.get<ExecutionOptions>(`${EXECUTION_BASE}/options`);
  return data;
}

export async function loadExecutionStatus(): Promise<ExecutionStatus> {
  const { data } = await api.get<ExecutionStatus>(`${EXECUTION_BASE}/status`);
  return data;
}

export async function startExecution(payload: {
  spec: string;
  layout: string;
  rounds: number;
  enter_quest: boolean;
  support_row: number;
  /** AP 不足时自动使用黄金果实，最多 3 个；0 = 关闭。 */
  auto_apple?: number;
  device?: string;
  confirm_ap: boolean;
  /** 显式允许跑「活动已结束」的 runbook（默认后端会拦）。 */
  allow_ended?: boolean;
}): Promise<ExecutionRunResult> {
  const { data } = await api.post<ExecutionRunResult>(`${EXECUTION_BASE}/run`, payload);
  return data;
}

/** 归档：挪进 `runbooks/_archive/`（不删），下拉里不再出现；可撤销。 */
export async function archiveRunbook(name: string): Promise<{ archived: boolean; name: string; path?: string }> {
  const { data } = await api.post(`${EXECUTION_BASE}/runbooks/${encodeURIComponent(name)}/archive`, null);
  return data;
}

export async function unarchiveRunbook(name: string): Promise<{ archived: boolean; name: string; path?: string }> {
  const { data } = await api.post(`${EXECUTION_BASE}/runbooks/${encodeURIComponent(name)}/unarchive`, null);
  return data;
}

export async function stopExecution(): Promise<ExecutionStopResult> {
  const { data } = await api.post<ExecutionStopResult>(`${EXECUTION_BASE}/stop`);
  return data;
}

export function executionEvidenceUrl(runId: string, name: string): string {
  return `/api${EXECUTION_BASE}/evidence/${encodeURIComponent(runId)}/${encodeURIComponent(name)}`;
}

// ---------- 自定义 runbook（表单：副本 + 队伍 + 每回合操作 + 助战规则） ----------

export interface RunbookTeamSlot {
  name: string;
  class_name: string;
}

export interface RunbookStep {
  turn: number;
  actor: string;
  /** 按站位指定演员（双杀狐 / 双 C呆这种同名占两个站位时必须用它）。 */
  actor_slot?: number;
  kind: 'skill' | 'np' | 'card' | 'mystic_code';
  skill_slot?: number;
  card?: string;
  position?: string;
  /** 选卡偏好链：按顺序试，第一条能挑到卡的生效（例如 力击 → 任意卡）。 */
  choose?: Array<{ card: string; position?: string; engraved_code?: string }>;
  target?: string;
}

export interface RunbookDraft {
  name: string;
  quest_id: string;
  title: string;
  source: string;
  notes: string[];
  /** 打手位（队伍里的名字）：辅助位没写 target 的单体友方技能会默认指向它。 */
  dps?: string;
  team: RunbookTeamSlot[];
  steps: RunbookStep[];
  support?: { servant: string; ce_names: string[] } | null;
}

export interface RunbookCreated {
  name: string;
  actions: number;
  summary: string;
  support: Record<string, unknown>;
}

/** 已登记过的助战指纹（表单勾白名单用）。 */
export interface SupportLibrary {
  servant: string[];
  ce: string[];
}

export async function loadSupportLibrary(): Promise<SupportLibrary> {
  const { data } = await api.get<SupportLibrary>(`${EXECUTION_BASE}/support-library`);
  return data;
}

/** 队伍下拉用的账号从者（按职阶+名字排好，带稀有度与等级，方便消歧）。 */
export interface AccountServantBrief {
  name: string;
  class_name: string;
  rarity: number;
  level: number;
  np_level?: number | null;
}

export async function loadAccountServants(): Promise<AccountServantBrief[]> {
  const { data } = await api.get<AccountServantBrief[]>('/game-assistant/fgo/account/servants');
  return data;
}

/** 把草稿交给后端：先编译期校验，通过才落盘成 runbook。 */
export async function createRunbook(draft: RunbookDraft): Promise<RunbookCreated> {
  try {
    const { data } = await api.post<RunbookCreated>(`${EXECUTION_BASE}/runbooks`, draft);
    return data;
  } catch (error: unknown) {
    throw new Error(runbookRequestErrorMessage(error));
  }
}

/** 「自检」：用不执行模式跑一遍执行器 —— 只截图判据，不点任何东西、不花 AP。 */
export interface RunbookCheckResult {
  ok: boolean;
  exit_code: number | null;
  output_tail: string[];
}

export async function checkRunbook(
  name: string,
  options: { layout?: string; enterQuest?: boolean; device?: string } = {},
): Promise<RunbookCheckResult> {
  const { data } = await api.post<RunbookCheckResult>(
    `${EXECUTION_BASE}/runbooks/${encodeURIComponent(name)}/check`,
    null,
    {
      params: {
        layout: options.layout ?? '',
        enter_quest: options.enterQuest ?? false,
        device: options.device ?? '',
      },
    },
  );
  return data;
}

/** 「登记当前助战行」：游戏停在助战屏时，把第 N 行的从者/礼装指纹存进指纹库（不点任何东西）。 */
export interface SupportRegisterSaved {
  kind: 'servant' | 'ce' | string;
  name: string;
  meta: string;
  source_row: number;
}

export interface SupportRegisterReport {
  ok?: boolean;
  row?: number;
  rows_seen?: number;
  scene?: string;
  shot?: string;
  saved?: SupportRegisterSaved[];
  discrimination?: Record<string, Record<string, number>>;
}

export interface SupportRegisterResult {
  ok: boolean;
  exit_code: number | null;
  run_id: string;
  report: SupportRegisterReport | null;
  output_tail: string[];
  note?: string;
}

export async function registerSupportRow(payload: {
  row: number;
  servant?: string;
  ce?: string[];
  device?: string;
}): Promise<SupportRegisterResult> {
  const { data } = await api.post<SupportRegisterResult>(
    `${EXECUTION_BASE}/support/register`,
    { row: payload.row, servant: payload.servant ?? '', ce: payload.ce ?? [], device: payload.device ?? '' },
  );
  return data;
}

// ---------- 后续活动日程（confirmed = 用户核对过来源；candidate = 候选） ----------

export interface UpcomingEvent {
  event_id: string;
  title: string;
  server: string;
  starts_at: string | null;
  ends_at: string | null;
  status: 'confirmed' | 'candidate';
  source_title: string;
  source_url: string;
  note: string;
  updated_at: string;
}

export interface ScheduleResponse {
  items: UpcomingEvent[];
  confirmed_count: number;
  /** 「下个活动」：confirmed 且尚未开始的条目（后端按 +08:00 算好）。 */
  confirmed_upcoming?: UpcomingEvent[];
  /** 日服·参考（约一年前同期）：只作参考，不代表国服排期。 */
  japanese_reference?: JapaneseReference;
  /** 维护窗口：单独存 `maintenance_cn.json`，不进活动日程。 */
  maintenance?: MaintenanceWindow[];
  path: string;
  note: string;
}

export interface MaintenanceWindow {
  announcement_id: string;
  title: string;
  starts_at: string;
  ends_at: string | null;
  source_url?: string;
  note?: string;
}

export interface JapaneseReferenceItem {
  title: string;
  starts_at: string;
  ends_at: string | null;
  type?: string;
  server?: string;
}

export interface JapaneseReference {
  fetched_at: string | null;
  anchor?: string;
  window_start?: string;
  window_end?: string;
  items: JapaneseReferenceItem[];
  note: string;
}

/** 「拉取官方公告」的回执：只落候选，确认永远由人点。 */
export interface ScheduleRefreshResult {
  added: Array<{ event_id: string; title: string; starts_at: string | null }>;
  updated: Array<{ event_id: string; title: string; starts_at: string | null }>;
  skipped: Array<{ event_id: string; title?: string; why: string }>;
  stale: Array<{ event_id: string; title?: string; why: string }>;
  errors: string[];
  checked: number;
  candidate_total: number;
  mooncell?: { ok: boolean; items?: number; jp?: number; cn?: number; error?: string };
}

export async function refreshOfficialSchedule(limit = 12): Promise<ScheduleRefreshResult> {
  const { data } = await api.post<ScheduleRefreshResult>(
    '/game-assistant/fgo/schedule/refresh-from-official',
    null,
    { params: { limit } },
  );
  return data;
}

export async function loadSchedule(): Promise<ScheduleResponse> {
  const { data } = await api.get<ScheduleResponse>('/game-assistant/fgo/schedule');
  return data;
}

export async function upsertScheduleEvent(payload: {
  event_id: string;
  title: string;
  starts_at?: string | null;
  ends_at?: string | null;
  source_title?: string;
  source_url?: string;
  note?: string;
  confirm: boolean;
}): Promise<UpcomingEvent> {
  const { data } = await api.post<{ item: UpcomingEvent }>('/game-assistant/fgo/schedule', payload);
  return data.item;
}

export async function deleteScheduleEvent(eventId: string): Promise<boolean> {
  const { data } = await api.delete<{ deleted: boolean }>(
    `/game-assistant/fgo/schedule/${encodeURIComponent(eventId)}`,
  );
  return data.deleted;
}
