# TowerGuard — 任務主導執行計畫（Bo-Ru 範圍）

*建立：2026-06-12 · 原則：任務主導、決策點對應既有 ATC 流程、邊際問題夠用就好*

---

## 核心敘事（評審答辯的軸線）

TowerGuard 不發明新流程。每個決策點都建立在**既有 ATC 專業流程**之上，只是加上現代化工具：

| 系統決策點 | 既有專業依據 | TowerGuard 現代化 |
|---|---|---|
| 分離標準（5NM 航路 / 3NM 終端 / 1000ft） | FAA JO 7110.65 ¶5-5-4（雷達最低間隔）＋ ¶4-5-1（垂直）；國際對照 ICAO Doc 4444 | ADS-B 即時外推自動比對 |
| 衝突偵測與分級 | STARS/ERAM Conflict Alert（SKYbrary: STCA） | 開放資料重現 + tier 透明規則 |
| 人在迴路、AI 不決策 | FAA JO 7110.65 ¶2-1-2（Duty Priority） | Parasuraman 第 1–2 階明確切線 |
| 交班簡報格式 | FAA JO 7110.65 ¶2-1-24（Transfer of Position Responsibility）＋ JO 7210.3 ¶2-2-4 | LLM 草擬 + 管制員確認簽核 |
| 人力負載評估 | FAA staffing 標準 | 即時加權指數化 |
| 整體系統 | NASA ATD-2/IADS（NTRS 20205006383，最接近前身） | 整合進單一管制員介面 + LLM 敘事 |

→ Wave 0 任務 W0-2 把這張表擴寫成 `docs/lineage.md`，是 demo 第 8 步的素材。
→ 依據原文已下載到 `docs/references/`（含索引 README），引用段落已對本地 PDF 驗證。

---

## Demo 驗收清單（5–8 分鐘 script，每步一個交付物）

| # | Demo 步驟 | 驗收標準 |
|---|---|---|
| D1 | 開 dashboard、選密集機場（JFK/EWR/BOS/ATL） | 地圖顯示 ≥10 架即時 ADS-B 飛機 |
| D2 | 展示三個確定性訊號面板 | 三面板都顯示 60 秒內的最新 tier + 關鍵欄位 |
| D3 | 衝突浮現 | 面板顯示 callsign 配對、projected vs ICAO 分離、time_to_violation |
| D4 | 「AI 建議、人決策」advisory 卡片 | 卡片顯示 action/severity/summary + human_override_required |
| D5 | 管制員按 Confirm | Redis `towerguard:confirmed:{id}` 寫入時間戳，UI 顯示已確認 |
| D6 | 交班簡報渲染 | 五個 section 全渲染 + Confirm 按鈕 |
| D7 | 「資料斷了怎辦」 | 斷線 → DEGRADED 顯示，**絕不**顯示 LOW |
| D8 | 「不是憑空發明」lineage 對應表 | 每個決策點都有具名標準依據 |
| D9 | Replay 防呆 | 全程可離線從錄製 fixture 重播 D1–D7 |
| D10 | 免責聲明 | 每個畫面都有「非認證 ATC 系統」banner |

---

## 任務波次（複雜度 S/M/L = 單檔 / 多檔 / 跨模組）

### Wave 0 — 地基 + 契約鎖定（6/15 前完成）

| 任務 | 內容 | 複雜度 |
|---|---|---|
| W0-1 | Repo 骨架：`modules/` `dashboard/` `data/` `fixtures/` `tests/` + `config.py`（機場清單、Redis、OpenSky 憑證） | S |
| W0-2 | `docs/lineage.md`：既有流程 → TowerGuard 對應表（上表擴寫，含引用） | M |
| W0-3 | Katherine 確認契約 v1.1（含 shift_events Stream 由她的 Orchestrator XADD） | S |
| W0-4 | `modules/envelope.py`：共用 envelope 建構 + schema 驗證 + alert_id 遞增；強制 `data_unavailable→tier=UNKNOWN` | M |

### Wave 1 — MVP（≈ overview 的 10 天最小版；獨立可 demo D1-D3、D7、D10）

| 任務 | 內容 | 複雜度 |
|---|---|---|
| W1-1 | `data/opensky.py`：bounding box 拉 state vectors，429/token 過期 → 往上拋 data_unavailable，不 retry storm | L |
| W1-2 | `modules/traffic_density.py`：50NM 計數 + 變異 + score→tier（§2a 對照） | M |
| W1-3 | `modules/conflict_geometry.py`：120s 成對外推、ICAO 比對、五條 tier 規則（每條都有單元測試） | L |
| W1-4 | `modules/workload_index.py`：mock/設定檔輸入 + 加權 score→tier | M |
| W1-5 | `modules/runner.py`：60 秒迴圈發布三個 pub/sub topic | M |
| W1-6 | Dashboard 核心：地圖、三 tier 面板、DEGRADED 渲染、免責 banner（✅ 已完成；技術從 Streamlit 改為 FastAPI/SSE + 純 HTML/CSS + Leaflet，transitions.dev 動畫紀律 + prefers-reduced-motion） | L |

### Wave 2 — 整合面（讓 6/19 能跑；mock 解耦 Katherine）

| 任務 | 內容 | 複雜度 |
|---|---|---|
| W2-1 | Advisory 卡片元件（訂閱 `towerguard:advisory`；SUPPRESS 不顯示） | M |
| W2-2 | Confirm 按鈕 → `SET towerguard:confirmed:{id}`，讀回顯示狀態（確認狀態以 key 為準，不信 advisory JSON 欄位） | S |
| W2-3 | Briefing Markdown 渲染器（§4 格式 + Confirm 接 W2-2） | M |
| W2-4 | **mock Katherine**（`fixtures/mock_katherine.py`）：發契約合規的 advisory + briefing → dashboard 完全不依賴她的進度 | M |

### Wave 3 — Demo 硬化（6/19 後）

| 任務 | 內容 | 複雜度 |
|---|---|---|
| W3-1 | Session recorder：錄下 live run（OpenSky frames + 全部事件） | M |
| W3-2 | 離線 replay 模式：`REPLAY=1` 全程無網路跑 D1–D7 | L |
| W3-3 | 精選 demo fixture：保證台上一定出現 CRITICAL 衝突 + advisory | M |
| W3-4 | 視覺打磨：tier 配色、刷新指示、lineage footer | S |

---

## 與 Katherine 的整合點

**她依賴我們（6/15–6/19 必須就位）：** 三模組 schema（6/15 凍結）、三個 topic 的 live 事件、`confirmed` key。
**我們依賴她（全部可 mock，永不卡）：** advisory JSON（D4）、briefing Markdown（D6）→ W2-4 解耦。
**解耦規則：** 6/19 把 mock 發布者換成她的真 agent，雙方守契約的話只是改 config，不改 code。

| 里程碑 | 我們要完成 |
|---|---|
| 6/15 EOD | Wave 0 全部 + schema 凍結 |
| 6/19 | Wave 1 + Wave 2 全部（整合測試） |
| Demo 日前 | Wave 3 |

---

## Mock 資料策略

一套 schema 服務三種模式：**live / 整合 mock / 離線 replay**。所有讀 Redis 的東西在三種模式下行為相同，dashboard 分不出來。精選 fixture（W3-3）保證台上的衝突橋段一定發生，不賭當天空域。

## 風險（只列影響 demo 成敗的）

| 風險 | 防呆 |
|---|---|
| OpenSky 429/token 過期 | Replay 模式 + 精選 fixture；彩排用 replay 跑 |
| Schema 漂移導致 6/19 整合失敗 | 單一 envelope builder + 驗證器（W0-4），雙方對 §2 驗證 |
| Live demo 時剛好沒有衝突 | 精選 fixture 保證 D3 橋段 |
| DEGRADED 被誤顯示成 LOW | 驗證器強制 + D7 專測 |
| Demo 現場沒網路 | Replay 全離線 |

**明確不做（邊際完美主義）：** OpenSky 重試退避精緻化、多機場同時串流、登入/多使用者、demo 之外的持久化、production 級錯誤分類。
