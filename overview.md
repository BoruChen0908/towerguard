# TowerGuard — 一頁總覽

*最後更新：2026-06-12 · 給 Bo-Ru 隨時回來看，不迷路*

---

## 它是什麼（一句話）

當塔台長期人力吃緊，TowerGuard 用一套「3 個確定性模組 + 2 個 LLM agent」的系統，**承擔資訊處理的負擔——偵測、排序、生成交班敘事——讓更少的管制員更安全地管更多航班。人始終保留所有決策權，AI 只放大他們的注意力。**

- **比賽**：USAII Global AI Hackathon 2026，研究所組，賽道「AI for Systems & Society（Human Safety）」
- **團隊**：Bo-Ru（後端／確定性模組）＋ Katherine（AI／agent）
- **主要使用者**：現場管制員（tower/TRACON）。管理層、政策層是「同一套產出往上彙整」的衍生視圖，不是主角。

---

## 三條不能破的紀律（整個專案的地基）

1. **紅線**：所有 AI 只做「資訊取得＋分析」（Parasuraman 四階段的第 1–2 階），**決策與執行（發許可、提供分離、發安全警報）永遠是人**。對應 FAA Order JO 7110.65BB ¶2-1-2。
2. **事實**：人力不足是真的（約 3,000 缺額、220 萬加班小時、每人比 2013 多 308%）。但 **DCA 是航線設計失誤、LaGuardia 管制員在崗沒離開、肇因未定**——三起事故只能當「系統壓力背景」，不能說成「缺人撞機」。
3. **誠實用 agent**：確定性的計算用確定性程式，只有需要語言理解與動態協調的才用 agent。**不為湊數而硬包 agent。**

---

## 架構（誰做什麼）

```
OpenSky ADS-B
     ↓
[Bo-Ru] Traffic Density ──┐
[Bo-Ru] Conflict Geometry ─┼→ Redis → [Katherine] Orchestrator → Advisory
[Bo-Ru] Workload Index ───┘                        ↓
                                        [Katherine] Narrator → 交班 Briefing
```

**Bo-Ru 的三個確定性模組（不是 agent，誠實標明）**
- Traffic Density：數航班、算速度/高度變異 → load tier
- Conflict Geometry：每對航班外推 **60–120 秒**，比對 ICAO 分離標準（5NM 航路 / 3NM 終端 / 1000ft）
- Workload Index：人力負載加權公式

**Katherine 的兩個真 agent（這才是「為什麼非 multi-agent 不可」的答案）**
- Orchestrator / 仲裁：協調三個模組訊號，**當它們判斷分歧時把矛盾浮現給人**
- Narrator：LLM 把整班事件組成交班簡報，**只摘要已記錄事件＋附 alert ID，不預測不建議**（這是最真的差異點，現有部署系統沒有先例）

---

## 差異化（怎麼跟 FAA/NASA/Google 既有系統區隔）

不跟 TFMS、ERAM、STARS、ASDE-X、NASA ATD-2 比「分析能力」——它們做得比 20 天專案好。
**只比三件它們做不到的事**：① 把各自為政的功能整合進同一個管制員介面 ② LLM 交班敘事 ③ 增能而非取代的設計。
（動手前先讀 NASA ATD-2 / IADS 技轉文件 NTRS 20205006383，它是最接近的前身，誠實說哪裡新哪裡不新。）

---

## 20 天能做出來的 demo

- **資料**：OpenSky（即時 ADS-B，免費非商用）＋ NWS（天氣）＋ BTS／FAA NASR（機場資料）。**不碰 LiveATC 音檔、不碰 FAA 營運系統。**
- **技術棧**：Python 模組 ＋ LangGraph/CrewAI（agent）＋ Redis（串接）＋ Streamlit＋地圖（儀表板）
- **最小版**：OpenSky ＋ 衝突偵測 ＋ 交班 agent ＋ Streamlit，約 10 個工作天；其餘擴充到 20 天
- **demo 防呆**：留 5 分鐘 replay buffer（防 OpenSky 429／token 過期）、選 JFK/EWR/BOS/ATL 等 ADS-B 密集機場、UI 放醒目免責聲明「非認證 ATC 系統，僅供決策輔助」

---

## 進度現況

| 項目 | 狀態 |
|---|---|
| 題目與架構定案 | ✅ 完成 |
| 事實查證（人力數字、三起事故） | ✅ 完成，已修正 |
| Qualifier 8 題答題（正確版） | ✅ 已成檔（`TowerGuard_Qualifier.md`） |
| Bo-Ru / Katherine 介面契約 | 🟡 v1.1 提案已出（命名統一＋bug 修正），待 Katherine 6/15 確認 |
| 任務主導執行計畫（`plan.md`） | ✅ 已成檔：demo 驗收清單 D1–D10 + 四個波次 |
| 專業依據文獻庫（`docs/references/`） | ✅ 13 份官方文件已下載驗證（FAA/NTSB/OIG/TRB/NASA）+ 知識地圖索引 |
| 三個模組實作 | ✅ 完成（120 tests / 97% cov，已上 GitHub private repo） |
| 兩個 agent 實作 | ⬜ 開發中 |
| 整合測試 | ⬜ 排定 6/19 |

---

