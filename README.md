# 🧬 SimLife Evolution System

**沙盒式人工生命模擬器** — 觀察模擬人在世代交替中的自然選擇與演化歷程。

玩家不直接控制「模擬人 (Sims)」的行為，而是透過修改基因編碼、調整物理環境與投放天敵/食物，觀察自然演化。

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Tests](https://img.shields.io/badge/Tests-41%20passed-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## ✨ Features

### 🧬 基因系統
- **可配置基因組** — 透過 JSON 定義基因，無需修改程式碼
- **連續數值基因** — Size, Lifespan, Sociability, Fear/Aggression
- **離散列舉基因** — Locomotion, DigestiveSystem, MatingStrategy
- **自定義基因** — 夜行性、海洋適應、體表絕緣等

### 🔄 進化演算法
- **基因交叉** — 單點交叉 / 多點交叉
- **隨機突變** — 高斯擾動 + 演化路徑限制
- **適應度評估** — 純自然選擇，無人工分數

### 🌍 環境系統
- **2D 地圖** — 草原、森林、沙漠、雪地、海洋等地形
- **氣候循環** — 四季溫度變化 + 濕度影響資源生成
- **日夜循環** — 光照等級平滑過渡，影響夜行性生物

### 🌙 夜行性機制
- **能量修正** — 夜行性生物夜間能耗低，白天能耗高
- **隱蔽值** — 影響被天敵偵測的機率
- **偵測範圍** — 夜間視力在黑暗中提供替代視野

### 🌊 海洋適應
- **水陸兩棲** — 從 LAND_BOUND 到 DEEP_SEA 的演化路徑
- **氧氣消耗** — 不同適應等級的水下生存能力

### 🔧 Web UI 編輯器
- **視覺化編輯** — 點選基因即可編輯屬性和演化路徑
- **SVG 演化路徑圖** — 環形佈局顯示基因間的突變關係
- **即時儲存** — 一鍵寫回 JSON 配置檔

---

## 🚀 Quick Start

### 安裝

```bash
git clone https://github.com/raymond2026-km/simlifeGen.git
cd simlifeGen
pip install flask
```

### 執行模擬

```bash
# 基本執行
python -c "
import sys; sys.path.insert(0,'.')
from simlife.simulation import SimulationEngine, SimulationConfig
config = SimulationConfig(initial_population=50, max_ticks=2000, seed=42)
engine = SimulationEngine(config)
engine.run(verbose=True)
"
```

### 啟動 Web 編輯器

```bash
python -m simlife.web --port 5000
# 瀏覽器開啟 http://127.0.0.1:5000
```

### 執行測試

```bash
cd simlife
python -m pytest tests/ -v
```

---

## 📁 Project Structure

```
simlife/
├── __init__.py              # 套件入口
├── __main__.py              # python -m simlife 支援
├── gene_config_manager.py   # 基因配置管理器（JSON 動態載入）
├── genetic_engine.py        # 進化引擎（交叉 + 突變）
├── sim.py                   # Sim 個體實體
├── metabolism.py            # 代謝引擎（BMR、體溫、活動乘數）
├── environment.py           # 環境系統（氣候、2D 地圖、晝夜）
├── ecology.py               # 生態閉環（資源生成、腐爛、爭奪）
├── selection.py             # 自然選擇（適應度、基因鏈追蹤、絕跡）
├── simulation.py            # 主模擬引擎（tick 循環整合）
├── main.py                  # CLI 進入點
├── configs/
│   └── gene_config.json     # 設計師可編輯的基因配置
├── tests/
│   └── test_basic.py        # 41 個單元測試
└── web/
    ├── server.py            # Flask REST API
    ├── run.py               # 獨立啟動腳本
    └── templates/
        └── index.html       # 單頁前端 UI
```

---

## 🧬 Gene System

### 內建基因

| 基因 | 類型 | 說明 |
|------|------|------|
| `locomotion` | 離散 | 移動方式：CRAWL, WALK, RUN, FLY, SWIM |
| `digestive` | 離散 | 消化系統：HERBIVORE, CARNIVORE, OMNIVORE, PLANKTIVORE |
| `mating` | 離散 | 交配策略：SEXUAL, ASEXUAL |
| `territory` | 離散 | 領域行為：SOLO, PACK, NOMADIC |
| `size` | 連續 | 體型大小（0.1 ~ 10.0） |
| `lifespan` | 連續 | 壽命極限（50 ~ 1000） |
| `sociability` | 連續 | 社交傾向（0.0 ~ 1.0） |
| `fear_aggression` | 連續 | 恐懼/攻擊權重（0.0 ~ 1.0） |
| `base_hp` | 連續 | 基礎血量（10 ~ 500） |

### 自定義基因（已內建）

| 基因 | 說明 |
|------|------|
| `nocturnality` | 夜行性：DIURNAL, NOCTURNAL, CREPUSCULAR |
| `ocean_adaptation` | 海洋適應：LAND_BOUND, AMPHIBIOUS, AQUATIC, DEEP_SEA |
| `thermal_insulation` | 體表絕緣：BARE_SKIN, FUR, FEATHERS, SCALES |

### 演化路徑範例

```
locomotion:
  CRAWL → WALK, FLY, SWIM
  WALK  → CRAWL, RUN, FLY, SWIM
  RUN   → WALK, FLY
  FLY   → WALK, RUN
  SWIM  → CRAWL, WALK
```

---

## 🌡️ Core Formulas

### 代謝消耗

```
E_drain = BMR × locomotion_mult × activity_mult × thermal_penalty + insulation_penalty

BMR = k₁ × size^1.5
```

### 體溫懲罰

```
penalty = BMR × (1 - thermal_strength) × (ΔT / critical_range)²
```

### 適應度

```
fitness = survival_score × efficiency_mult + reproduction_bonus

survival_score = min(ticks / expected_lifespan, 1.0) × 40
efficiency_mult = 1.0 + min(energy_efficiency, 5.0) × 0.1
reproduction_bonus = min(offspring_count × 10, 50)
```

### 夜行性能量修正

```
NOCTURNAL:
  夜間: modifier = 1.0 - 0.2 × light_level      (節省 20%)
  白天: modifier = 1.0 + 0.3 × (1 - light_level) (消耗 +30%)

DIURNAL:
  夜間: modifier = 1.0 + 0.25 × (1 - light_level) (消耗 +25%)
  白天: modifier = 1.0 - 0.15 × light_level        (節省 15%)
```

---

## 🎮 Gameplay

### 核心循環

```
每個 Tick:
  1. 氣候推進（溫度、濕度、日夜）
  2. 資源生成（受濕度、季節、地形影響）
  3. 個體行為（覓食、移動、戰鬥）
  4. 代謝消耗（能量扣除）
  5. 死亡判定（能量/HP 耗盡）
  6. 繁殖階段（適應度排序 + 交叉 + 突變）
  7. 絕跡檢查（連續 3 代未繁殖）
```

### 實驗建議

| 實驗 | 做法 |
|------|------|
| 觀察夜行性演化 | `seed=42` 跑 2000 tick，看 NOCTURNAL 比例變化 |
| 極端環境 | 調 `base_temp=40`（酷熱）或 `ticks_per_day=50`（快速日夜） |
| 加速突變 | `base_mutation_rate=0.05`，新品種更快出現 |
| 測試絕跡 | `max_population=30`（小種群更容易絕跡） |

---

## 🔧 Web UI

### 功能

- 📋 **基因列表** — 左側顯示所有基因（內建/自定義標籤）
- ✏️ **基因編輯器** — 描述、預設值、突變倍數、枚舉值屬性
- 📊 **SVG 演化路徑圖** — 環形佈局顯示突變關係
- ➕ **新增/刪除基因** — Modal 表單，支援批量屬性輸入
- 💾 **儲存/重載** — 一鍵寫回 JSON、熱重載配置

### API 端點

| 方法 | 路徑 | 功能 |
|------|------|------|
| `GET` | `/api/genes` | 列出所有基因 |
| `GET` | `/api/genes/<name>` | 取得單個基因 |
| `POST` | `/api/genes` | 新增基因 |
| `PUT` | `/api/genes/<name>` | 更新基因 |
| `DELETE` | `/api/genes/<name>` | 刪除基因 |
| `GET` | `/api/evolution-graph/<name>` | 演化路徑圖 |
| `POST` | `/api/save` | 儲存至 JSON |
| `POST` | `/api/reload` | 重新載入 |

---

## 🧪 Testing

```bash
# 執行所有測試
python -m pytest tests/ -v

# 執行特定測試類別
python -m pytest tests/test_basic.py::TestMetabolism -v

# 顯示覆蓋率
python -m pytest tests/ --cov=simlife
```

### 測試覆蓋

- ✅ GeneConfigManager — 配置載入、驗證、動態新增
- ✅ GeneticEngine — 交叉、突變、繁殖
- ✅ Sim — 個體實體、狀態管理、死亡判定
- ✅ MetabolismEngine — BMR、體溫、夜行性修正
- ✅ EnvironmentManager — 氣候、地圖、日夜循環
- ✅ EcologyManager — 資源生成、腐爛、搜尋
- ✅ SelectionEngine — 適應度、選擇、基因鏈追蹤

---

## 📜 License

MIT License - 自由使用、修改、分發。

---

## 🤖 Generated with Codebuff

This project was built with the assistance of [Codebuff](https://codebuff.com) AI.
