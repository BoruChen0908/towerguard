# Advisory 生命週期設計（v1.2 提案基礎）

*2026-06-12 · 三路平行設計（人因 / 協議 / demo 劇本）彙整 · 待指揮官拍板後實作*

## 核心原則（三路收斂的同一句話）

> **Re-surface on a change in the world, never on the passage of time.**
> 警示因「世界改變」（tier 惡化、新衝突對、資料恢復、shelve 到期）而重現，永不因「時間經過」而重複。

依據：alarm fatigue 實證（每次重複提醒接受率掉 ~30%，Ancker et al.）；ISA-18.2 / EEMUA 191 警報管理標準的 acknowledge/shelve 語義。

## 1. 管制員行動空間

完整模型五動作（ISA-18.2 對映），demo 實作三顆按鈕：

| 動作 | 語義 | 稽核 | demo 實作 |
|---|---|---|---|
| **Acknowledge** | 「我看到了、我接手」≠ 同意 ≠ 解除；條件未消失前卡片轉暗但不消失 | `confirmed:{id}` key + stream `action` | ✅ 按鈕（取代現在的 Confirm 語義） |
| **Dismiss（帶理由）** | 「我判斷這是誤報」——人否決 AI；理由用罐頭 chip（already separated / data stale / visual / other） | `dismissed:{id}` + reason | ✅ 按鈕＋理由 chips（誤報 ground truth，調閾值的素材） |
| **Re-assess** | 「用最新感測資料重算」——只能觸發重算，**不能餵給 AI 期望結論**；限流（每卡 ≤2 次）；重算結果同級或更糟時不可靜默消失 | stream `reassess` + 回應鏈 | ✅ 按鈕 |
| Agree / action taken | 「有效且我已處置」（與 Acknowledge 分開才能量測 AI 真陽性率） | stream `action` | 📋 寫入 v1.2 文件，demo 併入 Acknowledge |
| Shelve | 「有效但現在沒空」，限時自動回來、惡化立即穿透 | stream + `until` | 📋 v1.2 roadmap（ISA-18.2 shelve 原文語義） |

**紅線守則**：按鈕動詞永遠描述「人與 advisory 的關係」，絕不描述「對空域的操作」（不出現 Resolve/Vector/Clear）；無人理會的卡升高可見度、永不自動消失；沒有「全部信任 AI」開關。

## 2. 證據面板（Evidence）

- **Tier 1（卡面常駐）**：severity、summary、recommended_attention、contributing signal chips（幾個模組同意一目了然）、confidence **以等級帶呈現**（High/Med/Low，不裸給 0.92——假精度誘發過度信任）
- **Tier 2（點開展開，預設收合）**：每個訊號的決策時快照——**數值對著閾值放**（2.8 NM vs ICAO min 3.0 ¶5-5-4），附 lineage 標籤。CRITICAL 與 SURFACE_CONFLICT 預設展開
- **SURFACE_CONFLICT 特殊版面**：兩欄等權呈現矛盾雙方（各自 tier＋claim＋數值），AI 明確「拒絕仲裁」，UI 不得暗示偏好任一方；此類卡不鼓勵單純 Acknowledge——要嘛採信一方、要嘛 Re-assess

### Advisory v1.2 新欄位（全部 optional，缺席容忍）

```json
{
  "condition_key": "KJFK:conflict_geometry:AAL891/UAL412",
  "supersedes": ["ADV-0007"],
  "in_response_to": "RAS-7f3a",
  "evidence": { "signals": [ { "event_type", "alert_id", "tier", "key_values": {}, "detail" } ] },
  "conflict": { "between": [ {"event_type","alert_id","tier","claim"}, {...} ], "note": "..." }
}
```

## 3. 重發／去重協議（解掉「confirm 後又來一張」）

- **condition_key**＝airport＋signals＋排序後的衝突對 callsign（同一對機不因順序產生兩條）
- 規則：同 condition 同 tier → **不重發**；人處理後 cooldown 300s；**tier 惡化立即穿透 cooldown**，新卡帶 `supersedes`；條件消失 → 發 lifecycle `resolved` 收舊卡
- 病根診斷：現在的 mock 是 45 秒定時器＋每張新 id → 前端必建新卡。**重寫為條件驅動後此問題自然消失**

## 4. Re-assess 通道

```
dashboard POST /reassess/{id} → pub/sub towerguard:reassess_request
Orchestrator 必回（永不靜默）：
  (a) 條件仍在/更糟 → 新 advisory（supersedes + in_response_to）
  (b) 條件消失     → towerguard:advisory_lifecycle {new_state:"resolved", reason}
  (c) 訊號矛盾     → SURFACE_CONFLICT
timeout 10s → 卡片標「re-assess timed out」，fail-safe 不收卡
```

狀態機：`issued → confirmed/dismissed`（dashboard 擁有，v1.1 key 不動）；`superseded/expired/resolved`（Orchestrator 擁有，新 key `towerguard:advisory:state:{id}`）。**雙 key 設計避免兩個寫者搶同一個 key。** 人的決定永不被覆寫（confirmed 後被 supersede → 顯示「confirmed, then superseded」兩個事實並存）。

## 5. shift_events 補強

- 新 kind：`reassess` / `supersede` / `resolve` / `expire`（前端容忍未知 kind）
- 新增 optional 第五欄 `tier`（tier_change 帶新 tier，事件條才能上真色）

## 6. Mock 條件驅動規則表（demo 劇本）

| # | 觸發 | 輸出 | 去重鍵 |
|---|---|---|---|
| C1 | cg tier=HIGH 且該 pair 未發過 | ESCALATE/HIGH＋evidence | pair_key+HIGH |
| C2 | cg tier=CRITICAL 且該 pair CRITICAL 未發過 | ESCALATE/CRITICAL（supersedes C1 卡） | pair_key+CRITICAL |
| W | wi tier≥MEDIUM **且** cg≥HIGH 共現 | ESCALATE（複合：缺人＋衝突） | airport+wi.tier |
| S | td tier=LOW 但 cg≥HIGH（訊號矛盾） | SURFACE_CONFLICT＋conflict block | pair_key |
| R | 已發過的 pair 降回 LOW（respawn/改善） | lifecycle resolved＋顯式 supersede 卡 | pair 降級事件 |

- **Briefing 動態組裝**：五段全部從 shift_events 真實內容生成（未決 advisory 列表標 ✓/✕、本班 tier 變化逐行、pending = 未確認數）→ 每次渲染都不同，劇情自動反映
- **機場敘事弧**（實算 workload）：JFK 30/33=LOW（滿編對照組，AI 安靜）↔ **ATL 37/52=MEDIUM 缺 15 人**（規則 W 主場）；EWR 0.374 最接近門檻
- **導演開關**：①機場切換（現成）②`DEMO_WORKLOAD_SURGE`（推 HIGH 劇情）③`DEMO_DEGRADED`（D7 斷線演示）④幽靈高度對（水平近、垂直分離 ≥1000ft → 觸發 S 規則）
- 8 分鐘時間軸：0:00 JFK 開場 → 1:05 C1 卡 → confirm → 2:00 C2 卡 → dismiss → 2:40 切 ATL → 3:00 W 複合卡 → 3:30 動態 briefing 簽核 → 4:30 supersede 卡 → 5:30 SURFACE_CONFLICT → 6:00 DEGRADED → 7:00 切回 JFK＋lineage 收尾

## 給 Katherine 的 v1.2 確認清單

1. advisory 新欄位（condition_key/supersedes/in_response_to/evidence/conflict）— 全 optional
2. `towerguard:reassess_request` / `towerguard:advisory_lifecycle` 兩個新 topic
3. `towerguard:advisory:state:{id}` key（她擁有）＋ condition 去重 hash（她內部）
4. cooldown 300s / reassess timeout 10s 兩個契約常數
5. shift_events 的 tier 欄位與新 kind
6. briefing 建議獨立 `briefing_id`（與 advisory_id 分離）
