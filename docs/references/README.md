# TowerGuard 知識庫（專業依據文獻）

*更新：2026-06-12 · 用途：`docs/lineage.md`（W0-2）引用來源、demo 答辯備查、Narrator 的 grounding 素材*

---

## 知識地圖：議題 → 應對組織 → 它們用的知識

| 應對組織 | 角色 | 它們用的知識 | 本地檔案 |
|---|---|---|---|
| **FAA ATO** | 營運方 | 管制作業規範、設施管理、人力計畫 | `FAA_JO_7110.65BB_*.pdf` · `FAA_JO_7210.3EE_*.pdf` · `FAA_Controller_Workforce_Plan_2025-2028.pdf` |
| **DOT OIG** | 監察 | 對 FAA 關鍵設施人力與訓練的審計 | `DOT_OIG_Controller_Staffing_Critical_Facilities_2023.pdf` |
| **NTSB** | 事故調查 | 調查報告、緊急安全建議、人因分析 | `NTSB_AIR-25-01_*.pdf` · `NTSB_AIR-26-02_*.pdf` · 兩份 ATC 專題簡報 |
| **TRB／國家學院** | 獨立科學審查 | staffing 模型科學（FAA 2025 新人力計畫的依據；NATCA 有異議） | `TRB_SR357_*.pdf`（重點摘要版） |
| **NASA** | 研究與安全報告 | 衝突偵測演算法（TSAFE/Autoresolver 系）、ATD-2 系統前身、ASRS 自願安全報告 | `NASA_Paielli_*.pdf` · `NASA_ATD-2_*.pdf` · `NASA_ASRS_Controller_Report_Set.pdf` |
| **學界（人因）** | 理論 | 自動化分階模型、工作負荷測量（NASA-TLX） | `Parasuraman_Sheridan_Wickens_2000_*.pdf` |
| **EUROCONTROL／ICAO** | 國際標準 | PANS-ATM、STCA 規範、SKYbrary | 線上（見下表） |

## 檔案 → TowerGuard 模組對應

| 檔案 | 餵給哪個元件 | 用法 |
|---|---|---|
| `FAA_JO_7110.65BB_w_Chg1-2_2026-01-22.pdf`（916 頁） | 全系統紅線 + Conflict Geometry | ¶2-1-2 Duty Priority（人決策）· ¶5-5-4 雷達間隔 3NM/5NM · ¶4-5-1 垂直 1000ft · ¶2-1-24 交班 |
| `FAA_JO_7210.3EE_Facility_Operation.pdf`（664 頁） | Narrator 簡報格式 | ¶2-2-4 Duty Familiarization and Transfer of Position Responsibility（p.18 起）——position relief briefing 的設施端規範，**簡報五段式結構的直接依據** |
| `FAA_Controller_Workforce_Plan_2025-2028.pdf` | Workload Index | staffing 目標與缺口的官方數字 |
| `DOT_OIG_Controller_Staffing_Critical_Facilities_2023.pdf` | Workload Index + 議題敘事 | 關鍵設施人力審計——「人力不足是真的」的第三方背書 |
| `TRB_SR357_ATC_Workforce_Imperative_Highlights_2025.pdf` | Workload Index | staffing 模型的科學審查（2025-06-18 出版）；注意 NATCA 對其模型有異議——答辯時誠實呈現兩面 |
| `NTSB_AIR-25-01_DCA_Urgent_Safety_Recommendations.pdf` | 議題敘事 | DCA 緊急安全建議（2025-03） |
| `NTSB_AIR-26-02_DCA_Final_Report.pdf`（最終報告，2026-01-27） | 議題敘事 | **肇因定論：FAA 航線設計過近＋未評估安全數據**——引用時守紀律二 |
| `NTSB_DCA_ATC_Presentation_2026-01-27.pdf` | 議題敘事 | 董事會 ATC 專題簡報 |
| `NTSB_DCA_ATC_Human_Performance_2026-01-27.pdf` | Workload Index + Orchestrator 設計 | ATC 人因專題——注意力、負荷與系統壓力的官方分析框架 |
| `NASA_Paielli_Terminal_Pairwise_Conflict_Detection_NTRS-20170011259.pdf` | Conflict Geometry | 終端空域成對衝突偵測（Paielli，TSAFE 系）——外推比對方法的學術依據 |
| `NASA_ATD-2_IADS_TechTransfer_NTRS-20205006383.pdf` | 差異化敘事 | 最接近的系統前身，「哪裡新哪裡不新」 |
| `NASA_ASRS_Controller_Report_Set.pdf` | **Narrator grounding 素材** | 真實管制員自願報告敘事（去識別化）——LLM 寫交班敘事的語言與事件樣態範本；也是 demo mock 事件的靈感來源 |
| `Parasuraman_Sheridan_Wickens_2000_Types_Levels_Automation.pdf` | 全系統紅線 | 第 1–2 階（資訊取得＋分析）理論依據；Fig. 2、Table 1 |

## 線上來源（無法或不宜本地化）

| 來源 | 連結 | 說明 |
|---|---|---|
| ASRS Database Online | https://asrs.arc.nasa.gov/search/database.html | 可線上檢索管制員報告全文（workload、handoff 等關鍵字）——要更多 Narrator 素材來這裡挖 |
| TRB SR357 全書 | https://nap.nationalacademies.org/catalog/29112/ | 免費線上閱讀（DOI 10.17226/29112），下載需 NAP 帳號；已存重點摘要版 |
| NTSB DCA25MA108 調查專頁 | https://www.ntsb.gov/investigations/Pages/DCA25MA108.aspx | 全部簡報與聽證材料 |
| ICAO Doc 4444 PANS-ATM | https://store.icao.int/ | 付費出版品，不放盜版；美國 demo 主引 FAA 7110.65 |
| SKYbrary：Separation Standards / STCA / NASA-TLX | https://skybrary.aero/articles/separation-standards · /short-term-conflict-alert-stca · /nasa-task-load-index-nasa-tlx | JS 牆抓不下來，線上查 |
| FAA 7110.65BB / 7210.3EE HTML 版 | https://www.faa.gov/air_traffic/publications/atpubs/atc_html/ · /foa_html/ | 段落級超連結，寫 lineage.md 引用方便 |

## 引用紀律（答辯防線）

1. **DCA 事故（NTSB AIR-26-02）**：肇因定論是 FAA 航線設計過近＋未評估安全數據，**不是「缺人撞機」**。只能當「系統壓力背景」引用——這是 overview 紀律二，評審若追問就拿最終報告原文回應。
2. **TRB SR357 vs NATCA**：FAA 新人力計畫採用 TRB 模型，NATCA 公開質疑該模型是「現有危機的根因」。答辯時兩面都講，這正好支撐我們「工具透明、人來判斷」的立場。
3. **版本要寫全**：FAA Order JO 7110.65BB / JO 7210.3EE（皆 with Chg 1–2, eff. 2026-01-22 版）。
4. 所有本地 PDF 已驗證 magic bytes；7110.65BB 四個關鍵段落、7210.3EE ¶2-2-4 已用 pypdf 全文檢索確認。
