# WORK — Bo-Ru:Model + AI + 即時系統

*分工檔 · 配合 [masterplan.md](masterplan.md) · 截止 6/21 23:59 ET*
*你產生數據,KT 消費數據。你們之間唯一的介面 = 一份 scenario-results JSON。*

---

## 你的範圍

後端、模型、AI、以及**保留**現有的即時系統。你**不碰** KT 的任何新前端(scenario dashboard、charts、timing UI、ledger UI)。

## 你擁有的元件

| # | 元件 | 優先 | 複雜 | 建議檔案 |
|---|---|---|---|---|
| N1 | Workforce Stock-Flow Model | P0 | L | `models/workforce_sd.py` |
| N2 | Scenario Engine(5 情境 + timing) | P0 | M | `models/scenario_engine.py` |
| N4 | Economic Impact Module | P0 | M | `models/economic_impact.py` |
| N3 | Monte Carlo Wrapper | P1 | M | `models/monte_carlo.py` |
| N5 | Safety Risk Module | P1 | S | `models/safety_risk.py` |
| N8 | LLM Policy Brief Generator | P1 | M | `ai/policy_brief.py` |
| — | Live Validation 後端 + Leaflet 面板 | 保留 | — | 現有,**別動別交接** |

**Stretch(P2,有時間才做):** N9 Causal Explainer、N10 Data Integration Pipeline。

---

## 你的唯一交付介面:scenario-results JSON

**權威來源 = `contracts/scenario_results.example.json`**(你 Day 1 早上先吐一份寫死的假資料版)。
這份檔一旦存在,它就是規格;下面的 schema 只是給你看形狀。KT 全程只讀這份 JSON。

```jsonc
{
  "meta": {
    "model_version": "1.0",
    "calibration_date": "2026-06-17",
    "generated_at": "<ISO8601>",
    "data_sources": ["GAO-26-107320", "FAA CWP 2026-2028", "..."],
    "freshness": "green"            // green/yellow/red — drift indicator (§12.1)
  },
  "targets": {                       // 兩套都放,不選邊(§13 Risk 2/4)
    "faa": 12563,                    // FAA CWP 2026-2028
    "natca": 14633                   // NATCA / CRWG
  },
  "scenarios": [                     // 5 個:baseline / do_nothing / current_plan / accelerated / disruption
    {
      "id": "baseline",
      "label": "Baseline",
      "description": "FAA CWP 2026-2028 軌跡",
      "years": [2026, 2027, "...", 2036],
      "series": {                    // 每條都是對齊 years 的 10 年陣列
        "total_controllers": [],
        "cpc": [],
        "developmentals": [],
        "staffing_pct_of_target": [],   // 給 85% 危險線用
        "overtime_hours_per_controller": []
      },
      "bands": {                     // Monte Carlo 信賴帶,fan chart 用(先給假帶寬也行,欄位要在)
        "cpc_p10": [],
        "cpc_p90": []
      },
      "costs": {
        "annual_cost_by_year": [],   // 對齊 years
        "cumulative_delay_cost_usd": 0,
        "cumulative_overtime_cost_usd": 0
      },
      "safety": {
        "months_below_85pct": 0,
        "risk_index": []             // 機率性,帶 caveat,非事故預測(§9.2)
      }
    }
  ],
  "timing_comparator": {             // N7 用 — Brief 6 核心要求(§10.2)
    "start_years": [2026, 2027, 2028, 2029, 2030],
    "trajectories": { "2026": [], "2027": [] },        // 每個起始年一條 CPC 曲線
    "cumulative_cost_gap_usd": { "2026": 0, "2027": 0 }, // 相對 2026 介入的累積差距
    "net_cost_of_delay_usd": { "2027": 0, "2028": 0 }    // 晚做總成本 − 早做總成本
  },
  "sensitivity": [                   // N11 tornado
    { "parameter": "academy_washout_rate", "baseline": 0, "low_impact": 0, "high_impact": 0 }
  ],
  "assumptions": [                   // N12 ledger
    { "parameter": "hires_target_fy2026", "value": 2200, "source": "FAA CWP 2026-2028", "confidence": "high" }
  ],
  "policy_brief": {                  // N8,LLM 生成的結構化文字
    "executive_summary": "",
    "key_findings": [],
    "cost_of_delay": "",
    "recommendations": [],
    "limitations": ""
  }
}
```

---

## 4 天排程

| 日 | 做什麼 | 驗收 |
|---|---|---|
| **Day 1 (6/17)** | ① 早上跟 KT 敲定上面 schema → **立刻吐 stub `scenario_results.example.json`** ② N1 stock-flow ③ N4 economic ④ N2 scenario engine | terminal 跑 5 scenarios 輸出 10 年曲線 + cost 數字 |
| **Day 2 (6/18)** | 真模型輸出接上 stub 的位置 · N3 monte carlo(填 `bands`)· 算 `timing_comparator` | KT 換成真資料後前端不爆 |
| **Day 3 (6/19)** | N8 policy brief(Claude API)· N5 safety · meta 的 drift/version 欄位(§12)· 你那半文案 | policy_brief 欄位有真內容 |
| **Day 4 (6/20)** | bug fix · 支援錄影 · 提交 | demo flow 跑通 |

---

## 鐵律

1. **Day 1 早上第一件事就是 stub JSON。** KT 全程靠它開工,你模型晚交不能卡她。schema 欄位先到位,值可以假。
2. **Monte Carlo 帶寬**先給假的沒關係,但 `bands` 欄位一定要在 —— Brief 6 明文罰 single-point prediction,前端要靠這個畫信賴帶。
3. **既有 Live Validation(OpenSky/Redis/SSE/Leaflet)你留著,別動別交接。** 給 KT 一個可嵌入的面板/route 就好。
4. **兩套 target 都放進去**(FAA 12,563 / NATCA 14,633),不選邊。
5. schema 要改 → 先跟 KT 講,改 `contracts/scenario_results.example.json`,別自己默默改欄位名。

## 證據在哪(別重抄,要時翻 masterplan)

- 模型校準數據 → [masterplan.md](masterplan.md) §7 + Appendix A
- 經濟成本乘數 → §8 · safety 閾值 → §9 · 5 情境定義 → §10 · AI layer → §11 · lifecycle/drift → §12
