"""
SimulationEngine — 主模擬引擎

整合所有模組，驅動 tick-based 模擬循環。

╔══════════════════════════════════════════════════════════╗
║                   模擬時鐘流程                           ║
║                                                        ║
║  for each tick:                                        ║
║    1. environment.advance()         → 氣候 + 晝夜       ║
║    2. ecology.spawn_resources()     → 生成資源          ║
║    3. ecology.decay_resources()     → 資源腐爛          ║
║    4. for each sim:                                     ║
║       a. 行為決策 (BehaviorDecider)                    ║
║       b. 代謝計算 (MetabolismEngine)                   ║
║       c. 能量/HP 更新                                  ║
║       d. 死亡判定                                      ║
║    5. 繁殖階段                                         ║
║       a. 篩選繁殖候選者                                 ║
║       b. 適應度排序 + 選擇親本                          ║
║       c. 交叉 + 突變 → 產生新生代                       ║
║    6. 絕跡檢查                                         ║
║    7. 統計輸出                                         ║
╚══════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from .gene_config_manager import GeneConfigManager
from .genetic_engine import ConfigDrivenGeneticEngine, ConfigChromosome
from .sim import Sim, SimState, DeathCause
from .metabolism import MetabolismEngine
from .environment import EnvironmentManager
from .ecology import EcologyManager, Resource
from .selection import SelectionEngine


# ════════════════════════════════════════════════════════════════
#  模擬配置
# ════════════════════════════════════════════════════════════════

@dataclass
class SimulationConfig:
    """模擬參數"""
    # 種群
    initial_population: int = 50
    max_population: int = 200
    reproduction_energy_threshold: float = 80.0
    reproduction_cooldown: int = 20
    max_offspring_per_tick: int = 5

    # 環境
    map_width: int = 50
    map_height: int = 50
    ticks_per_season: int = 200
    ticks_per_day: int = 100

    # 進化
    base_mutation_rate: float = 0.01
    crossover_method: str = "single"  # "single" / "multi"

    # 選擇
    extinction_threshold: int = 3

    # 基因配置路徑
    gene_config_path: str = "configs/gene_config.json"

    # 模擬範圍
    max_ticks: int = 2000

    # 隨機種子
    seed: Optional[int] = None


# ════════════════════════════════════════════════════════════════
#  行為決策器
# ════════════════════════════════════════════════════════════════

class BehaviorDecider:
    """
    行為決策器 — 基於基因型決定模擬人的行為。

    Fear/Aggression 決策模型：
      fear_weight = (1 - fa) × (1 - ally_bonus)
      aggression_weight = fa × (0.5 + 0.5 × (1 - enemy_hp_ratio))

    Predation Stealth 模型：
      被偵測機率 = (1 - attacker_stealth) × detection_range / distance
      stealth 由 nocturnality 基因 + light_level 決定
    """

    BASE_DETECTION_RANGE: float = 30.0

    @staticmethod
    def decide_conflict(
        sim: Sim,
        threat_distance: float,
        has_ally_nearby: bool,
        enemy_hp_ratio: float,
        attacker_stealth: float = 0.5,
        defender_stealth: float = 0.5,
    ) -> SimState:
        """
        決定面對威脅時的行為。

        stealth 差異影響決策：
          - 攻擊者 stealth 高 → 防禦者更傾向逃跑（感覺不到威脅）
          - 防禦者 stealth 高 → 防禦者更傾向戰鬥（有優勢）
        """
        fa = sim.chromosome.get_slot("fear_aggression").value
        soc = sim.chromosome.get_slot("sociability").value
        hp_ratio = sim.hp / max(1.0, sim.get_stat("base_hp"))

        ally_bonus = 0.3 if (has_ally_nearby and soc > 0.5) else 0.0
        fear_weight = (1.0 - fa) * (1.0 - ally_bonus)
        aggression_weight = fa * (0.5 + 0.5 * (1.0 - enemy_hp_ratio))

        urgency = max(0.5, 1.0 - threat_distance / BehaviorDecider.BASE_DETECTION_RANGE)
        fear_weight *= urgency
        aggression_weight *= urgency

        # Stealth 差異修正：隱蔽越高，越有優勢
        stealth_advantage = defender_stealth - attacker_stealth
        aggression_weight *= (1.0 + stealth_advantage * 0.5)  # 隱蔽優勢增加攻擊意願
        fear_weight *= (1.0 - stealth_advantage * 0.3)        # 隱蔽優勢降低恐懼

        if hp_ratio < 0.3:
            fear_weight *= 1.5

        if fear_weight > aggression_weight:
            return SimState.FLEEING
        elif aggression_weight > fear_weight:
            return SimState.FIGHTING
        return SimState.IDLE

    @staticmethod
    def decide_resource_competition(
        sim: Sim,
        resource: Resource,
        num_competitors: int,
    ) -> str:
        soc = sim.chromosome.get_slot("sociability").value
        fa = sim.chromosome.get_slot("fear_aggression").value
        territory = sim.get_gene("territory")

        if num_competitors <= 1:
            return "consume"

        if territory == "SOLO":
            hp_ratio = sim.hp / max(1.0, sim.get_stat("base_hp"))
            if fa > 0.6 and hp_ratio > 0.4:
                return "compete"
            elif fa < 0.3:
                return "flee"
            return "compete"

        elif territory == "PACK":
            return "wait" if soc > 0.5 else "compete"

        else:  # NOMADIC
            return "flee" if num_competitors > 3 else "compete"


# ════════════════════════════════════════════════════════════════
#  主模擬引擎
# ════════════════════════════════════════════════════════════════

class SimulationEngine:
    """
    主模擬引擎 — 整合所有子系統。
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or SimulationConfig()

        if self.config.seed is not None:
            random.seed(self.config.seed)

        # 子系統初始化
        self.gene_config = GeneConfigManager(self.config.gene_config_path)
        self.genetic_engine = ConfigDrivenGeneticEngine(self.gene_config)
        self.metabolism = MetabolismEngine()
        self.environment = EnvironmentManager(
            map_width=self.config.map_width,
            map_height=self.config.map_height,
            ticks_per_season=self.config.ticks_per_season,
            ticks_per_day=self.config.ticks_per_day,
        )
        self.ecology = EcologyManager(self.environment)
        self.selection = SelectionEngine()
        self.behavior = BehaviorDecider()

        # 狀態
        self.tick_count: int = 0
        self.generation: int = 0
        self.population: list[Sim] = []
        self.death_log: list[dict] = []
        self.birth_log: list[str] = []
        self.mutation_log: list[dict] = []
        self.extinct_log: list[str] = []

        # 歷史
        self.tick_stats: list[dict] = []

        # 初始種群
        self._spawn_initial_population()

    def _spawn_initial_population(self) -> None:
        """產生初始種群"""
        for _ in range(self.config.initial_population):
            chr = self.genetic_engine.create_random_chromosome()
            sim = Sim(
                chromosome=chr,
                x=random.uniform(0, self.config.map_width - 1),
                y=random.uniform(0, self.config.map_height - 1),
            )
            sim.current_terrain = self.environment.get_terrain_at(sim.x, sim.y)
            self.population.append(sim)

    # ── 主 Tick 循環 ──────────────────────────────────────

    def run_tick(self) -> dict:
        """執行一個模擬幀"""
        self.tick_count += 1
        self.selection.set_tick(self.tick_count)

        # Step 1: 環境推進
        self.environment.advance()

        # Step 2 & 3: 資源生成與腐爛
        self.ecology.spawn_resources()
        self.ecology.decay_resources()

        # Step 4: 個體行為循環
        deaths = []
        survivors = []
        births_this_tick = 0

        for sim in self.population:
            if not sim.is_alive:
                continue

            # 4a: 更新地形
            sim.current_terrain = self.environment.get_terrain_at(sim.x, sim.y)

            # 4b: 行為決策
            self._sim_action_tick(sim)

            # 4c: 代謝（含夜行性能量修正）
            drain, damage = self.metabolism.compute_total_drain(
                sim,
                self.environment.climate.temperature,
                is_night=self.environment.climate.is_night,
                light_level=self.environment.climate.light_level,
            )
            sim.apply_drain(drain, damage)

            # 水中額外消耗
            if sim.current_terrain in ("ocean", "river", "swamp"):
                water_drain = self.metabolism.compute_water_drain(sim)
                sim.drain_energy(water_drain)
                sim.ticks_in_water += 1

            # 4d: 推進 tick
            sim.advance_tick()

            # 4e: 死亡判定
            if sim.check_death():
                survivors.append(sim)
            else:
                deaths.append(sim)
                self.death_log.append({
                    "tick": self.tick_count,
                    "sim_id": sim.sim_id,
                    "cause": sim.death_cause.value if sim.death_cause else "unknown",
                    "age": sim.age_ticks,
                    "generation": sim.chromosome.generation,
                })

        self.population = survivors

        # Step 5: 繁殖
        births_this_tick = self._reproduction_phase()
        self.birth_log.append(str(births_this_tick))

        # Step 6: 絕跡檢查
        extinct = self.selection.extinction_check()
        self.extinct_log.extend(extinct)

        # Step 7: 統計
        stats = self._compute_tick_stats(deaths, births_this_tick)
        self.tick_stats.append(stats)
        return stats

    # ── 個體行為 ──────────────────────────────────────────

    def _sim_action_tick(self, sim: Sim) -> None:
        """
        處理個體的行為邏輯。

        整合夜行性基因修正：
          1. 移動速度：套用 nocturnality speed_mult_day/night
          2. 偵測範圍：夜行性生物在黑暗中保持高偵測
          3. 隱蔽值：影響被天敵偵測的機率
          4. 搜尋範圍：光照越暗，日行性生物搜尋範圍越小
        """
        climate = self.environment.climate
        is_night = climate.is_night
        light_level = climate.light_level

        # 取得夜行性修正
        noct_speed_mod = self.metabolism.apply_nocturnal_modifier(sim, is_night)
        stealth = self.metabolism.compute_nocturnal_stealth(sim, light_level)
        detection_range = self.metabolism.compute_nocturnal_detection_range(
            sim, light_level, base_range=self.behavior.BASE_DETECTION_RANGE
        )

        # 光照影響搜尋範圍：日行性生物在夜間搜尋範圍縮小
        base_search_range = 100.0
        noct_attrs = sim.get_gene_attrs("nocturnality")
        night_vision = noct_attrs.get("night_vision", 0.0)
        # 夜間視力越強，搜尋範圍縮減越少
        search_range = base_search_range * (night_vision * 1.0 + (1.0 - night_vision) * light_level)
        search_range = max(10.0, search_range)

        # 找食物
        attrs = self.gene_config.get_gene_attributes("digestive", sim.get_gene("digestive"))
        edible = attrs.get("edible_prefixes", ["plant"])

        nearest_food = self.ecology.find_nearest_food(
            sim.x, sim.y, edible, max_range=search_range
        )

        if nearest_food:
            dist = sim.distance_to_point(nearest_food.x, nearest_food.y)
            if dist <= 2.0:
                # 吃！
                cal = nearest_food.consume()
                gain = self.metabolism.compute_energy_gain(cal, sim.get_gene("digestive"))
                sim.gain_energy(gain)
                sim.state = SimState.IDLE
            else:
                # 移向食物（套用夜行性速度修正）
                speed = self.metabolism.compute_effective_speed(sim) * noct_speed_mod
                sim.move_towards(nearest_food.x, nearest_food.y, speed)
                sim.state = SimState.FORAGING
        else:
            # 無食物，隨機漫步（套用夜行性速度修正）
            speed = self.metabolism.compute_effective_speed(sim) * noct_speed_mod * 0.3
            tx = sim.x + random.uniform(-10, 10)
            ty = sim.y + random.uniform(-10, 10)
            sim.move_towards(tx, ty, speed)
            sim.state = SimState.IDLE

        # 邊界保護
        sim.x = max(0, min(sim.x, self.config.map_width - 1))
        sim.y = max(0, min(sim.y, self.config.map_height - 1))

    # ── 繁殖階段 ──────────────────────────────────────────

    def _reproduction_phase(self) -> int:
        """繁殖階段。回傳本 tick 產生的後代數。"""
        if len(self.population) >= self.config.max_population:
            return 0

        candidates = [s for s in self.population if s.can_reproduce]
        if len(candidates) < 2:
            return 0

        max_new = min(
            self.config.max_offspring_per_tick,
            self.config.max_population - len(self.population),
        )

        new_borns = []
        for _ in range(max_new):
            if len(candidates) < 2:
                break

            chosen = random.choice(candidates)

            if chosen.get_gene("mating") == "SEXUAL" and len(candidates) >= 2:
                # 有性生殖
                parents = SelectionEngine.roulette_select(candidates, 2)
                parent_a, parent_b = parents[0], parents[1]

                if parent_a.sim_id == parent_b.sim_id:
                    continue

                child_chr = self.genetic_engine.crossover(
                    parent_a.chromosome, parent_b.chromosome,
                    method=self.config.crossover_method,
                )
                child_chr = self.genetic_engine.apply_mutation(
                    child_chr, self.config.base_mutation_rate
                )

                parent_a.energy -= 20
                parent_b.energy -= 20
                parent_a.repro_cooldown = self.config.reproduction_cooldown
                parent_b.repro_cooldown = self.config.reproduction_cooldown
                parent_a.offspring_count += 1
                parent_b.offspring_count += 1
            else:
                # 無性生殖
                child_chr = chosen.chromosome.clone()
                child_chr = self.genetic_engine.apply_mutation(
                    child_chr, self.config.base_mutation_rate * 1.5
                )
                chosen.energy -= 30
                chosen.repro_cooldown = self.config.reproduction_cooldown
                chosen.offspring_count += 1

            # 建立新生代
            baby = Sim(
                chromosome=child_chr,
                x=chosen.x + random.uniform(-5, 5),
                y=chosen.y + random.uniform(-5, 5),
            )
            baby.x = max(0, min(baby.x, self.config.map_width - 1))
            baby.y = max(0, min(baby.y, self.config.map_height - 1))
            baby.current_terrain = self.environment.get_terrain_at(baby.x, baby.y)

            # 追蹤基因鏈
            chain_id = self.selection.track_birth(baby)
            self.selection.track_reproduction(chain_id)

            new_borns.append(baby)

        self.population.extend(new_borns)
        return len(new_borns)

    # ── 統計 ──────────────────────────────────────────────

    def _compute_tick_stats(self, deaths: list, births: int) -> dict:
        """計算每 tick 統計"""
        alive = [s for s in self.population if s.is_alive]
        climate = self.environment.climate

        # 夜行性基因分佈
        noct_dist = {}
        for sim in alive:
            noct = sim.get_gene("nocturnality")
            noct_dist[noct] = noct_dist.get(noct, 0) + 1

        return {
            "tick": self.tick_count,
            "population": len(alive),
            "deaths": len(deaths),
            "births": births,
            "temperature": round(climate.temperature, 1),
            "humidity": round(climate.humidity, 3),
            "season": climate.season,
            "is_night": climate.is_night,
            "is_dawn": climate.is_dawn,
            "is_dusk": climate.is_dusk,
            "light_level": round(climate.light_level, 3),
            "time_of_day": climate.time_of_day_label,
            "resources": self.ecology.alive_count,
            "gene_chains": self.selection.get_stats()["active_chains"],
            "nocturnality_dist": noct_dist,
        }

    # ── 完整模擬 ──────────────────────────────────────────

    def run(self, verbose: bool = True) -> list[dict]:
        """執行完整模擬"""
        if verbose:
            print(f"🧬 SimLife Evolution System — 開始模擬")
            print(f"   初始種群: {len(self.population)} | 目標 tick: {self.config.max_ticks}")
            print("=" * 70)

        for _ in range(self.config.max_ticks):
            stats = self.run_tick()

            if verbose and self.tick_count % 100 == 0:
                time_icon = self.environment.climate.time_icon
                light = stats['light_level']
                noct = stats.get('nocturnality_dist', {})
                noct_str = ", ".join(f"{k}:{v}" for k, v in noct.items()) if noct else "-"
                print(
                    f"  Tick {stats['tick']:5d} | "
                    f"種群: {stats['population']:4d} | "
                    f"死亡: {stats['deaths']:3d} | "
                    f"出生: {stats['births']:2d} | "
                    f"資源: {stats['resources']:4d} | "
                    f"溫度: {stats['temperature']:6.1f}°C | "
                    f"{time_icon} 光:{light:.2f} | "
                    f"夜行: {noct_str}"
                )

            if len(self.population) == 0:
                if verbose:
                    print("\n💀 所有模擬人已滅絕！")
                break

        if verbose:
            print("=" * 70)
            print(f"✅ 模擬完成 — 結束種群: {len(self.population)}")
            self._print_final_report()

        return self.tick_stats

    def _print_final_report(self) -> None:
        """輸出最終報告"""
        if not self.population:
            print("  所有模擬人已滅絕！")
            return

        # 基因分佈
        gene_dists = {}
        for sim in self.population:
            for slot in sim.chromosome.slots:
                if not slot.is_continuous:
                    if slot.gene_name not in gene_dists:
                        gene_dists[slot.gene_name] = {}
                    val = slot.enum_value
                    gene_dists[slot.gene_name][val] = gene_dists[slot.gene_name].get(val, 0) + 1

        print("\n📊 最終種群基因分佈:")
        for gene_name, dist in gene_dists.items():
            print(f"  {gene_name}: {dist}")

        # 絕跡統計
        sel_stats = self.selection.get_stats()
        print(f"\n🔬 基因鏈統計:")
        print(f"  總鏈數: {sel_stats['total_chains']}")
        print(f"  存活鏈: {sel_stats['active_chains']}")
        print(f"  絕跡鏈: {sel_stats['extinct_chains']}")

        # 夜行性分佈
        noct_dist = {}
        for sim in self.population:
            noct = sim.get_gene("nocturnality")
            noct_dist[noct] = noct_dist.get(noct, 0) + 1
        print(f"\n🌙 夜行性分佈: {noct_dist}")
        # 夜行性平均隱蔽值
        alive = [s for s in self.population if s.is_alive]
        if alive:
            stealth_vals = [
                self.metabolism.compute_nocturnal_stealth(s, 0.0)  # 夜間隱蔽
                for s in alive
            ]
            avg_night_stealth = sum(stealth_vals) / len(stealth_vals)
            stealth_vals_day = [
                self.metabolism.compute_nocturnal_stealth(s, 1.0)  # 白天隱蔽
                for s in alive
            ]
            avg_day_stealth = sum(stealth_vals_day) / len(stealth_vals_day)
            print(f"   平均夜間隱蔽: {avg_night_stealth:.3f} | 平均白天隱蔽: {avg_day_stealth:.3f}")

        # 死因統計
        death_causes = {}
        for d in self.death_log:
            cause = d["cause"]
            death_causes[cause] = death_causes.get(cause, 0) + 1
        print(f"\n💀 死因統計: {death_causes}")

    # ── 存取 API ──────────────────────────────────────────

    def get_population_summary(self) -> dict:
        """取得當前種群摘要"""
        alive = [s for s in self.population if s.is_alive]
        return {
            "count": len(alive),
            "avg_age": sum(s.age_ticks for s in alive) / max(1, len(alive)),
            "avg_energy": sum(s.energy for s in alive) / max(1, len(alive)),
            "avg_hp": sum(s.hp for s in alive) / max(1, len(alive)),
        }
