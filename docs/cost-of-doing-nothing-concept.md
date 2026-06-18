# TowerGuard — The Cost of Doing Nothing: ATC Controller Staffing

*定稿：2026-06-13 · USAII Hackathon Challenge Brief 6 · Direction A · 研究所組*
*這份文件是 pitch 與 Devpost 的內容真相來源（取代原本的即時工具框架）*

---

## 重新定位（從即時工具 → 長期政策模擬器）

**舊**：即時航管塔台安全工具（秒級衝突偵測）。
**新**：**不作為代價模擬器**——若以目前速率持續不補管制員，未來 10 年的代價如何複利累積。

- **使用者**：FAA 人力規劃者、DOT 政策制定者、國會撥款者（＝ brief 的 policymakers / public-sector leaders）
- **社區連結**：每個有機場的社區都承受代價——航班延誤、區域經濟孤立、安全風險。把「航管人力」框成**公共安全勞動力投資**問題（brief 領域含 workforce development、public investment）
- **核心命題**：*The dashboard shows you the staffing gap now; this simulator shows you what doing nothing about it costs over 10 years.*

---

## 模擬模型（系統動力學 ODE — 這是 AI Reasoning 35% 的核心）

### Stock-and-flow 骨架

**存量（隨時間演化）**：
- `CPC` — 在崗合格管制員（真實數字：如 JFK 30/33）
- `Trainees` — 訓練中（2–3 年才認證）
- `CumOvertimeHours` — 累積加班債（錨點：全國 2.2M 小時）
- `FatigueIndex` — 0–1 過勞指數（人力越少累積越快）
- `CumCost` — 累積不作為代價（加班費＋延誤經濟成本＋安全風險曝險）

**流量**：
- `Hiring(t)` → 進 Trainees（**政策槓桿**）
- `Certification` = Trainees / certify_time → Trainees 轉 CPC（2–3 年延遲是關鍵）
- `Attrition` = CPC × base × **fatigue_multiplier(FatigueIndex)** → 離職（螺旋來源）
- `Retirement` → 退休（人口結構，近外生）

### 複利機制（非線性鉤子）：離職螺旋
人力少 → 人均加班升 → 過勞升 → 離職率升 → 人力更少。這是**增強迴路**；又因認證落後雇用 2–3 年，**晚補人＝補進一個還在變深的洞**——這就是「不作為」會複利而非線性累積的原因。

### 反事實對比（demo 的 money shot）
跑「**現在補 N 人 vs 拖 5 年**」：
- 10 年 CPC 曲線（拖的版本跌破安全線且回不來）
- 累積代價差距（兩條曲線間的面積＝等待的代價）
- 恢復滿編所需年數（拖延把 4 年變 8 年）

### 不確定性呈現（brief 明令：不准單點預測）
- **情境帶**：樂觀/基準/悲觀（attrition、retirement、certify_time 三組參數）
- **信賴區間**：Monte Carlo——對參數抽樣跑 1,000 條軌跡，畫 P10/P50/P90 扇形圖。**永遠不是一條線。**

### 模型類型／資料／評估（kill brief 的扣分項①）
- **類型**：系統動力學 ODE（4–5 條耦合差分方程，月步長）。不是黑箱 ML——每個參數可審計，正合 lineage 精神
- **校準資料**：FAA Controller Workforce Plan 2025–28（已在 repo）、BLS 該職離職率、學院產出量
- **predictive-analytics 規格**（評審要的）：inputs = 當前 CPC/trainee＋雇用排程；model = SD ODE；training signal = CWP 歷年人力；evaluation = 人力回測 RMSE＋敏感度
- **評估策略**：① 歷史回測（2020→2025 復現觀測到的下滑）② 敏感度龍捲風圖（哪個槓桿最關鍵）

### Lifecycle / drift（研究所差異化，kill 扣分項④）
- 每年新 CWP 出爐重新校準；追蹤回測 RMSE 跨版本趨勢
- **drift trigger**：實際人力偏離前次預測 P50 超過 X% → 觸發重擬（沿用既有 condition_key 閾值範式）

### Bypass 條件（kill 扣分項③）
模型何時**不該**被採信：政策劇變（強制退休年齡改變、國會大量招募法案）使校準的離職曲線失效 → 模型回 `OUT_OF_SCOPE`（鏡像既有 `data_unavailable → UNKNOWN` 紀律，不偽裝確定）。

---

## TowerGuard 資產重用對照

| 既有資產 | 重用為 |
|---|---|
| FastAPI/SSE/Leaflet dashboard | 換成情境時間軸／扇形圖視圖（新「Projection」分頁） |
| tier 引擎（含 UNKNOWN） | 重用「確定性+可審計+顯式 UNKNOWN」範式 → 不作為風險帶 |
| 人在迴路三行動 | Re-assess→「改假設重跑」（雙審查循環）；Dismiss+理由→「我否決這個假設」；Acknowledge→「已審閱未背書」 |
| **DEGRADED 誠實降級** | **最大可轉移強項**：資料失效時拒絕輸出代價數字、顯示 DEGRADED 而非自信的假投影 |
| lineage 依據面板 | 每條代價線連到證據源（CWP/BLS/Urban Institute） |
| info icons | 改寫成 model card（模型類型/輸入/校準/評估/假設/非目標） |
| 導演開關 | `/scenario/delay_5y`、`/scenario/funding_cut`、`/scenario/data_degraded` |
| 13 份文獻＋真實 FAA 數字 | 保留 FAA/NTSB/TRB；新增 BLS／GAO 人力成本 |

---

## Devpost 必填素材（草稿）

**Human-in-Loop（AI 不做的決策）**：
> AI 不決定要不要補人、補多少——它只量化「現在補 vs 拖延」的預期代價。撥公帑是價值判斷、要問責的決策，牽涉模型看不到的公平、政治、在地脈絡；模擬器讓取捨可見，不替人選。每個投影都由人審閱、可改假設重跑或否決前提。

**Responsible AI Guardrail（最大風險＋緩解）**：
> 風險——過度依賴／假精確：一個乾淨的代價數字（「拖 5 年花 $42M」）看起來權威，可能被當預測在預算戰裡引用。
> 緩解——系統永不輸出單一數字：每個輸出都是**帶信賴區間的範圍**、每條線**可追溯到來源與假設**、敏感度視圖顯示假設變動的影響；資料漂移或缺失時**拒絕投影、進入 DEGRADED**——fail loud 而非 fail silent。

**非目標**：① 不做撥款決策（只 inform）② 不做點預測（只有情境範圍）③ 不評分個人 ④ 不替你選贏家情境 ⑤ 非認證系統。

---

## Katherine 的兩個 agent 也要轉（排程風險，須儘早同步）

- **Orchestrator** → 情境仲裁：當兩組可信假設給出矛盾投影時，並排呈現請人判斷（沿用 SURFACE_CONFLICT 雙欄）
- **Narrator** → 從模擬 run 生成**政策摘要敘事**（取代交班簡報）：「在基準假設下，拖延 5 年的代價區間為……，主要驅動是離職螺旋」——只摘要已算出的結果，不預測不建議

---

## 7 天建置計畫

| 日 | 工作 |
|---|---|
| D1–2 | 編碼 FAA 參數＋5 方程積分器（numpy） |
| D3 | Monte Carlo wrapper → P10/P50/P90 扇形圖 |
| D4 | 回測（pre-2023 擬合、預測 2023–25、RMSE）＋敏感度龍捲風圖 |
| D5 | 現在補 vs 拖延反事實＋累積代價積分 |
| D6–7 | 把 Projection 分頁接進既有 dashboard（重用 tier-panel/lineage 元件）＋ OUT_OF_SCOPE bypass 守衛 |

**複雜度**：L（跨模組、換 domain 模型，但底盤架構不動）。
