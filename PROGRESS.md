# TowerGuard — 進度與待辦盤點

> ⚠️ **Pre-pivot 文件（2026-06-12）— 只反映「即時 Live Validation 半」的進度,不是整個專案的現狀。**
> 模擬器半(model 層、validation/lifecycle/community、JSON 合約)在此之後才建,**不在本文範圍**。交接與全專案現狀請看 **[HANDOVER.md](HANDOVER.md)**;本文當作 KT 的 Job B(即時 agent)整合脈絡即可。

*最後更新：2026-06-12 · 負責人：Bo-Ru（後端＋dashboard）· 隊友：Katherine（LLM agents）*
*GitHub：`BoruChen0908/towerguard`（private）· 測試：212 passed · 今日 commit：10*

---

## 它是什麼（一句話）

當塔台長期人力吃緊，TowerGuard 用「3 個確定性模組 ＋ 2 個 LLM agent」承擔資訊處理負擔——偵測、排序、生成交班敘事——讓更少的管制員更安全地管更多航班。**人始終保留所有決策權，AI 只放大注意力**（Parasuraman 四階段第 1–2 階；對應 FAA JO 7110.65 ¶2-1-2）。

---

## 系統架構（誰做什麼）

```
OpenSky ADS-B
     ↓
[Bo-Ru] Traffic Density ──┐
[Bo-Ru] Conflict Geometry ─┼→ Redis ──→ [Katherine] Orchestrator → Advisory
[Bo-Ru] Workload Index ───┘     ↑            ↓
[Bo-Ru] Dashboard (FastAPI/SSE) ─┘    [Katherine] Narrator → 交班 Briefing
                                              ↑
                              shift_events Stream（Bo-Ru 已開通，Narrator 讀取）
```

- **Bo-Ru（我，已完成）**：三個確定性模組、Redis 資料層、OpenSky client、即時 dashboard、demo mock 系統
- **Katherine（她，尚未開始）**：Orchestrator 仲裁 agent、Narrator 交班敘事 agent
- **目前 demo 靠 `mock_katherine` 代行 Katherine 的兩個 agent**，6/19 接上她的真 agent 即可（守契約的話只是換掉 mock 進程）

---

## ✅ 今日完成（依 commit 順序）

### 1. 三個確定性模組 ＋ 後端資料層（`b5eb297`）
- **Traffic Density**：50NM 內飛機計數＋速度/高度變異 → 加權 score → tier
- **Conflict Geometry**：每對航班 120 秒外推、解析 CPA、雙條件比對（水平 3.0NM **且** 垂直 1000ft，FAA JO 7110.65 ¶5-5-4/¶4-5-1）、五條 tier 規則（首次違規時刻 ≤60s CRITICAL / ≤90s HIGH）
- **Workload Index**：用**真實 FAA 數字**（Controller Workforce Plan 2025–28 設施表，JFK 30/33、ATL 37/52 等）＋ mock 頻率/交接 → score → tier
- 共用 envelope builder＋schema 驗證器（強制 `data_unavailable → tier=UNKNOWN`，故障絕不偽裝成 LOW）
- OpenSky OAuth2 client（429/401/timeout 邊界 → data_unavailable，不偽造資料）
- Redis pub/sub 60 秒 runner、docker-compose（Redis）

### 2. 即時 Dashboard（`db4802c`）
- 技術棧從 Streamlit 改為 **FastAPI + SSE + 純 HTML/CSS + Leaflet**（視覺品質、擺脫 AI 範本臉、可上自訂過場動畫）
- 暗色 ops-room 介面：地圖（即時機隊）、三 tier 面板、advisory 警示列、briefing 滑出層、UTC 時鐘、LIVE 連線狀態、常駐免責横幅
- SSE bridge（last-message cache 重放，開頁面不必等 60 秒）
- 修掉 redis-py 8 安靜頻道 socket timeout bug（改 `get_message` 輪詢）

### 3. 地圖動態化（`60ab204`、`623c412`）
- velocity 單位修正：OpenSky m/s → knots（parse 邊界轉換，與既有 altitude/vertical_rate 一致）
- **dead-reckoning 動畫**：每秒按航向/速度外推飛機位置（與 conflict 模組同假設），120 秒上限、stale >90s 凍結
- demo 衝突對連續逼近（跨 cycle，HIGH→CRITICAL→重生），不再每分鐘重置

### 4. 三個展示功能（`06a62bc`）
- **機場切換器**：5 機場（JFK/EWR/BOS/ATL/MDW），切換即時 recenter ＋ 換真實 staffing 數字
- **Lineage「依據」面板**：每個決策點 → FAA/ICAO 標準對照表（後改為英文，`6fa0a72`）
- **班次事件時間軸**：`towerguard:shift_events` Redis Stream 的可視化——即 Narrator 交班敘事的原料

### 5. Advisory 生命週期 v1.2（`ce18392`、`6fa0a72`、`01efa62`）
- **條件驅動引擎**（取代定時器洗版）：規則 C1/C2/W/S/R，`condition_key` 去重，同條件同 tier 只發一次、人處理後 300s cooldown、**惡化才穿透**（HIGH→CRITICAL 帶 supersedes 取代舊卡）
- **三個行動**（對映 ISA-18.2 警報管理標準）：
  - **Acknowledge**（已接手，≠ 同意 ≠ 解除）
  - **Dismiss ＋ 五選一理由 chip**（誤報 ground truth）
  - **Re-assess**（用最新資料重算，10 秒超時、每卡限 2 次、429 限流）
- **Evidence 證據面板**：confidence 等級帶、每訊號數值對閾值、SURFACE_CONFLICT 雙欄等權矛盾呈現
- **9 顆區域 ⓘ info icons**：評審自助看技術細節（英文，含資料源/節奏/FAA 依據/AI 邊界）
- **導演開關**：`/demo/degraded|sparse|workload_surge` 控制 demo 劇情
- 動態 briefing：五段從 shift_events 真實內容組裝（每次渲染不同）

### 6. 可讀性調整（`252867e`）
- 文字三級對比度重定（WCAG AA+：正文 14.8:1、標籤 8.7:1、裝飾 4.7:1）
- 背景層次拉開（面板從底圖浮起），保留暗色 ops-room 氣質
- 八處誤用為裝飾灰的內容文字升級、字號下限 12px

### 7. 知識庫與文件
- `docs/references/`：13 份官方文件（FAA/NTSB/OIG/TRB/NASA），原文 PDF 已驗證
- `docs/lineage.md`：決策點 → 專業標準對照表（英文，答辯材料）
- `docs/advisory-lifecycle-design.md`：三路 Opus 設計彙整（人因/協議/劇本）
- `contact.md`：介面契約 v1.1（凍結）＋ §7 v1.2 提案

---

## 🔬 驗證狀態

| 項目 | 狀態 |
|---|---|
| 後端單元測試 | ✅ 212 passed（fakeredis、conflict tier 全分支、envelope、引擎規則、endpoints） |
| ruff format / check | ✅ 乾淨 |
| Dashboard 端到端 | ✅ 瀏覽器實測：面板渲染、地圖動畫、advisory 三行動、confirm→Redis key、機場切換、lineage、info popover、垂直捲動不裁切 |
| 前端 JS | 🟡 僅 `node --check` 語法檢查（無 DOM 測試框架） |
| **真實 OpenSky live 資料** | ❌ **從未實跑**——全程在 DEMO_MODE ＋ fixture 驗證 |

---

## ⬜ 還缺什麼

### A. 我（Bo-Ru）這邊待辦

| # | 項目 | 影響 | 優先 |
|---|---|---|---|
| A1 | **真實 OpenSky live 資料未實跑** | velocity 單位等只在 demo 模式驗證，接真資料行為未知 | 高 |
| A2 | **fixture 的 UAL412/AAL891 永遠違規** | 導致 cg 恆為 CRITICAL，蓋掉 DMO 對的 HIGH→CRITICAL 演進劇情。應改成正常航跡讓 DMO 對主導 | 高（影響 demo 敘事） |
| A3 | **Wave 3：replay 錄製 ＋ 離線重播** | demo 防呆 D9（斷網/OpenSky 429 時全離線重播）未做 | 高（demo 保險） |
| A4 | DEGRADED 横幅未在瀏覽器實測 | 邏輯有單元測試，但沒實際觸發 `/demo/degraded` 看畫面 | 中 |
| A5 | 前端無自動化測試 | 純 vanilla JS，要 Playwright E2E 才有 DOM 層保障 | 低 |
| A6 | Shelve / Agree 兩個行動 | v1.2 文件已設計，未實作（避免按鈕過多） | 低（roadmap） |
| A7 | `expire` kind 無自動觸發器 | 契約已定義，無 advisory 自動過期邏輯 | 低 |
| A8 | 依賴未 pin 版本 | 供應鏈衛生，黑客松階段不擋 | 低 |

### B. Katherine 整合線（6/19 整合測試前）

| # | 項目 | 狀態 |
|---|---|---|
| B1 | Katherine 確認契約 **v1.1**（三模組 schema 凍結） | ⏳ 待她點頭（原定 6/15 EOD） |
| B2 | Katherine 確認契約 **v1.2 提案**（advisory 生命週期，contact.md §7） | ⏳ 待確認：新欄位、reassess/lifecycle topic、advisory:state key、cooldown/timeout 常數、shift_event tier 欄位 |
| B3 | Orchestrator agent 實作 | ❌ 她尚未開始（目前 mock_katherine 代行） |
| B4 | Narrator agent 實作 | ❌ 她尚未開始（目前 mock 發罐頭→動態 briefing） |
| B5 | briefing 建議獨立 `briefing_id`（與 advisory_id 分離） | 📋 v1.2 提案項，待討論 |
| B6 | shift_event 加 `tier` 欄位（前端上真 tier 色） | 📋 已 mock-first 實作，待她正式採納 |
| B7 | 6/19 整合測試：mock 換真 agent 跑完整流程 | ⏳ 排定 |

### C. 關鍵日期

| 日期 | 事項 | 狀態 |
|---|---|---|
| 6/15 EOD | 三模組 schema 定版（v1.1） | ⏳ 待 Katherine 確認 |
| 6/16 EOD | Advisory output schema 確認 | ⏳ |
| 6/17 EOD | Handover briefing 格式確認 | ⏳ |
| 6/19 | 整合測試（mock 資料跑完整流程） | ⏳ 我方已就緒 |

---

## 🎬 Demo 驗收清單（D1–D10）現況

| # | Demo 步驟 | 狀態 |
|---|---|---|
| D1 | 開 dashboard、機場地圖＋即時飛機 | ✅ |
| D2 | 三個確定性訊號面板 | ✅ |
| D3 | 衝突浮現（callsign/sep/ttv） | ✅ |
| D4 | Advisory 卡（ESCALATE/SURFACE_CONFLICT 等四型） | ✅（mock 條件驅動） |
| D5 | 人決策（Acknowledge/Dismiss/Re-assess → Redis 稽核） | ✅ |
| D6 | 交班 briefing 渲染＋簽核 | ✅（mock 動態） |
| D7 | DEGRADED 斷線演示 | 🟡 有開關，未實測畫面（A4） |
| D8 | Lineage 依據對照表 | ✅（英文） |
| D9 | 離線 replay 防呆 | ❌ 未做（A3） |
| D10 | 免責聲明常駐 | ✅（sticky footer） |

**8/10 可演**；缺 D9（replay 防呆）與 D7 實測。

---

## 啟動方式（本地）

```bash
docker compose up -d                      # Redis
DEMO_MODE=1 python -m modules.runner      # 三模組 + demo 機隊
python -m fixtures.mock_katherine         # advisory/briefing 引擎（代 Katherine）
python -m dashboard.server                # → http://127.0.0.1:8800
```

導演開關（demo 時觸發劇情）：
```bash
curl -X POST http://127.0.0.1:8800/demo/workload_surge/on   # 推高人力壓力
curl -X POST http://127.0.0.1:8800/demo/sparse/on           # 稀疏空域（觸發訊號矛盾卡）
curl -X POST http://127.0.0.1:8800/demo/degraded/on         # 斷線演示（DEGRADED）
```
