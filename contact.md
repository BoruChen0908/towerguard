# TowerGuard — Interface Contract
**Version:** 1.1（提案版 — 待 Katherine 於 6/15 EOD 前確認）
**Date:** 2026-06-12
**Katherine (AI/Agents) ↔ Bo-Ru (Backend/Modules)**

---

## v1.0 → v1.1 變更摘要（給 Katherine 看的重點）

| # | 變更 | 原因 |
|---|------|------|
| 1 | 分級欄位統一為 `tier`（原 `load_tier` / `severity` / `tier` 三種叫法） | Orchestrator 不必為每個模組寫特判 |
| 2 | 0–1 指數統一為 `score`（原 `load_index` / `workload_score`） | 同上 |
| 3 | 三個模組事件共用同一組頂層欄位（見 §2 envelope） | 一套解析邏輯走全部 |
| 4 | 斷線改為 `data_unavailable: true` + `tier: "UNKNOWN"`，撤銷「斷線發 LOW」 | 回報 LOW 等於把系統故障偽裝成安全狀態，違反紀律一 |
| 5 | Conflict Geometry 的 tier 規則改為由重到輕逐條判定、先中先停 | v1.0 規則有重疊（≤60s 同時符合 HIGH 與 CRITICAL）與未定義區間 |
| 6 | Workload Index 補上 tier 閾值（沿用 §2a 對照表） | v1.0 漏寫 |
| 7 | `towerguard:shift_events` 從 pub/sub 改為 Redis Stream | pub/sub 不累積、訂閱者離線會漏訊息；Narrator 需要完整班次 log |
| 8 | 新增 `towerguard:confirmed:{advisory_id}` 持久 key | pub/sub 訊息發出即逝，`confirmed_by_controller` 原本沒有地方可以改 |
| 9 | 衝突定義補明垂直條件（原文僅水平，與作業實務不符） | 真實間隔判定是水平與垂直雙條件同時成立；只看水平會把垂直已分離的飛機誤報為衝突 |

---

## 概覽

這份文件定義 Bo-Ru 的三個確定性模組和 Katherine 的兩個 LLM Agent 之間的完整介面。
雙方只要遵守這份 schema，可以完全獨立開發，互不干擾。

```
OpenSky ADS-B
     ↓
Bo-Ru: Traffic Density ──┐
Bo-Ru: Conflict Geometry ─┼→ Redis pub/sub → Katherine: Orchestrator → Advisory JSON
Bo-Ru: Workload Index ───┘                              ↓
                                              Katherine: Narrator → Briefing Markdown
```

---

## 1. Redis Topic 命名規範

| Topic | 型態 | 發布者 | 訂閱／讀取者 | 說明 |
|-------|------|--------|--------------|------|
| `towerguard:traffic_density` | pub/sub | Bo-Ru | Orchestrator | 每 60 秒發一次 |
| `towerguard:conflict_geometry` | pub/sub | Bo-Ru | Orchestrator | 每 60 秒發一次 |
| `towerguard:workload_index` | pub/sub | Bo-Ru | Orchestrator | 每 60 秒發一次 |
| `towerguard:advisory` | pub/sub | Orchestrator | Dashboard / Narrator | 有 ESCALATE 時發 |
| `towerguard:shift_events` | **Redis Stream**（`XADD`） | Orchestrator | Narrator | 累積整班次 event log；Narrator 用 `XRANGE` 讀全量，離線也不漏 |
| `towerguard:confirmed:{advisory_id}` | String key（`SET`） | Dashboard | Orchestrator / Narrator | 管制員按下 Confirm 時寫入 ISO 8601 時間戳 |

---

## 2. 模組事件共用 Envelope（Bo-Ru 負責輸出）

**三個模組的事件一律包含以下頂層欄位，命名完全一致：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `event_type` | string | `"traffic_density"` \| `"conflict_geometry"` \| `"workload_index"` |
| `alert_id` | string | 前綴 `TD-` / `CG-` / `WI-` + 四位數字，每次遞增 |
| `airport` | string | ICAO 機場代碼（例如 `KMDW`） |
| `timestamp` | string | ISO 8601 UTC |
| `tier` | string | `"LOW"` \| `"MEDIUM"` \| `"HIGH"` \| `"CRITICAL"` \| `"UNKNOWN"` |
| `data_unavailable` | boolean | 正常為 `false`；拿不到上游資料時為 `true`（此時 `tier` 必為 `"UNKNOWN"`） |

`score`（float，0.0–1.0）是標準化指數欄位名，出現在 Traffic Density 和 Workload Index；Conflict Geometry 的 tier 由規則直接判定，無 `score` 欄位。

### 2a. score → tier 對照表（Traffic Density 與 Workload Index 共用）

| tier | 條件 |
|------|------|
| LOW | score < 0.40 |
| MEDIUM | 0.40 ≤ score < 0.65 |
| HIGH | 0.65 ≤ score < 0.85 |
| CRITICAL | score ≥ 0.85 |
| UNKNOWN | 僅在 `data_unavailable: true` 時使用，此時 `score` 為 `null` |

### 2b. Traffic Density

```json
{
  "event_type": "traffic_density",
  "alert_id": "TD-0001",
  "airport": "KMDW",
  "timestamp": "2026-06-14T18:42:00Z",
  "tier": "HIGH",
  "data_unavailable": false,
  "score": 0.74,
  "aircraft_count": 115,
  "speed_variance": 42.3,
  "altitude_variance": 3800,
  "window_seconds": 60
}
```

| 模組專屬欄位 | 型別 | 說明 |
|------|------|------|
| `score` | float | 0.0–1.0，加權計算結果（v1.0 的 `load_index`） |
| `aircraft_count` | integer | 50NM 半徑內飛機總數 |
| `speed_variance` | float | 地速標準差（knots） |
| `altitude_variance` | float | 高度標準差（feet） |
| `window_seconds` | integer | 計算窗口（固定 60） |

### 2c. Conflict Geometry

```json
{
  "event_type": "conflict_geometry",
  "alert_id": "CG-0017",
  "airport": "KMDW",
  "timestamp": "2026-06-14T18:42:05Z",
  "tier": "HIGH",
  "data_unavailable": false,
  "pairs_checked": 22,
  "conflicts_detected": 2,
  "closest_pair": {
    "callsigns": ["UAL412", "AAL891"],
    "projected_separation_nm": 2.8,
    "icao_minimum_nm": 3.0,
    "time_to_violation_seconds": 87
  },
  "all_conflicts": [
    {
      "callsigns": ["UAL412", "AAL891"],
      "projected_separation_nm": 2.8,
      "icao_minimum_nm": 3.0,
      "time_to_violation_seconds": 87
    }
  ]
}
```

| 模組專屬欄位 | 型別 | 說明 |
|------|------|------|
| `pairs_checked` | integer | 本次檢查的飛機配對總數 |
| `conflicts_detected` | integer | 偵測到的潛在衝突數量 |
| `closest_pair` | object \| null | 最近的一對；無衝突時為 `null` |
| `all_conflicts` | array | 所有衝突配對，無衝突時為空陣列 `[]` |

**衝突定義（雙條件，需同時成立）：** 在外推窗口（120 秒）內存在某一時刻，使得 projected horizontal separation `< icao_minimum_nm`（3.0 NM）**且** vertical separation `< 1000 ft`。兩者缺一不構成衝突——垂直已分離（≥ 1000 ft）的飛機即使水平接近也不算衝突。

- `time_to_violation_seconds`：上述雙條件首次同時成立的時刻（首次違規時刻）。
- `projected_separation_nm`：窗口內最小水平間隔（由 CPA 解析求得）。此值是「最近接近」量，與首次違規時刻通常不是同一時間點。

**tier 判斷規則（由上往下逐條判定，先中先停）：**

1. `data_unavailable: true` → **UNKNOWN**
2. 無衝突 → **LOW**
3. 任一衝突 `time_to_violation_seconds ≤ 60` → **CRITICAL**
4. 任一衝突 `time_to_violation_seconds ≤ 90` → **HIGH**
5. 其餘（所有衝突 > 90s） → **MEDIUM**

### 2d. Workload Index

```json
{
  "event_type": "workload_index",
  "alert_id": "WI-0033",
  "airport": "KMDW",
  "timestamp": "2026-06-14T18:42:08Z",
  "tier": "HIGH",
  "data_unavailable": false,
  "score": 0.81,
  "staffed_controllers": 2,
  "recommended_controllers": 4,
  "active_frequencies": 3,
  "handoff_rate_per_hour": 12
}
```

| 模組專屬欄位 | 型別 | 說明 |
|------|------|------|
| `score` | float | 0.0–1.0（v1.0 的 `workload_score`），tier 對照見 §2a |
| `staffed_controllers` | integer | 目前上班人數（demo 中為 mock／設定檔，OpenSky 無此資料） |
| `recommended_controllers` | integer | FAA 建議人數（同上，mock／設定檔） |
| `active_frequencies` | integer | 目前使用中的頻率數（同上，mock／設定檔） |
| `handoff_rate_per_hour` | integer | 每小時交接次數（同上，mock／設定檔） |

---

## 3. Advisory Output Schema（Katherine 負責輸出）

Orchestrator 輸出到 `towerguard:advisory` topic：

```json
{
  "advisory_id": "ADV-0009",
  "timestamp": "2026-06-14T18:42:10Z",
  "airport": "KMDW",
  "action": "ESCALATE",
  "severity": "HIGH",
  "confidence": 0.92,
  "summary": "High traffic density with projected separation violation detected.",
  "contributing_signals": ["traffic_density", "conflict_geometry", "workload_index"],
  "recommended_attention": "UAL412/AAL891 pair approaching 2.8nm in 87s, understaffed sector.",
  "human_override_required": true,
  "confirmed_by_controller": false,
  "generated_at": "2026-06-14T18:42:10Z"
}
```

**action 三種值的意思：**
- `ESCALATE`：需要人注意，顯示在 dashboard 警示區
- `SUPPRESS`：不需要動作，不顯示
- `SURFACE_CONFLICT`：模組信號衝突，特別標示請人判斷

**`confirmed_by_controller` 的語義（v1.1 修正）：** 發布時固定為 `false`（pub/sub 訊息發出後不可變）。實際確認狀態以 `towerguard:confirmed:{advisory_id}` key 是否存在為準（見 §4）。

---

## 4. Handover Briefing Format（Katherine 負責輸出）

Narrator 輸出 Markdown 字串，Bo-Ru 的 dashboard 直接渲染：

```markdown
---
## Position Relief Briefing — KMDW 1842Z
*AI-generated draft. Outgoing controller must review and confirm.*

### 1. Current traffic picture
### 2. Active advisories
### 3. Notable events this shift
### 4. Weather and NOTAMs
### 5. Pending actions

---
*Reviewed and confirmed by: ________________  [TIME]__________*
---
```

Dashboard 渲染這個 Markdown 時，底部加一個「Controller Confirmed」按鈕。點擊後執行：

```
SET towerguard:confirmed:{advisory_id} "<ISO 8601 UTC 時間戳>"
```

需要確認狀態的一方（Orchestrator / Narrator）用 `GET` 讀這個 key：存在即已確認。

---

## 5. 交接時間表

| 日期 | 交接內容 | 負責人 |
|------|----------|--------|
| 6/15 EOD | 確認三個模組 JSON schema 最終版本（含本次 v1.1 變更） | 雙方 |
| 6/16 EOD | Advisory output schema 確認 | Katherine |
| 6/17 EOD | Handover briefing Markdown 格式確認 | Katherine |
| 6/19 | 整合測試，用 mock 資料跑完整流程 | 雙方 |

---

## 6. 錯誤處理約定（v1.1 重寫）

- **模組拿不到 OpenSky 資料：** 照常發事件，但 `data_unavailable: true`、`tier: "UNKNOWN"`、`score: null`（Conflict Geometry 的 `closest_pair: null`、`all_conflicts: []`）。Dashboard 顯示 **DEGRADED** 狀態，**不得**顯示為 LOW——故障不能偽裝成安全。
- **Orchestrator 收到格式錯誤的事件：** 回傳 `action: "SUPPRESS"`，不會 crash。
- **所有事件的 `timestamp`：** 統一用 UTC，格式 ISO 8601。

---

*TowerGuard — AI-augmented decision support for understaffed ATC towers*
*Katherine & Bo-Ru — BU MSBA, USAII Global AI Hackathon 2026*

---

## 7. v1.2 提案（待 Katherine 確認）

> 核心原則：**Re-surface on a change in the world, never on the passage of time.**
> 警示因「世界改變」（tier 惡化、新衝突對、資料恢復）而重現，永不因「時間經過」而重複。
> 設計全文見 `docs/advisory-lifecycle-design.md`。以下是需要 Katherine 點頭的契約增量，全部 **向後相容**（既有欄位/topic 不動）。

### 7.1 Advisory 新欄位（全 optional，缺席容忍）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `condition_key` | string | `{airport}:{signals}:{sorted_callsigns}`；同一對機去重的依據，順序無關 |
| `supersedes` | array[string] | 此卡取代的舊 advisory_id（tier 惡化或 re-assess 重發時帶） |
| `in_response_to` | string \| null | 對應的 `request_id`（只有 re-assess 重發的卡才有） |
| `evidence` | object | `{signals:[{event_type, alert_id, tier, key_values{}, detail}]}`；三模組決策時快照，`detail` 一句話含數值對閾值 |
| `conflict` | object | 僅 SURFACE_CONFLICT：`{between:[{event_type, alert_id, tier, claim}×2], note}`；恰兩個矛盾訊號，AI 拒絕仲裁 |

### 7.2 兩個新 topic（pub/sub）

| Topic | 型態 | 發布者 | 訂閱者 | 說明 |
|-------|------|--------|--------|------|
| `towerguard:reassess_request` | pub/sub | Dashboard | Orchestrator | payload `{type:"reassess_request", request_id:"RAS-<4hex>", advisory_id, requested_at, reason:"controller_manual"}`；Orchestrator **必回**（永不靜默） |
| `towerguard:advisory_lifecycle` | pub/sub | Orchestrator | Dashboard | payload `{type:"advisory_lifecycle", advisory_id, new_state:"resolved"\|"superseded"\|"expired", in_response_to, reason, timestamp}` |

### 7.3 新 key（Orchestrator 擁有）

| Key | 型態 | 寫者 | 說明 |
|-----|------|------|------|
| `towerguard:advisory:state:{id}` | String（`SET`） | Orchestrator | `superseded`\|`resolved`\|`expired`。**與 dashboard 的 `confirmed:`/`dismissed:` 是不同 key**，雙寫者不搶，人的決定永不被覆寫 |
| `towerguard:dismiss_reason:{id}` | String（`SET`） | Dashboard | dismiss 罐頭理由（`already_separated`\|`data_stale`\|`visual_separation`\|`false_geometry`\|`other`）；`dismissed:{id}` 本身仍是純 ISO 時間戳，理由另存不污染契約 |
| `towerguard:reassess_count:{id}` | String（`INCR`） | Dashboard | 每張 advisory 的 re-assess 次數，**上限 2**，第 3 次回 429 `{"error":"reassess_limit"}` |
| `towerguard:demo:{flag}` | String（`SET`/`DEL`） | Dashboard | 導演開關 `flag ∈ degraded\|sparse\|workload_surge`；runner 每 cycle 讀 |

### 7.4 兩個契約常數

| 常數 | 值 | 用途 |
|------|----|----|
| cooldown | **300 s** | 人處理後同 condition 同 tier 的冷卻；tier 惡化立即穿透 |
| reassess timeout | **10 s** | 卡片端等待重評上限；逾時標「re-assess timed out」、fail-safe 不收卡 |

### 7.5 shift_events 補強（§5 細化）

- 新 `kind`：`reassess` / `supersede` / `resolve` / `expire`（前端容忍未知 kind）
- 新增 optional 第五欄 `tier`（tier_change 帶新 tier，事件條才能上真色）；缺席容忍，沿用 `"null"` sentinel 模式解碼回 `None`

### 7.6 建議：briefing_id 與 advisory_id 分離

- briefing 改為動態組裝（五段從 shift_events 真實內容生成），不再綁單一 advisory
- 建議獨立 `briefing_id`（`BRF-####`），與 `advisory_id` 分離；過渡期 payload 仍保留 `advisory_id` 欄位以相容現有 SSE 契約
