"""
MetabolismEngine — 代謝引擎

負責計算每個 Sim 每個 tick 的能量消耗與攝取。

核心公式：
  E_drain = BMR × locomotion_mult × activity_mult × thermal_penalty + insulation_penalty

其中：
  BMR = k₁ × size^1.5
  locomotion_mult: 由 locomotion 基因屬性決定
  activity_mult:  由當前行為狀態決定
  thermal_penalty: 由 thermal_insulation 基因 + 環境溫度決定
  insulation_penalty: 由 thermal_insulation.weight_penalty × size 決定
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .sim import Sim, SimState


# ════════════════════════════════════════════════════════════════
#  活動類型
# ════════════════════════════════════════════════════════════════

class Activity(Enum):
    IDLE        = "idle"
    FORAGING    = "foraging"
    FLEEING     = "fleeing"
    FIGHTING    = "fighting"
    MATING      = "mating"
    SOCIALIZING = "socializing"
    SWIMMING    = "swimming"


# ════════════════════════════════════════════════════════════════
#  代謝引擎
# ════════════════════════════════════════════════════════════════

class MetabolismEngine:
    """
    代謝引擎

    ╔══════════════════════════════════════════════════════════════╗
    ║              EnergyDrainRate 核心公式                       ║
    ║                                                            ║
    ║  E_drain = BMR × loc_mult × act_mult + thermal + insul    ║
    ║                                                            ║
    ║  BMR = k₁ × size^1.5                                      ║
    ║  loc_mult: CRAWL=0.6, WALK=1.0, RUN=2.2, FLY=3.5,        ║
    ║            SWIM=1.2                                        ║
    ║  act_mult: IDLE=0.5, FORAGING=1.0, FLEEING=2.0,           ║
    ║            FIGHTING=2.5, MATING=1.5, SOCIALIZING=0.8       ║
    ║  thermal:  ThermalRegulation.energy_penalty(env_temp, BMR) ║
    ║  insul:    weight_penalty × size × 0.5                     ║
    ╚══════════════════════════════════════════════════════════════╝
    """

    K1: float = 0.5  # 代謝常數

    # 移動方式 → 代謝乘數（從基因屬性 fallback）
    LOCOMOTION_MULT_DEFAULTS = {
        "CRAWL": 0.6,
        "WALK":  1.0,
        "RUN":   2.2,
        "FLY":   3.5,
        "SWIM":  1.2,
    }

    # 活動狀態 → 代謝乘數
    ACTIVITY_MULT = {
        Activity.IDLE:        0.5,
        Activity.FORAGING:    1.0,
        Activity.FLEEING:     2.0,
        Activity.FIGHTING:    2.5,
        Activity.MATING:      1.5,
        Activity.SOCIALIZING: 0.8,
        Activity.SWIMMING:    1.3,
    }

    # 消化系統 → 攝取效率
    DIGESTIVE_EFFICIENCY = {
        "HERBIVORE": 1.0,
        "CARNIVORE": 1.3,
        "OMNIVORE":  0.85,
        "PLANKTIVORE": 1.1,
    }

    def __init__(self, k1: float = 0.5):
        self.k1 = k1

    # ── 核心計算 ──────────────────────────────────────────

    def compute_bmr(self, size: float) -> float:
        """基礎代謝率 BMR = k₁ × size^1.5"""
        return self.k1 * (size ** 1.5)

    def get_locomotion_mult(self, sim: Sim) -> float:
        """取得移動方式代謝乘數（優先從基因屬性讀取）"""
        loco = sim.get_gene("locomotion")
        attrs = sim.get_gene_attrs("locomotion")
        if "speed_mult" in attrs:
            # 速度乘數越高 → 代謝越高（但不是線性，用平方根緩衝）
            import math
            return 0.3 + 0.7 * math.sqrt(attrs["speed_mult"] / 3.0)
        return self.LOCOMOTION_MULT_DEFAULTS.get(loco, 1.0)

    def get_activity_mult(self, state: SimState) -> float:
        """取得活動狀態代謝乘數"""
        activity_map = {
            SimState.IDLE:     Activity.IDLE,
            SimState.FORAGING: Activity.FORAGING,
            SimState.FLEEING:  Activity.FLEEING,
            SimState.FIGHTING: Activity.FIGHTING,
            SimState.MATING:   Activity.MATING,
            SimState.DEAD:     Activity.IDLE,
        }
        activity = activity_map.get(state, Activity.IDLE)
        return self.ACTIVITY_MULT.get(activity, 1.0)

    def compute_thermal_penalty(
        self,
        sim: Sim,
        env_temp: float,
        bmr: float,
    ) -> float:
        """
        計算體溫調節能量懲罰。

        公式：
          ΔT = |env_temp - body_temp_base|
          penalty = bmr × (1 - thermal_strength) × (ΔT / critical_range)²

        thermal_strength 取決於 thermal_insulation 基因：
          BARE_SKIN: 0.0, FUR: 0.5, FEATHERS: 0.6, SCALES: 0.4
        """
        insulation = sim.get_gene("thermal_insulation")
        attrs = sim.get_gene_attrs("thermal_insulation")

        # 基礎體溫（假設 37°C，由 size 微調：越大越接近恆溫）
        body_temp_base = 37.0 + (sim.get_stat("size") - 5.0) * 0.2

        # 來自 insulation 基因的抗性
        cold_resist = attrs.get("cold_resistance", 0.0)
        heat_resist = attrs.get("heat_resistance", 0.0)

        delta_T = env_temp - body_temp_base
        if delta_T > 0:
            # 炎熱：heat_resistance 抵消
            thermal_strength = heat_resist
            effective_range = 30.0
        else:
            # 寒冷：cold_resistance 抵消
            thermal_strength = cold_resist
            effective_range = 30.0
            delta_T = abs(delta_T)

        penalty = bmr * (1.0 - thermal_strength) * (delta_T / effective_range) ** 2
        return max(0.0, penalty)

    def compute_structural_damage(
        self,
        sim: Sim,
        env_temp: float,
    ) -> float:
        """
        計算體溫過極端導致的結構性損傷（HP 扣除比例）。
        只有 ΔT 超過 critical_range 才會觸發。
        """
        body_temp_base = 37.0 + (sim.get_stat("size") - 5.0) * 0.2
        delta_T = abs(env_temp - body_temp_base)
        critical_range = 30.0  # 可擴展為基因屬性

        excess = max(0.0, delta_T - critical_range)
        vulnerability = 0.02  # 每度超限的組織損傷率
        return excess * vulnerability

    def compute_insulation_penalty(self, sim: Sim) -> float:
        """
        體表絕緣的重量懲罰。
        weight_penalty × size × 0.5
        越厚重的覆蓋（鱗片、厚毛）→ 移動越慢 → 代謝越高
        """
        attrs = sim.get_gene_attrs("thermal_insulation")
        weight_penalty = attrs.get("weight_penalty", 0.0)
        size = sim.get_stat("size")
        return weight_penalty * size * 0.5

    # ── 統一計算入口 ──────────────────────────────────────

    def compute_total_drain(
        self,
        sim: Sim,
        env_temp: float,
        is_night: bool = False,
        light_level: float = 1.0,
    ) -> tuple[float, float]:
        """
        計算總能量消耗與 HP 損傷。

        Args:
            sim: 模擬人個體
            env_temp: 環境溫度 (°C)
            is_night: 是否為夜晚
            light_level: 光照等級 (0.0 ~ 1.0)

        Returns:
            (energy_drain, hp_damage)
        """
        size = sim.get_stat("size")
        bmr = self.compute_bmr(size)
        loc_mult = self.get_locomotion_mult(sim)
        act_mult = self.get_activity_mult(sim.state)
        thermal = self.compute_thermal_penalty(sim, env_temp, bmr)
        insul = self.compute_insulation_penalty(sim)
        nocturnal_mod = self.compute_nocturnal_energy_modifier(sim, is_night, light_level)
        hp_dmg = self.compute_structural_damage(sim, env_temp)

        total_drain = (bmr * loc_mult * act_mult + thermal + insul) * nocturnal_mod
        return total_drain, hp_dmg * sim.hp  # hp_damage 為百分比

    # ── 水中額外消耗 ──────────────────────────────────────

    def compute_water_drain(self, sim: Sim) -> float:
        """
        水中額外氧氣消耗。
        取決於 ocean_adaptation 基因的 oxygen_consumption 屬性。
        """
        attrs = sim.get_gene_attrs("ocean_adaptation")
        o2_consumption = attrs.get("oxygen_consumption", 0.0)
        if o2_consumption >= 999.0:
            return 10.0  # LAND_BOUND 在水中每 tick 扣 10 能量
        return o2_consumption * 2.0  # 基礎水中消耗

    # ── 食物攝取 ──────────────────────────────────────────

    def compute_energy_gain(
        self,
        resource_calories: float,
        digestive: str,
    ) -> float:
        """計算攝取能量"""
        efficiency = self.DIGESTIVE_EFFICIENCY.get(digestive, 1.0)
        return resource_calories * efficiency

    # ── 速度計算（考慮多種基因） ──────────────────────────

    def compute_effective_speed(self, sim: Sim) -> float:
        """
        計算 Sim 的有效移動速度。

        考慮：
          1. locomotion.speed_mult（從基因屬性）
          2. thermal_insulation.weight_penalty（重量懲罰）
          3. nocturnality（日夜修正，如果存在）
          4. ocean_adaptation.land_movement_penalty（陸地懲罰）
          5. size（越大越慢）
        """
        attrs = sim.get_gene_attrs("locomotion")
        base_speed = attrs.get("speed_mult", 1.0)

        # 重量懲罰
        insul_attrs = sim.get_gene_attrs("thermal_insulation")
        weight = insul_attrs.get("weight_penalty", 0.0)
        base_speed *= (1.0 - weight)

        # 體型修正：size 越大越慢（但不是主要因素）
        size = sim.get_stat("size")
        base_speed *= max(0.3, 1.0 - (size - 5.0) * 0.05)

        # 夜行性修正 — 由外部傳入 is_night/light_level 時套用
        # 此方法預設不做修正，由 SimulationEngine 在 action tick 時套用

        # 海洋陸地懲罰
        terrain = sim.current_terrain
        if terrain in ("ocean", "river", "swamp"):
            swim_speed = sim.get_gene_attrs("ocean_adaptation").get("swim_speed", 0.0)
            base_speed = swim_speed * base_speed
        else:
            land_penalty = sim.get_gene_attrs("ocean_adaptation").get("land_movement_penalty", 0.0)
            base_speed *= (1.0 - land_penalty)

        return max(0.1, base_speed)

    # ── 夜行性修正 ───────────────────────────────────────

    def apply_nocturnal_modifier(
        self,
        sim: Sim,
        is_night: bool,
    ) -> float:
        """
        根據晝夜狀態套用夜行性基因的速度修正。
        回傳修正後的速度乘數。
        """
        attrs = sim.get_gene_attrs("nocturnality")
        if not attrs:
            return 1.0

        if is_night:
            return attrs.get("speed_mult_night", 1.0)
        else:
            return attrs.get("speed_mult_day", 1.0)

    def compute_nocturnal_energy_modifier(
        self,
        sim: Sim,
        is_night: bool,
        light_level: float,
    ) -> float:
        """
        夜行性能量消耗修正器。

        ╔══════════════════════════════════════════════════════════════╗
        ║  Nocturnal Energy Modifier                                  ║
        ║                                                            ║
        ║  夜行性生物在白天活動時：                                    ║
        ║    modifier = 1.0 + day_penalty × (1 - light_level)        ║
        ║    (白天 = 高能耗，因為它們不適應日光)                      ║
        ║                                                            ║
        ║  夜行性生物在夜間活動時：                                    ║
        ║    modifier = 1.0 - night_bonus × light_level              ║
        ║    (夜間 = 低能耗，因為它們適應黑暗)                        ║
        ║                                                            ║
        ║  日行性生物相反：                                           ║
        ║    夜間 modifier = 1.0 + night_penalty × (1 - light_level) ║
        ║    白天 modifier = 1.0 - day_bonus × light_level           ║
        ╚══════════════════════════════════════════════════════════════╝
        """
        attrs = sim.get_gene_attrs("nocturnality")
        if not attrs:
            return 1.0

        nocturnal = sim.get_gene("nocturnality")

        if nocturnal == "NOCTURNAL":
            # 夜行性：白天能耗高，夜間能耗低
            day_penalty = 0.3   # 白天額外消耗 30%
            night_bonus = 0.2   # 夜間節省 20%
            if is_night:
                return 1.0 - night_bonus * light_level
            else:
                return 1.0 + day_penalty * (1.0 - light_level)

        elif nocturnal == "DIURNAL":
            # 日行性：夜間能耗高，白天能耗低
            night_penalty = 0.25  # 夜間額外消耗 25%
            day_bonus = 0.15      # 白天節省 15%
            if is_night:
                return 1.0 + night_penalty * (1.0 - light_level)
            else:
                return 1.0 - day_bonus * light_level

        else:  # CREPUSCULAR
            # 晨昏性：日夜能耗均衡，黎明/黃昏時最高效
            # 近似：light_level 接近 0.5 時 modifier 最低
            optimal_light = 0.4  # 最佳光照
            deviation = abs(light_level - optimal_light)
            return 1.0 + deviation * 0.1  # 偏離最佳光照 → 輕微能耗增加

    def compute_nocturnal_stealth(
        self,
        sim: Sim,
        light_level: float,
    ) -> float:
        """
        夜行性隱蔽值 — 影響被天敵偵測的機率。

        ╔══════════════════════════════════════════════════════════════╗
        ║  Stealth Formula                                           ║
        ║                                                            ║
        ║  stealth = base_stealth_night × (1 - light_level)          ║
        ║          + base_stealth_day × light_level                  ║
        ║                                                            ║
        ║  NOCTURNAL: stealth_night=0.9, stealth_day=0.1             ║
        ║    → 夜間 stealth ≈ 0.9, 白天 stealth ≈ 0.1               ║
        ║  DIURNAL: stealth_night=0.1, stealth_day=0.7               ║
        ║    → 夜間 stealth ≈ 0.1, 白天 stealth ≈ 0.7               ║
        ║  CREPUSCULAR: stealth_night=0.5, stealth_day=0.5           ║
        ║    → 全天候 stealth ≈ 0.5                                  ║
        ╚══════════════════════════════════════════════════════════════╝
        """
        attrs = sim.get_gene_attrs("nocturnality")
        if not attrs:
            return 0.5  # 無夜行性基因 → 預設隱蔽值

        stealth_night = attrs.get("stealth_night", 0.5)
        # 白天隱蔽 = 1 - stealth_night（鏡像）
        stealth_day = max(0.1, 1.0 - stealth_night)

        # 線性插值：light_level 0→night, 1→day
        return stealth_night * (1.0 - light_level) + stealth_day * light_level

    def compute_nocturnal_detection_range(
        self,
        sim: Sim,
        light_level: float,
        base_range: float = 30.0,
    ) -> float:
        """
        夜行性偵測範圍修正 — 光照越暗，偵測範圍越小（除了夜行性生物）。

        ╔══════════════════════════════════════════════════════════════╗
        ║  Detection Range Formula                                   ║
        ║                                                            ║
        ║  base_component = light_level（日光提供基礎視野）           ║
        ║  nv_component = night_vision × (1 - light_level)           ║
        ║    (夜間視力在黑暗中提供額外視野)                           ║
        ║                                                            ║
        ║  effective = base_range × max(base_component, nv_component)║
        ║                                                            ║
        ║  NOCTURNAL (nv=0.8):                                       ║
        ║    light=0.0 → 30 × max(0, 0.8) = 24.0                   ║
        ║    light=1.0 → 30 × max(1.0, 0) = 30.0                   ║
        ║  DIURNAL (nv=0.0):                                         ║
        ║    light=0.0 → 30 × max(0, 0) = 0 → clamp 3.0            ║
        ║    light=1.0 → 30 × max(1.0, 0) = 30.0                   ║
        ╚══════════════════════════════════════════════════════════════╝
        """
        attrs = sim.get_gene_attrs("nocturnality")
        if not attrs:
            return base_range * (0.3 + 0.7 * light_level)

        night_vision = attrs.get("night_vision", 0.0)
        # 日光提供基礎視野，夜間視力在黑暗中提供替代視野
        base_component = light_level
        nv_component = night_vision * (1.0 - light_level)
        effective = base_range * max(base_component, nv_component)
        return max(base_range * 0.1, effective)
