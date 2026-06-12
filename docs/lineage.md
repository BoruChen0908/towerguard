# TowerGuard — Decision Lineage

**TowerGuard 不發明流程：每個決策點都站在既有 ATC 標準上。**

這份文件把 TowerGuard 每一個會影響顯示或建議的決策點，逐條對回它所依據的既有專業標準、系統前例或學術譜系。目的有兩個：對評審證明「這不是憑空發明的」，對使用者交代「畫面上每個數字背後站著誰」。凡是 demo 校準值（而非標準硬性規定的數字），下表都會誠實標注，不假裝它是 FAA 規範。

---

## 決策點 → TowerGuard 實作 → 專業依據

| 決策點 | TowerGuard 實作 | 專業依據 |
|---|---|---|
| **終端區水平分離 3.0 NM** | conflict 雙條件之一 | FAA JO 7110.65BB ¶5-5-4 Minima（本地 PDF 已驗證）；國際對照 ICAO Doc 4444 |
| **垂直分離 1000 ft** | conflict 雙條件之二 | FAA JO 7110.65BB ¶4-5-1 Vertical Separation |
| **成對外推衝突偵測（120s、CPA）** | conflict_geometry 模組 | 系統前例：STARS/ERAM Conflict Alert（safety net 定位，參 SKYbrary STCA）；演算法譜系：NASA Paielli 終端空域成對 CD&R（NTRS 20170011259） |
| **tier 時間閾值 60/90s** | CRITICAL/HIGH 分級 | 概念對應 STCA 戰術預警窗（誠實標注：具體數值為 demo 校準，分級結構沿襲 CA/STCA 實務） |
| **score → tier 0.40/0.65/0.85** | traffic / workload 分級 | demo 校準值（誠實標注），分級習慣對應 FAA 流量管理實務 |
| **staffed / recommended** | workload_index 真實基準 | FAA Controller Workforce Plan 2025–2028 設施表 pp.28–33（CRWG target vs CPC，JFK 33/30 等）；模型科學審查：TRB Special Report 357（2025） |
| **人決策、AI 只做資訊取得 + 分析** | HUMAN DECISION REQUIRED、Confirm | FAA JO 7110.65 ¶2-1-2 Duty Priority；Parasuraman/Sheridan/Wickens (2000) 自動化四階段第 1–2 階 |
| **交班簡報五段式 + 簽核** | Narrator briefing + Controller Confirmed | FAA JO 7110.65 ¶2-1-24 Transfer of Position Responsibility；JO 7210.3EE ¶2-2-4；敘事素材譜系：NASA ASRS 管制員報告 |
| **斷線顯示 DEGRADED 不偽裝 LOW** | UNKNOWN tier + 橫幅 | safety-critical fail-safe 原則（故障不得呈現為安全狀態） |
| **系統定位** | 整體 | 最近前身 NASA ATD-2/IADS（NTRS 20205006383）：資料整合有先例；新在管制員單一介面 + LLM 交班敘事 |

---

完整文獻在 `docs/references/`（13 份官方文件含原文 PDF）。
