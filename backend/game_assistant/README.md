# FGO Game Assistant Guide Slice

本模块是游戏助手的第一阶段垂直切片，只负责：

- 当前活动公开事实与来源 revision。
- 攻略结构化生成。
- 候选执行计划生成。
- 生成记录持久化。

不包含账号资源、ADB、模拟器输入、游戏点击、奖励领取或自动执行。

## Providers

- `template`：确定性模板，始终可用，也是失败回退。
- `local`：Ollama OpenAI-compatible API，默认模型 `qwen3:8b`。
- `deepseek`：OpenAI-compatible DeepSeek API，使用 JSON response format。

环境变量：

```text
GAME_ASSISTANT_DB=
GAME_ASSISTANT_LOCAL_MODEL=qwen3:8b
GAME_ASSISTANT_LLM_TIMEOUT=180
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
```

DeepSeek Key 只能配置在后端环境中，不应进入前端、数据库、日志或版本控制。

## API

```text
GET  /api/game-assistant/fgo/bootstrap
GET  /api/game-assistant/fgo/events
POST /api/game-assistant/fgo/guides/generate
GET  /api/game-assistant/fgo/guides/{generation_id}
```

生成请求示例：

```json
{
  "provider": "local",
  "event_id": "fgo-cn-2026-gudaguda9",
  "revision": 1,
  "goal": "生成本期活动的当前阶段攻略和候选执行计划"
}
```

## Data Boundary

- 公共事实保存在独立 `game_assistant.db`。
- 事实包携带 `source_id`、抓取时间和 revision。
- LLM 只接收生成所需的紧凑事实包。
- 时间、当前阶段和 90++ 解锁判断由规则代码校正，模型不能覆盖。
- 本阶段输出永远是候选攻略和候选计划。
## Editable Account Snapshot

The Game Assistant page includes an editable `账号资源` table for:

- Servant levels, NP levels, skills, append skill, confidence and notes.
- Material quantity and reserve quantity.
- Manual add, edit, save, delete and refresh.

Private data is stored in a separate `game_assistant_private.db`. It is not
copied into the public event knowledge database and is not sent to DeepSeek.
Scanning and screenshot/VLM import can write candidate rows into this table in
a later phase.
## Provider Settings

The Game Assistant page includes a `模型设置` dialog for:

- DeepSeek API.
- OpenAI-compatible endpoints.
- Local Ollama.

API keys are write-only from the frontend perspective. They are never stored
in the public/private SQLite databases or returned by the API. On Windows they
are encrypted with DPAPI in:

`AIproduct/game_assistant_config/secrets.json`

Non-secret provider fields and the latest connection-test result are stored in
the same config directory. `POST /api/game-assistant/fgo/settings/providers/{provider_id}/test`
performs a minimal model-list or Ollama-tag request.

## Source Ingestion

The activity page supports URL or pasted-text sources. Snapshot files are saved
under `AIproduct/game_assistant_sources`.

Endpoints:

```text
GET  /api/game-assistant/fgo/sources
POST /api/game-assistant/fgo/sources/ingest
GET  /api/game-assistant/fgo/sources/{source_id}
POST /api/game-assistant/fgo/sources/{source_id}/extract
POST /api/game-assistant/fgo/sources/{source_id}/publish
```

URL fetching is server-side and rejects loopback, private, link-local, and
reserved addresses. Redirects are validated and response size/time are limited.
Dynamic JavaScript pages may not expose readable text to the server; in that
case the UI supports pasting the article body while retaining the original URL.

LLM extraction produces an `EventRevisionPatch` preview. Nothing is applied to
the active event bundle until the user explicitly confirms the publish action.
Only allow-listed event metadata and typed phase/quest/mission/shop collections
can be updated; source citations remain attached to the new revision.

## 3T Foundation MVP

The Game Assistant now exposes a reviewable 3T foundation:

- `CombatProfile`: three waves, enemy class/HP/attributes/traits/effects, verification status, and sources.
- `CombatantSnapshot`: actor slot, attack/HP, class relation, card/NP multipliers, NP state, and effects.
- `TeamPlan` and `TeamPlanAction`: three-turn action order, targets, NP changes, buffs, gates, assumptions, and warnings.
- Deterministic simplified damage/NP simulator with damage ranges and a three-turn clear gate.

Endpoints:

```text
GET  /api/game-assistant/fgo/3t/foundation
GET  /api/game-assistant/fgo/3t/combat-profiles
GET  /api/game-assistant/fgo/3t/combat-profiles/{quest_id}
GET  /api/game-assistant/fgo/3t/team-plans
POST /api/game-assistant/fgo/3t/simulate
```

The current `fgo_90pp_mock` profile and `mock-90pp-3t-plan` are fixtures for contract/simulator validation only. They are not verified game data and must not be used as an executable farming plan.

Source extraction sends only compact existing-ID context, not the full event bundle. This avoids model echo/truncation and keeps the output limited to added or changed records. A JSON parse failure is reported as a source error rather than a raw decoder exception.
