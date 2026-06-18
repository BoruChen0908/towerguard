# TowerGuard — 完整執行計畫與研究證據庫

*建立：2026-06-17 · 截止：2026-06-21 23:59 ET · 團隊：Bo-Ru + Katherine*
*比賽：USAII Global AI Hackathon 2026 · Graduate Track · Challenge Brief 6 Direction A*

---

# PART I — 計畫概要

## 1. 重新定位

### 舊定位（原 TowerGuard 即時系統）
即時 ATC 決策輔助系統——幫管制員偵測衝突、排序工作量、生成交班敘事。

### 新定位（TowerGuard）
**ATC 人力危機的「不作為代價」模擬器**——幫政策制定者看到：如果繼續不補人，5年後美國的天空會怎樣？每延遲一年介入，要多付多少錢、多承受多少安全風險？

### Domain Fit 證據
- Brief 6 Direction A 明列 **workforce development** 為 possible domain
- ATC staffing crisis 完全符合 "model the long-term social and economic cost of delayed or absent intervention"
- 認領 Optional Extension: **Diagnostic Delay & System Bottlenecks**（FAA 招募管線充滿瓶頸）

---

## 2. Scope、Non-Goals、Stakeholders

### Scope
- 模擬美國 ATC 人力管線在不同政策情境下 2026–2036 的軌跡
- 量化每個情境的經濟成本和安全風險指標
- 比較「現在介入 vs 延遲介入」的累積成本差距
- 以互動式 dashboard 呈現，附 LLM 生成的 policy brief

### Non-Goals
- **不是即時航班監控系統**——即時模組只作為模型驗證層
- **不做個別設施的排班決策**——模型是戰略/政策層級
- **不預測具體事故**——安全輸出是機率風險指標
- **不取代 FAA 的 CRWG/AFN 模型**
- **不設定「可接受風險水準」**——那是政策/倫理判斷

### Stakeholders
| 層級 | 使用者 | 他們從系統得到什麼 |
|---|---|---|
| 政策層 | 國會撥款委員會、FAA 高層 | 情境比較、cumulative cost gap、policy brief |
| 管理層 | FAA 設施管理者 | 設施層級的 staffing gap 預測、瓶頸識別 |
| 驗證層 | 分析師、研究者 | 模型假設透明度、sensitivity analysis |
| 社區層 | 機場依賴型城市經濟發展機構 | 區域經濟影響估計 |

---

## 3. 系統架構

### 四層架構
```
DATA LAYER → MODEL LAYER → AI LAYER → PRESENTATION LAYER
```

**Data Layer**: FAA CWP PDF · GAO Reports · BTS/ASPM · OpenSky ADS-B
**Model Layer**: Workforce Stock-Flow (SD) · Economic Impact · Safety-Risk
**AI Layer**: Scenario Engine · Causal Explainer · Policy Brief Narrator
**Presentation Layer**: Scenario Dashboard · Intervention Timing Comparator · Live Validation

### 架構決策的研究依據
> **為什麼選 System Dynamics 作為核心？**
> 研究發現 SD 是安全關鍵產業人力規劃的主流方法。英國 Centre for Workforce Intelligence (CfWI, 2010-2016) 用 SD 建了國家醫療人力規劃框架，描述為 "linking the states of training and categories of staff... recruitment and training delays, meeting targets for staff in posts and coping with drop outs, leaving and retirement flows"——跟 ATC pipeline 幾乎一模一樣。2023 PMC10349158 系統性文獻回顧確認 SD 是現代健康人力規劃中最常用的分析方法。
>
> **為什麼不用純 Agent-Based 或 Discrete Event？**
> ABM 適合看個人決策異質性（個別管制員是否轉調/退休），但更需要數據、更難校準。DES 適合流程細節（Academy 排課、醫檢排隊），但不是策略層工具。ISPOR SIMULATE task force 強調「問題應決定方法」，我們的問題是 aggregate workforce pipeline → SD 最適合。
>
> **為什麼加 Monte Carlo？**
> ISPOR good-practice 標準要求報告 distributions 而非 point estimates。Brief 6 的 common mistakes 明確寫「single-point predictions without scenario ranges or confidence intervals — policy models must represent uncertainty」。
>
> **為什麼不存在已發表的 FAA ATC 動態模擬模型？**
> 美國國家科學院 (Transportation Research Board) 2025 年 6 月報告批評 FAA 的現有 AFN/CRWG 模型是靜態試算表，呼籲改用動態建模。我們的專案正好填補這個空缺。

---

## 4. 從現有 TowerGuard 複用什麼

| 現有元件 | 新角色 | 改動程度 |
|---|---|---|
| Workload Index Module | Live Validation panel | 不改 |
| Conflict Geometry Module | Live Validation panel | 不改 |
| Traffic Density Module | Live Validation panel | 不改 |
| OpenSky Client + Redis | 即時數據串接 | 不改 |
| Dashboard (FastAPI/SSE/Leaflet) | 改框架為 Scenario Dashboard | 大改前端 |
| Lineage Panel | 改為 Assumption Ledger | 擴充 |
| DEMO_MODE | Live Validation 的 replay | 微調 |

**估計複用率：後端 ~60%，前端 ~30%**

---

## 5. 需要新建什麼

| # | 新元件 | 優先級 | 複雜度 |
|---|---|---|---|
| N1 | Workforce Stock-Flow Model | P0 | L |
| N2 | Scenario Engine (5 scenarios + timing) | P0 | M |
| N3 | Monte Carlo Wrapper | P1 | M |
| N4 | Economic Impact Module | P0 | M |
| N5 | Safety Risk Module | P1 | S |
| N6 | Scenario Dashboard 前端 | P0 | L |
| N7 | Intervention Timing Comparator UI | P0 | M |
| N8 | LLM Policy Brief Generator | P1 | M |
| N9 | LLM Causal Explainer | P2 | M |
| N10 | LLM Data Integration Pipeline | P2 | M |
| N11 | Sensitivity + Tornado Chart | P1 | S |
| N12 | Assumption Ledger UI | P1 | S |
| N13 | CLD 視覺化 | P1 | S |

**最小可 demo = P0 only (N1+N2+N4+N6+N7) + Live Validation (existing)**

---

## 6. 四天執行計畫

### Day 1 (6/17)：Model Core
- N1: Stock-flow model → `models/workforce_sd.py`
- N4: Economic impact → `models/economic_impact.py`
- N2: Scenario engine → `models/scenario_engine.py`
- **驗收**：terminal 跑 5 scenarios 輸出 10 年曲線 + cost 數字

### Day 2 (6/18)：Dashboard + Timing
- N6: Scenario dashboard (Chart.js)
- N7: Intervention Timing Comparator (slider)
- N3: Monte Carlo → fan charts
- 整合 Live Validation panel
- **驗收**：瀏覽器完整 dashboard + slider 互動

### Day 3 (6/19)：AI + Polish + 文案
- N8: LLM Policy Brief
- N11: Sensitivity + tornado
- N12: Assumption Ledger
- N5: Safety risk module
- 所有 Devpost 欄位文案
- **驗收**：完整 demo flow 頭到尾跑通

### Day 4 (6/20)：Video + Submit
- 錄 3-5 分鐘 pitch video
- Bug fix + 連結測試
- Devpost 提交（deadline 6/21 23:59 ET）

---

# PART II — MODEL LAYER 詳細設計與證據

## 7. Workforce Stock-Flow Model

### 7.1 五個 Stock

| Stock | 定義 | 校準值 | 來源 |
|---|---|---|---|
| S1: Applicants | 應徵者池 | FY2017-2022 累計 106,533 (Track 1) | GAO-26-107320 |
| S2: Academy Trainees | FAA Academy 學員 | FY2025 入學 ~2,028 | FAA CWP 2026-2028 |
| S3: Developmentals | 訓練中管制員 | ~4,000 (截至 April 2026) | FAA/Reuters |
| S4: CPCs | 認證管制員 | ~11,000 (21 世紀新低) | FAA CWP 2026-2028 |
| S5: Total Controllers | 全體管制員 | 13,164 (FY2025 end) | GAO-26-107320 |

> **證據：歷史趨勢**
> GAO 審計端點：14,007 (FY2015) → 13,164 (FY2025)，十年跌 6%。
> GAO 原文：「FAA employed 14,007 controllers at the end of fiscal year 2015 and 13,164 at the end of fiscal year 2025, a decrease of about 6 percent.」
> 同期航班量從 28.1M (FY2015) 增加到 30.8M (FY2024)，+10%。
> 意味著每個管制員負責的航班量增加了 ~17%。

### 7.2 七條 Flow 與校準數據

| Flow | 路徑 | 校準值 | 來源 |
|---|---|---|---|
| F1: Hiring | → Academy | 2,200/yr (FY26), 2,300 (FY27), 2,400 (FY28) | FAA CWP |
| F2: Academy Grad | Academy → Dev | 畢業率 ~70% (washout ~30%) | GAO |
| F3: Certification | Dev → CPC | 耗時 2-6 年 | FAA/National Academies |
| F4: Aging | CPC → Eligible | 年齡 > ~50 | BLS |
| F5: Retirement | Eligible → out | ~400 被留任 (FY2025, $12.3M bonus) | FAA CWP |
| F6: Resignation | CPC → out | 包含在總流失 1,460 (FY2025) | FAA |
| F7: Training Attrition | Academy/Dev → out | Dev: 201/yr projected (was 102/yr avg) | FAA CWP |

> **證據：招募漏斗全貌 (GAO-26-107320, FY2017-2022 Track 1)**
> 這是最關鍵的一組數據——揭示了整條管線的效率：
>
> | 階段 | 人數 | 流失率 |
> |---|---|---|
> | 申請 | 106,533 | — |
> | 考能力測驗 (ATSA) | 32,615 | -69% |
> | 收到暫定錄取 | 9,107 | -72% |
> | 接受錄取 | 8,442 | -7% |
> | 通過體檢+安全審查 | 4,619 | -45% |
> | 進入 Academy | 3,964 | -14% |
> | 完成 Academy | 2,610 | -34% |
> | 認證/在職訓練 | 2,258 | -14% |
>
> **淨轉換率：申請到認證 ≈ 2%**
> 62% 被邀請者從未去考 ATSA。14% 收到最終 offer 後拒絕。
> ATSA 85+ 分的認證率 29% vs 80-84.9 分的 9%。CTI 畢業生成功率 41% vs 非 CTI 22%。
>
> **體檢瓶頸**：心理評估平均等待超過 2 年，截至 2024 年 8 月約 1,200 人卡在此環節。

> **證據：COVID 對管線的衝擊**
> FAA Academy 在 2020 年停訓 4 個月，2021-2022 恢復但顯著減量。
> FY2021 僅招 ~500 人（目標 910）。
> 2025 年 shutdown 導致 400-500 學員退出。
> GAO：「FAA's hiring pipeline was interrupted as it suspended training at the FAA Academy for 4 months in 2020 due to the COVID-19 pandemic and then resumed training at significantly reduced rates during 2021 and 2022.」

> **證據：加班數據**
> National Academies (via Reuters)：「The FAA air traffic control workforce in 2024 logged 2.2 million hours of overtime costing $200 million. Annual overtime is up 308% per air traffic controller, or 126 hours per year since 2013, to 167 hours on average.」
> 2026 年 2 月國會致 FAA 信：超過 41% 的 CPC 每週工作 6 天、每天 10 小時，士氣歷史低點。

### 7.3 三條回饋迴路

> **R1 — Burnout Spiral（正回饋/惡性循環）**
> ```
> CPC 不足 → 強制加班 → 疲勞累積 → 錯誤率↑ + 離職率↑ → CPC 更不足
> ```
>
> **回饋迴路的學術依據：**
> Frontiers in Public Health (2023, PMC10687398) 用 Causal Loop Diagram 建模了職業燃盡的正回饋迴路：「Several reinforcing feedback loops resulting in an increase of the prevalence of burn-out were identified in which the factors (very) high workload, imbalance between work and private life, and insufficient recovery time play an important role.」
>
> MDPI Systems (2026) 的 Burnout Risk Management Framework 進一步建模了 Reinforcing Loop R1（疲勞循環）：「increased Workload generates an accumulation of Emotional Exhaustion. This state leads to an erosion of Operational Effectiveness... reduced productivity results in Backlog Accumulation, which secondarily increases the pressure on the team, closing the 'vicious cycle' of systemic collapse.」
>
> Sterman (2001) Business Dynamics 是 SD 建模的經典教科書。
>
> **非線性特性：**
> SAFTE-FAST 模型閾值：效能分數 77% = 清醒 18.5 小時 = BAC 0.05%。
> 低於 77% 後 impairment 非線性上升。
> 巴西航空研究 (arXiv 2201.05438)：30 天內夜班從 1 增到 13 時，相對疲勞風險上升 23.3% (95% CI 20.4-26.2%)。

> **R2 — Knowledge Drain（正回饋/知識流失）**
> ```
> 資深CPC流失（離職/晉升/退休）→ 可用訓練教官↓ → Dev認證速度↓ → CPC補充延遲
> ```
> **此迴路不依賴「退休潮」**：退休 2007 已達峰、前向低且下降（見 §10.3 校正）。驅動力是廣義的資深流失（離職、晉升轉管理、調職、退休）加上既有的教官短缺。
> DOT OIG 審計指出 FAA 面臨合格 ATC 教官短缺。
> 認證時間最複雜設施可達 4-6 年，調職重新認證 12-18 個月。

> **B1 — Load Shedding（負回饋/代價高昂的制衡）**
> ```
> CPC 不足 → 流量管制 → 航班減少 → 工作量暫降（但經濟損失激增）
> ```
> 2025 shutdown 實例：FAA 在 40 機場逐步減班 4%→6%→8%→10%。
> A4A 估計 10% 減班時每日經濟影響 $2.85-5.8 億。

---

## 8. Economic Impact Module

### 8.1 成本層次與數據來源

| 成本類別 | 金額 | 來源 |
|---|---|---|
| 年度加班 | $2 億 (2024) | National Academies/Reuters |
| 年度延誤總成本 | $330 億 (2019) | FAA/Nextor via A4A |
| 每分鐘 block time | $100.76 (2024) | A4A delay cost dataset |
| 旅客時間價值 | $47/hr | FAA recommended value |
| 旅客年度延誤成本 | $180 億 (2026 est.) | FAA research |
| Shutdown 每日影響 | $2.85-5.8 億 | A4A (Nov 2025) |
| 全球航班擾亂 | $675 億 | AirHelp (2022) |

> **證據：延誤成本的分解**
> UC Berkeley/NEXTOR 研究 (Hansen et al., FAA-commissioned, 2010)：
> 2007 年延誤成本 $329 億 = 航空公司 $83 億 + 旅客 $167 億（「just over half」）+ 流失需求 $39 億 + GDP $40 億。
>
> A4A：「In 2024, the average cost of aircraft block (taxi plus airborne) time for U.S. passenger airlines was $100.76 per minute. Labor costs rose 7.8 percent to $35.23 per minute. Fuel costs declined 11.3 percent to $33.06 per minute.」
>
> Eurocontrol 發布按機型和延誤長度分類的每分鐘邊際延誤成本（如 B747-400 長延誤 €289/min）。

> **證據：Shutdown 量化**
> A4A 參議院證詞 (Nov 2025)：
> 「When the FAA flight-reduction order reaches 10% on Nov. 14, A4A estimates a daily average U.S. economic impact of $285M–$580M.」
> 前 29 天僅取消 11 班（controller staffing），之後 9 天取消 1,271 班（含 11/7 的 865 班）。
> 超過 400 萬旅客受影響。
> Controller staffing 從佔 NAS 延誤的 5%（正常）飆升到 61%（shutdown 期間）。

### 8.2 ASCE "Failure to Act" 前例

> **證據：基礎設施版的 Cost of Doing Nothing**
> ASCE Failure to Act 系列計算：放任基礎設施惡化 → $3.1 兆經濟產出損失 + 350 萬工作流失。避免代價：額外投資 $1.1 兆。
> 方法論核心：**gap analysis + cascading impact**——投資缺口 → 設施劣化 → 下游傳導 → GDP 影響。
> 國會聽證會 (2019)："The Cost of Doing Nothing: Why Investing in Our Nation's Infrastructure Cannot Wait"
> 具體例子：Brent-Spence 橋每延遲一年動工，成本增加 $7,500-8,500 萬/年。
>
> **直接套用到 ATC**：CPC 缺口 → 流量管制 → 延誤 → 航空公司+旅客成本 → 區域 GDP 影響。每一層都有上述真實乘數。

---

## 9. Safety-Risk Projection Module

### 9.1 DCA 事故作為錨定點

> **證據：NTSB DCA 最終報告 (Jan 2026)**
>
> Probable cause（原文）：
> 「the FAA's placement of a helicopter route in close proximity to a runway approach path, their failure to regularly review and evaluate helicopter routes and available data, and their failure to act on recommendations to mitigate the risk of a midair collision near Ronald Reagan Washington National Airport.」
>
> Controller workload 相關發現：
> 「the tower team's loss of situation awareness and degraded performance due to the high workload of the combined helicopter and local control positions and the absence of a risk assessment process to identify and mitigate real-time operational risk factors.」
>
> 關鍵細節：
> - 一個管制員同時管飛機和直升機頻率（被認定為 "not normal"）
> - DCA 塔台 2018 年被降級 → 降薪 → 高離職率
> - NTSB 找到 "make it work" 文化，正常化了不安全操作
> - NTSB Chair Homendy：「100% preventable」
> - 67 人死亡，23 年來最嚴重美國商業航空事故

### 9.2 近接事件趨勢

> **證據：**
> FY2023：19 起嚴重近接（Category A/B runway incursions），七年最高。
> FY2022-2023：23 起嚴重機場近接。
> FY2024：9 起嚴重近接（A/B 率從 0.435 降至 0.117 per million ops，-73%）。
> 參議院聽證 (2023/11)，Duckworth：「Our nation is experiencing an aviation safety crisis with near misses that are happening way too frequently.」
>
> **重要建模警告**：近接事件是稀有事件（Category A+B ≈ 0.00004% of operations），統計噪訊大。
> 模型必須將安全輸出視為機率性風險指標，配帶寬大的信賴區間，**不能**當作確定性事故預測。

### 9.3 SAFTE-FAST 疲勞模型

> **證據：**
> SAFTE-FAST (Sleep, Activity, Fatigue, and Task Effectiveness — Fatigue Avoidance Scheduling Tool; Hursh et al., 2004) 是 FAA 認可的生物數學疲勞模型。
>
> 關鍵閾值：
> - 效能分數 77% = 清醒 18.5 小時 = BAC 0.05%（FAA 疲勞風險線）
> - Federal Railroad Administration 使用 ≤70% 為閾值
> - Reservoir score 75% = 少睡 8 小時
>
> 支持科學：
> - Van Dongen, Maislin, Mullington & Dinges (2003)：睡眠限制的累積劑量反應
> - Williamson & Feyer：17 小時清醒 ≈ BAC 0.05%
>
> FAA 疲勞專家面板 (2024/04/19)：114 頁報告，結論「the science is clear that controller fatigue is a public safety issue」。四個優先建議含 10-12 小時班間休息。FAA 分析發現 FY2024 排班中超過 4,000 次疲勞規則違規。

### 9.4 設施層級缺人數據

> **證據：**
> 2023 DOT OIG：26 個關鍵設施中 20 個低於 85% 編制目標。
> 2024 年 9 月：290 個終端設施中超過 40% 缺人。19 個最大設施 ≥15% 低於目標。
> 最缺人：Grand Forks Tower (53.3% of target)。
> New York TRACON (N90)：113 CPCs，約目標的一半。
> 這些大型缺人設施處理 27% 商業航班和 40% 延誤。
> Transportation Research Board：約 30% 設施低於目標 10%+，另 30% 高於目標 10%+。

---

## 10. Scenario Design

### 10.1 五個情境

| 情境 | 描述 | 校準依據 |
|---|---|---|
| **Baseline** | FAA CWP 2026-2028 軌跡 | CPC+CPC-IT 11,686 (FY2024 實際) → 12,691 (FY2028 預測) |
| **Do Nothing** | 凍結在 FY2021 水準 (~500/yr) | COVID 期間實際數據 |
| **Current Plan** | 新目標 12,563 CPC + 效率改善 | FAA CWP 2026-2028 |
| **Accelerated** | 最大 Academy 產能 + CTI + 留任 + TSS | TSS 可縮短認證時間 27% |
| **Disruption** | 重現 shutdown 衝擊 | 2025 實際數據 (400-500 學員流失) |

### 10.2 Intervention Timing Comparator

> **設計原理：Brief 6 Direction A 的核心要求**
> 原文：「if we invest X now vs. in 5 years, what is the projected difference?」
>
> 使用者選介入方案 → 拉 slider 選起始年 (2026-2030) → 系統顯示：
> 1. CPC 軌跡分歧
> 2. 累積成本差距（area between curves）
> 3. Safety risk window（低於 85% 的月數）
> 4. Net cost of delay = 晚做的總成本 - 早做的總成本
>
> **延遲成本的數學原理（來自研究）：**
>
> **Stern Review 框架**（延遲行動的代價）：「The benefits of strong, early action ... outweigh the costs.」延遲讓問題更難逆轉（正回饋迴路 + 不可逆的管線時滯）。
> **但我們模型的實際結果不是「指數級」,是「近乎線性」**：每延一年介入,累積代價多約 **$70B**(2027/28/29/30 才起步 = 相對 2026 +$70B / $139B / $206B / $271B)。為什麼不是指數爆炸?因為**工作力崩潰雖然非線性,但年度經濟成本封頂在崩潰天花板**(見 N4 / D17),把「美元表現」攤平成大致每年一個固定量。誠實講:這是個「**穩定計費表,每年 ~$70B**」而非「指數炸彈」;而且因為有封頂,它是**保守下限**,真實代價可能更高。這條曲線對天花板的選擇不敏感(2×/3×/5× 都給同一條),所以結論不靠那個假設。
>
> **Social Discount Rate**：用來將未來成本折算回現值。SDR 的選擇是關鍵假設——Stern 用 1.4% (偏低，看重未來)，Nordhaus 用 ~5% (偏高，看重現在)。差異巨大。
> 我們的模型應呈現不同 SDR 下的結果，作為 sensitivity analysis 的一部分。
>
> **ASCE 延遲成本的具體例子**：
> Brent-Spence 橋：每延遲一年，成本增加 $7,500-8,500 萬。
> 全國基礎設施：$2 兆投資缺口 → $10 兆經濟損失（10 年）。
>
> **為什麼延遲代價真實且持久（機制）**：
> - **管線時滯**：今天招的人 2-3 年後才上線 → 晚 1 年招 = 晚 3-4 年才有 CPC（延遲代價的主因，每年一截）
> - **知識流失不可逆**：資深 CPC 流失（離職/晉升/退休，非單一「退休潮」——見 §10.3 校正）帶走的經驗無法快速重建
> - **R1 燃盡螺旋**使工作力崩潰本身非線性；但在保守的成本封頂(D17)下,延遲的「美元」代價攤平成大致 ~$70B/年
> - **安全閾值是 cliff**：低於 85% 編制 → 流量管制激增；其經濟代價在模型中封頂(保守),所以總體呈線性而非指數

### 10.3 Tipping Points

| 臨界點 | 閾值 | 後果 |
|---|---|---|
| 設施編制 85% | CPC < CRWG target × 0.85 | 流量管制指數級增加 |
| SAFTE-FAST 77% | 效能 < 0.77 | Impairment ≈ BAC 0.05% |
| 加班飽和 | 持續 6-day/10-hr weeks | 觸發 R1 正回饋 |

> **關於「退休懸崖」（已校正，2026/6 研究）**：常被引用的 PATCO 退休潮在我們的時間窗（2026–2036）內**不適用**——退休 2007 已達峰（828/年），前向退休低且持續下降（FY2024 底僅 463 人符合資格、未來 4 年預計退 ~819 人 ≈ 205/yr，2030 前降到 ~236/yr），勞動力偏年輕（26–43，近 10–15 年招募）。今天的集中流失來自**燃盡螺旋（R1）+ 認證管線追不上 + OJT 漏損**,不是退休潮。把這點講清楚反而更站得住，也是模型的實際依據（見 calibration D12）。

---

# PART III — AI LAYER 詳細設計與證據

## 11. 為什麼需要 AI（回應 35% 評分權重）

> **Brief 6 評分結構**：
> AI Reasoning 35%：「Architecture tradeoffs explained, evaluation strategy mentioned, justified approach」
>
> **Brief 6 列出的可用 AI 能力**：
> Predictive modeling and simulation systems · Optimization models and causal inference · Systems dynamics modeling · Data integration pipelines · Explainable AI (XAI) and scenario modeling
>
> **Common Mistake to avoid**：
> 「'Predictive analytics' without specifying inputs, model type, training signal, and evaluation metrics」

### 11.1 六個 AI 角色

| # | 角色 | AI 技術 | 為什麼 Excel 做不到 |
|---|---|---|---|
| 1 | Data Integration | LLM + Pydantic schema extraction | FAA CWP 是 PDF，每年格式微調 |
| 2 | Causal Explainer | LLM causal pathway tracing | SD 模型輸出是數字，非技術者看不懂回饋迴路 |
| 3 | Policy Brief Narrator | LLM structured report generation | 5 scenarios × 3 dimensions 的比較，手動太慢 |
| 4 | Sensitivity Narrator | LLM parameter importance analysis | Monte Carlo 500 次結果需要自動化解讀 |
| 5 | Counterfactual | LLM historical divergence narrative | 反事實需追蹤多條因果鏈 |
| 6 | NL Query Interface | LLM → parameter modification → re-run | 「如果 Academy 淘汰率降到 20%？」 |

### 11.2 AI Role #1: Data Integration Pipeline

> **證據：LLM 結構化數據抽取的成熟度**
>
> Simon Willison (2025/02)：「Structured data extraction is a killer app for LLMs — I've suspected for a while that the single most commercially valuable application of LLMs is turning unstructured content into structured data.」
>
> OpenAI, Anthropic, Gemini, Mistral 都提供 structured output API。
>
> Cleanlab TLM 提供 trustworthiness score：「you can let LLMs automatically process the documents where they are trustworthy and automatically detect which remaining LLM outputs to manually review.」
>
> LlamaIndex：「you can get an LLM to read natural language and identify semantically important details such as names, dates, addresses, and figures, and return them in a consistent structured format regardless of the source format.」
>
> **應用到我們的場景**：
> - 輸入：FAA CWP 2026-2028 PDF
> - LLM 抽取：hiring targets, attrition estimates, facility staffing tables
> - 輸出：JSON with confidence scores
> - 自動比對前一版 CWP → 標記顯著變動 → 觸發 drift detection

### 11.3 AI Role #2: Causal Explainer (XAI)

> **證據：XAI 在政策工具中的應用**
>
> ML 模型的 XAI (SHAP/LIME) vs SD 模型的 XAI 不同。
> SD 模型天生是「白盒」（方程式透明），但輸出行為的因果鏈路可能不直觀（因為回饋迴路和延遲）。
>
> 我們的 XAI 是 **causal pathway tracing**：
> LLM 沿回饋迴路走一遍，用人話解釋非直覺的行為。
> 例：「為什麼 Accelerated scenario 短期 CPC 反而下降？」
> → 「因為 Academy 容量瓶頸：大量湧入的新學員拉高了淘汰率，同時佔用 developmental 的訓練資源。」
>
> **Robust Decision Making (RDM)** 框架：
> 「Robust decision methods seem most appropriate under three conditions: when the uncertainty is deep, when there is a rich set of decision options, and the decision challenge is sufficiently complex that decision-makers need simulation models to trace the potential consequences of their actions over many plausible scenarios.」

### 11.4 AI Role #3: Policy Brief Narrator

> 每次 scenario run 生成結構化 policy brief：
> - Executive Summary（1 段）
> - Key Findings（3-5 bullet）
> - Scenario Comparison（表格 + 解讀）
> - Cost of Delay Analysis（timing comparator 結果）
> - Recommendations（帶 uncertainty caveat）
> - Assumptions & Limitations

### 11.5 Causal Inference 方法論

> **證據：反事實推理在政策評估中的應用**
>
> Synthetic Control Method (Abadie et al.)：用控制組加權平均建構反事實。被稱為「arguably the most important innovation in the policy evaluation literature in the last 15 years」(Athey & Imbens 2017)。
>
> Difference-in-Differences (DiD)：比較 treatment 前後和 control 組的差異。
>
> Synthetic Difference-in-Differences (SDID)：結合 SCM 和 DiD 的優點。
>
> **在我們的模型中**：
> 不是用 SCM 做因果推斷（我們沒有 treatment/control），而是用 SD 模型做 **counterfactual simulation**：
> 「如果 2020 年 COVID 沒有中斷 Academy → 管線狀態會是什麼？」
> 這是 model-based counterfactual，不是 data-based counterfactual。

### 11.6 ML 預測離職

> **證據：**
> Scientific Reports (2026/02)：「a comprehensive framework that utilizes advanced machine learning techniques to predict employee attrition and job change likelihood. The framework integrates robust preprocessing pipelines, state-of-the-art predictive models, and explainability tools such as SHAP.」
>
> 使用 gradient boosting, random forest, neural networks → "flight risk" score。
> 「Organizations using AI to predict and prevent turnover have reduced their attrition rates by up to 50%.」
>
> **在我們的模型中**：
> 用合成數據（年齡、年資、設施、加班時數）訓練離職風險模型 → 比全國平均流失率更精確的設施層級預測。
> 這是 P2 元素，hackathon 時間內可能只能用簡化版。

---

# PART IV — LIFECYCLE DESIGN 與證據

## 12. Lifecycle Beyond Demo

> **Brief 6 要求**：
> 「Demonstrates lifecycle awareness beyond the demo: drift detection, updates, governance」
> Judge's Lens：「The differentiator at grad level is infrastructure thinking. Did you design for what happens after the demo? A system that acknowledges its own failure modes is more credible than one that doesn't.」

### 12.1 Drift Detection

> **證據：**
> Concept drift (Wikipedia/ML literature)：「an evolution of data that invalidates the data model. It happens when the statistical properties of the target variable change over time in unforeseen ways.」
>
> Detection methods：DDM (Drift Detection Method) 監控 error rate over time；EDDM (Early Drift Detection)；control charts from statistical process control。
>
> **我們的實作**：
> - 每年 FAA CWP 更新 → 比對 predicted vs actual CPC count
> - 偏差 > 5% → "Assumption Drift Detected"
> - Dashboard 顯示 Model Freshness indicator（🟢🟡🔴）
> - Parameter bounds check：新數據超出歷史範圍 → bypass warning

### 12.2 Model Versioning

> **證據：**
> ModelOps 框架：「model registry — metamodel (the model specification) with all of the component and dependent pieces that go into building the model, such as the data, the hardware and software environments, the classifiers, and code plug-ins, and most importantly, the business and compliance/risk KPIs.」
>
> **我們的實作**：
> - v1.0: Initial (GAO FY2015-2025 + CWP 2025-2028)
> - v1.1: Updated with CWP 2026-2028
> - 每版完整記錄所有參數值+來源+日期

### 12.3 Verification & Validation

> **證據：**
> 「Simulation models are approximate imitations of real-world systems and they never exactly imitate the real-world system. A model should be verified and validated to the degree needed for the model's intended purpose.」
>
> **三層驗證**：
> - Verification：SD 方程式數學正確性
> - Calibration：用歷史數據 (14,007→13,164) 跑模型
> - Face validation：domain expert 常識檢查

### 12.4 Governance

> **證據：**
> Simulation governance：「concerned with (a) selection of best simulation technology, (b) formulation of mathematical models, (c) management of experimental data, (d) verification procedures, (e) revision in light of new information.」
>
> Sensitivity auditing 框架：「The ultimate aim is to communicate openly and honestly the extent to which particular models can be used to support policy decisions and what their limitations are.」
>
> **我們的實作**：
> - Parameter changes require source citation + confidence rating
> - All outputs auto-tagged with model version + calibration date
> - Cannot export single-scenario results without full comparison
> - Safety outputs always with uncertainty bands + disclaimer

### 12.5 Bypass Conditions

1. 政府 shutdown 期間（歷史 attrition 率不適用）
2. 個別設施決策（模型是戰略層）
3. 外推超過校準範圍（招募率超過 Academy 最大容量）
4. 試圖設定「可接受風險水準」（倫理判斷）
5. 結構性斷裂後立即使用（pandemic、重大政策變革）

---

# PART V — RESPONSIBLE AI 與證據

## 13. 四項風險與緩解

### Risk 1: Overconfidence
- 決策者把模型當精確預測
- 緩解：Monte Carlo 信賴區間、sensitivity rankings、mandatory assumptions panel

### Risk 2: Political Weaponization
- 模型被用來合理化削減
- 緩解：疲勞是 constraint 不是 variable、同時呈現 FAA 和 NATCA 目標

> **證據：NATCA 的立場**
> FAA 2026 年計畫將 CPC 目標從 14,633 降至 12,563（-2,070）。
> NATCA 稱新目標是「the root cause of the staffing crisis we now face」。
> 模型必須呈現兩個目標，不選邊。

### Risk 3: Safety Output Misuse
- 風險指標被誤讀為事故預測
- 緩解：disclaimer + probabilistic framing + 近接事件的統計噪訊說明

### Risk 4: Contested Stakeholder Data
- FAA 和 NATCA 對編制標準有根本分歧
- 緩解：兩套目標都跑、呈現差異、讓使用者選

---

# PART VI — DEMO SCRIPT

## 14. 影片結構 (3-5 min)

### Hook (0:00-0:30)
67 人死亡 → NTSB: workload contributing cause → 280/300 facilities understaffed → near-misses 7-year high

### Solution (0:30-2:00)
TowerGuard: Cost of Doing Nothing simulator → 架構圖 → SD model + AI layer 分工

### Demo (2:00-4:00)
1. Scenario Dashboard → 五條曲線
2. Do Nothing 曲線掉到危險線以下
3. **Intervention Timing slider** → 每延遲一年多花 $X billion
4. Policy Brief → LLM 生成
5. Live Validation → JFK 即時數據確認模型
6. Assumption Ledger → 透明度

### Responsible AI (4:00-4:30)
信賴區間、不選邊、bypass conditions

### Close (4:30-5:00)
$33B/yr delays + 2.2M overtime hrs + 67 lives = the cost of doing nothing

---

# PART VII — SUBMISSION DRAFTS

## 15. Devpost 欄位草稿

### Project Title
TowerGuard: The Cost of Doing Nothing in America's Skies

### Tagline (80 chars)
ATC workforce crisis simulator: see the cost before it's too late

### AI Architecture (600 chars)
> Inputs: FAA Controller Workforce Plan PDFs, GAO audit reports, BTS delay statistics, OpenSky ADS-B live feeds. LLM pipeline extracts structured parameters with confidence scoring. AI Capabilities: (1) System Dynamics simulation engine with Monte Carlo uncertainty wrapper; (2) LLM-powered causal pathway tracer for explainable outputs; (3) Policy brief auto-generation from multi-scenario comparison. Processing: Stock-flow model projects workforce pipeline across 5 scenarios over 10 years. Outputs: Interactive scenario dashboard, intervention timing comparator, AI-generated policy briefs.

### Human-in-Loop (500 chars)
> The system does NOT set acceptable risk levels or make staffing allocation decisions. It projects outcomes under different scenarios and quantifies the cost of delay. All policy decisions — how many to hire, where to allocate, what risk is acceptable — remain with human decision-makers. The AI generates policy briefs and explains model dynamics, but the human must review, validate, and decide. Bypass conditions are enforced when the model operates outside its calibration range.

### Responsible AI Guardrail (500 chars)
> Risk: Overconfidence — policymakers treating model projections as precise forecasts. Mitigation: All outputs display Monte Carlo confidence bands (not point estimates), sensitivity rankings showing which assumptions drive uncertainty, and a mandatory Assumptions panel. The system refuses to display single-scenario results without full comparison context, preventing cherry-picking. We present both FAA (12,563) and NATCA (14,633) staffing targets without endorsing either.

### Tools Used (800 chars) — 草稿
> Python (free) — System Dynamics model, Monte Carlo engine, FastAPI backend
> Claude API / Anthropic (paid) — LLM for policy brief generation, causal explanation, data extraction
> Chart.js (free, open-source) — Interactive scenario visualization
> Leaflet.js (free, open-source) — Live ATC validation map
> Redis (free, open-source) — Real-time data pub/sub
> OpenSky Network API (free, non-commercial) — Live ADS-B flight data
> Claude AI (paid) — Coding assistance during development
> [Add Katherine's tools if applicable]

### Data Disclosure (800 chars) — 草稿
> FAA Controller Workforce Plan 2025-2028 and 2026-2028 (public government documents)
> GAO-26-107320: Air Traffic Control Workforce report, Dec 2025 (public)
> National Academies/TRB: The ATC Workforce Imperative, June 2025 (public)
> Airlines for America: U.S. Passenger Carrier Delay Costs dataset (public)
> FAA/Nextor: delay cost methodology and values (public)
> BTS On-Time Performance data (public)
> OpenSky Network: real-time ADS-B state vectors (free, non-commercial)
> NTSB DCA investigation findings (public)
> Synthetic data: Monte Carlo parameter distributions based on documented historical ranges from the above sources.

---

# APPENDIX A — 完整數據參數表

```python
CALIBRATION_DATA = {
    # === STOCKS (initial values, FY2025 end) ===
    "total_controllers_fy2025": 13164,       # GAO-26-107320
    "total_controllers_fy2015": 14007,       # GAO-26-107320
    "cpcs_fy2025": 11000,                    # FAA CWP 2026-2028 (approx, Apr-2026 snapshot)
    "cpc_only_fy2024": 10730,                # FAA CWP 2025 Fig 2.2 (FY2024 actual, CPC only)
    "cpcs_cpcit_fy2024": 11686,              # FAA CWP 2025 (FY2024 actual; 11,855 was the FY2025 PROJECTION, mislabeled before)
    "developmental_fy2026": 4000,            # FAA/Reuters Apr 2026 — "in training" = Dev + ~1,000 CPC-IT, NOT developmentals alone
    
    # === FLOW RATES ===
    # Hiring
    "hires_fy2020": 920,                     # FAA CWP 2021 facility table (actual)
    "hires_fy2021": 500,                     # GAO (COVID low; goal was 910)
    "hires_fy2022": 1026,                    # FAA CWP 2023 facility table (actual)
    # hires_fy2023: NOT FOUND in any source (the old "1,500 FAA actual" was unverified — removed)
    "hires_fy2024": 1811,                    # FAA CWP 2025 actual (1,700 was the target)
    "hires_fy2025": 2028,                    # FAA CWP 2026-2028 (actual; GAO says 2,026)
    "hires_target_fy2026": 2200,             # FAA CWP
    "hires_target_fy2027": 2300,             # FAA CWP
    "hires_target_fy2028": 2400,             # FAA CWP
    "hires_total_fy2025_2028": 8900,         # FAA CWP
    
    # Academy
    "academy_washout_rate": 0.30,            # GAO: >30% FY2024
    "academy_duration_months": 6,            # approx
    "medical_eval_backlog": 1200,            # ~1,200 stuck (Aug 2024)
    "medical_eval_avg_wait_years": 2,        # FAA/GAO
    
    # Developmental
    "dev_attrition_annual_historical": 102,  # FAA 5-yr avg
    "dev_attrition_annual_projected": 201,   # FAA projected with higher hiring
    "dev_certification_time_median_years": 3, # FAA, range 2-6
    "dev_certification_time_complex_years": 6, # most complex facilities
    "transfer_recertification_months": 18,   # FAA
    
    # Total attrition
    "total_attrition_fy2024": 1400,          # FAA actual
    "total_attrition_fy2025": 1460,          # FAA actual
    "total_attrition_projected_fy2025_2028": 6872, # FAA CWP
    "shutdown_trainee_losses": 450,          # ~400-500, 2025 shutdown
    
    # Retirement
    "mandatory_retirement_age": 56,          # FAA/BLS
    "retention_bonus_retained_fy2025": 400,  # FAA
    "retention_bonus_cost_fy2025": 12300000, # $12.3M
    
    # Pipeline funnel (GAO FY2017-2022 Track 1)
    "funnel_applications": 106533,
    "funnel_took_atsa": 32615,               # -69%
    "funnel_tentative_offer": 9107,          # -72%
    "funnel_accepted": 8442,                 # -7%
    "funnel_passed_medical_security": 4619,  # -45%
    "funnel_started_academy": 3964,          # -14%
    "funnel_completed_academy": 2610,        # -34%
    "funnel_certified_or_ojt": 2258,         # -14%
    "funnel_net_conversion_rate": 0.02,      # ~2%
    
    # === TARGETS ===
    "crwg_target_fy2024": 14633,             # NATCA-preferred
    "afn_target_fy2024": 12242,              # FAA AFN model
    "faa_new_target_fy2026": 12563,          # FAA CWP 2026-2028 (lowered)
    "cpc_cpcit_target_fy2028": 12691,        # FAA projection
    
    # === TRAFFIC ===
    "flights_fy2015": 28100000,              # GAO
    "flights_fy2024": 30800000,              # GAO
    "daily_flights": 45000,                  # NATCA/FAA
    "daily_passengers": 2900000,             # NATCA/FAA
    "atc_facilities_total": 300,             # FAA
    "atc_facilities_understaffed": 280,      # multiple sources (approx)
    
    # === WORKLOAD ===
    "overtime_hours_fy2024": 2200000,        # National Academies
    "overtime_cost_fy2024": 200000000,       # $200M
    "overtime_increase_per_controller_since_2013": 3.08, # +308%
    "overtime_hours_per_controller_fy2024": 167, # avg
    "pct_cpcs_6day_10hr_weeks": 0.41,        # Congressional letter (Feb 2026)
    
    # === ECONOMIC COSTS ===
    "block_time_cost_per_min_usd": 100.76,   # A4A 2024
    "labor_cost_per_min_usd": 35.23,         # A4A 2024
    "fuel_cost_per_min_usd": 33.06,          # A4A 2024
    "pax_time_value_per_hour_usd": 47,       # FAA recommended
    "annual_delay_cost_usd": 33000000000,    # $33B FAA/Nextor 2019
    "annual_pax_delay_cost_usd": 18000000000, # $18B FAA 2026 est
    "shutdown_daily_impact_low_usd": 285000000,  # A4A Nov 2025
    "shutdown_daily_impact_high_usd": 580000000,  # A4A Nov 2025
    "shutdown_pax_disrupted_oct_nov": 5200000, # A4A
    
    # === SAFETY THRESHOLDS ===
    "facility_staffing_floor_pct": 0.85,     # CRWG operational floor
    "safte_fast_impairment_threshold": 0.77, # BAC ≈ 0.05%
    "safte_fast_railroad_threshold": 0.70,   # FRA uses
    "serious_near_misses_fy2023": 19,        # FAA (7-year high)
    "serious_near_misses_fy2022_2023": 23,   # FAA airport total
    "serious_near_misses_fy2024_ab": 9,      # FAA Cat A/B
    "dca_deaths": 67,                        # NTSB
    
    # === FAA MODERNIZATION ===
    "tss_certification_time_reduction": 0.27, # -27% (2021 study)
    "bnatcs_initial_funding": 12500000000,   # $12.5B Congress
    "enhanced_cti_annual_grant": 20000000,   # $20M/yr
    "academy_salary_increase": 0.30,         # ~30% starting salary raise
}
```

---

# APPENDIX B — 研究來源索引

| # | 來源 | 類型 | 用於 |
|---|---|---|---|
| 1 | GAO-26-107320 (Dec 2025) | 審計報告 | 人力數字、招募漏斗、歷史趨勢 |
| 2 | FAA CWP 2025-2028 | 官方計畫 | 招募目標、流失預測、設施編制 |
| 3 | FAA CWP 2026-2028 (May 2026) | 官方計畫 | 最新目標、FY2025 實際數據 |
| 4 | National Academies/TRB (Jun 2025) | 獨立研究 | 編制模型評估、加班數據、建議 |
| 5 | NTSB DCA Final Report (Jan 2026) | 事故調查 | Workload 因果、安全論述 |
| 6 | FAA Fatigue Expert Panel (Apr 2024) | 專家報告 | 疲勞科學、SAFTE-FAST、政策建議 |
| 7 | A4A Delay Cost Dataset | 產業數據 | $100.76/min、年度延誤成本 |
| 8 | A4A Senate Testimony (Nov 2025) | 國會證詞 | Shutdown 經濟影響 |
| 9 | Congressional Letter (Feb 2026) | 國會文件 | 41% 超時工作、士氣低落 |
| 10 | DOT OIG Audit | 監察報告 | 設施缺人比例 |
| 11 | ASCE Failure to Act Series | 政策報告 | Cost of Doing Nothing 方法論前例 |
| 12 | Stern Review (2006) | 經濟學報告 | 延遲行動的複利成本框架 |
| 13 | DICE Model (Nordhaus) | 學術模型 | Social discount rate 方法論 |
| 14 | CfWI UK Workforce SD | 政策實踐 | SD 用於人力規劃的前例 |
| 15 | Frontiers burnout CLD (2023) | 學術論文 | 正回饋迴路建模方法 |
| 16 | MDPI Burnout Framework (2026) | 學術論文 | R1/B1 迴路數學化 |
| 17 | SAFTE-FAST (Hursh et al. 2004) | 疲勞模型 | 77% 閾值校準 |
| 18 | ISPOR SIMULATE Checklist | 方法論標準 | 模型驗證、不確定性處理 |
| 19 | Simulation Governance (Wikipedia) | 標準綜述 | V&V、governance 框架 |
| 20 | ModelOps (Wikipedia) | 技術框架 | Model registry、drift detection |
| 21 | Scientific Reports ML Attrition (2026) | 學術論文 | AI 預測離職的方法論 |
| 22 | Simon Willison LLM Schemas (2025) | 技術部落格 | LLM 結構化抽取是 killer app |
| 23 | Synthetic Control (Abadie/Athey) | 學術方法 | 反事實推理的政策評估前例 |

---

*文件結束。此為活文件，隨執行進度更新。*