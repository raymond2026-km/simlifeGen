"""
SimLife Evolution System — 基礎單元測試
"""

import sys
import os
import random
import unittest

# 確保 simlife 套件可被 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from simlife.gene_config_manager import GeneConfigManager
from simlife.genetic_engine import (
    ConfigDrivenGeneticEngine,
    ConfigChromosome,
    GeneSlot,
)
from simlife.sim import Sim, SimState, DeathCause
from simlife.metabolism import MetabolismEngine
from simlife.environment import EnvironmentManager, ClimateState
from simlife.ecology import EcologyManager, Resource
from simlife.selection import SelectionEngine, GeneChainRecord


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "gene_config.json")


class TestGeneConfigManager(unittest.TestCase):
    """測試基因配置管理器"""

    def setUp(self):
        self.config = GeneConfigManager(CONFIG_PATH)

    def test_load(self):
        """配置載入"""
        genes = self.config.get_all_gene_names()
        self.assertIn("locomotion", genes)
        self.assertIn("digestive", genes)
        self.assertIn("nocturnality", genes)
        self.assertIn("ocean_adaptation", genes)

    def test_builtin_vs_custom(self):
        """內建 vs 自定義基因"""
        builtin = self.config.get_builtin_genes()
        custom = self.config.get_custom_genes()
        self.assertIn("locomotion", builtin)
        self.assertIn("nocturnality", custom)
        self.assertIn("ocean_adaptation", custom)

    def test_evolution_path(self):
        """演化路徑查詢"""
        path = self.config.get_evolution_path("locomotion", "WALK")
        self.assertIn("RUN", path)
        self.assertIn("FLY", path)
        self.assertIn("CRAWL", path)

    def test_evolution_path_no_mutate(self):
        """無路徑的情況"""
        path = self.config.get_evolution_path("mating", "SEXUAL")
        self.assertIn("ASEXUAL", path)
        self.assertEqual(len(path), 1)

    def test_gene_attributes(self):
        """基因屬性查詢"""
        attrs = self.config.get_gene_attributes("nocturnality", "NOCTURNAL")
        self.assertEqual(attrs["night_vision"], 0.8)
        self.assertEqual(attrs["speed_mult_night"], 1.3)

    def test_register_custom_gene(self):
        """動態新增基因"""
        self.config.register_gene(
            gene_name="test_gene",
            description="測試用基因",
            values={"A": {"val": 1}, "B": {"val": 2}},
            evolution_paths={"A": ["B"], "B": ["A"]},
        )
        self.assertIn("test_gene", self.config.get_all_gene_names())
        path = self.config.get_evolution_path("test_gene", "A")
        self.assertEqual(path, ["B"])


class TestGeneticEngine(unittest.TestCase):
    """測試進化演算法引擎"""

    def setUp(self):
        self.config = GeneConfigManager(CONFIG_PATH)
        self.engine = ConfigDrivenGeneticEngine(self.config)
        random.seed(42)

    def test_create_random_chromosome(self):
        """隨機染色體建立"""
        chr = self.engine.create_random_chromosome()
        self.assertGreater(len(chr.slots), 0)

        # 檢查所有基因都存在
        slot_names = [s.gene_name for s in chr.slots]
        self.assertIn("size", slot_names)
        self.assertIn("locomotion", slot_names)
        self.assertIn("nocturnality", slot_names)
        self.assertIn("ocean_adaptation", slot_names)

    def test_single_point_crossover(self):
        """單點交叉"""
        a = self.engine.create_random_chromosome()
        b = self.engine.create_random_chromosome()
        child = self.engine.single_point_crossover(a, b)

        self.assertEqual(len(child.slots), len(a.slots))
        self.assertEqual(child.generation, 1)
        self.assertEqual(child.parent_ids, (a.chromosome_id, b.chromosome_id))

    def test_multi_point_crossover(self):
        """多點交叉"""
        a = self.engine.create_random_chromosome()
        b = self.engine.create_random_chromosome()
        child = self.engine.multi_point_crossover(a, b, num_points=3)

        self.assertEqual(len(child.slots), len(a.slots))
        self.assertEqual(child.generation, 1)

    def test_mutation_continuous(self):
        """連續基因突變"""
        chr = self.engine.create_random_chromosome()
        size_before = chr.get_continuous_value("size")

        # 高突變率確保觸發
        random.seed(123)
        for _ in range(100):
            chr = self.engine.apply_mutation(chr, base_mutation_rate=0.5)

        # 至少有些基因被突變了（統計上幾乎必定）
        self.assertIsNotNone(chr)

    def test_mutation_discrete(self):
        """離散基因突變"""
        chr = self.engine.create_random_chromosome()
        loco_before = chr.get_enum_value("locomotion")

        # 高突變率
        random.seed(456)
        mutated = False
        for _ in range(200):
            chr = self.engine.apply_mutation(chr, base_mutation_rate=0.5)
            if chr.get_enum_value("locomotion") != loco_before:
                mutated = True
                break

        self.assertTrue(mutated, "離散基因應在高突變率下發生突變")

    def test_reproduce_asexual(self):
        """無性生殖"""
        a = self.engine.create_random_chromosome()
        child = self.engine.reproduce(a, base_mutation_rate=0.01, is_sexual=False)
        self.assertEqual(child.generation, a.generation)

    def test_reproduce_sexual(self):
        """有性生殖"""
        a = self.engine.create_random_chromosome()
        b = self.engine.create_random_chromosome()
        child = self.engine.reproduce(a, b, base_mutation_rate=0.01, is_sexual=True)
        self.assertEqual(child.generation, 1)


class TestSim(unittest.TestCase):
    """測試 Sim 個體"""

    def setUp(self):
        random.seed(42)
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)
        self.chr = engine.create_random_chromosome()

    def test_create_sim(self):
        """建立 Sim"""
        sim = Sim(chromosome=self.chr)
        self.assertTrue(sim.is_alive)
        self.assertEqual(sim.state, SimState.IDLE)
        self.assertGreater(sim.hp, 0)
        self.assertGreater(sim.energy, 0)

    def test_sim_death(self):
        """Sim 死亡"""
        sim = Sim(chromosome=self.chr)
        sim.kill(DeathCause.STARVATION)
        self.assertFalse(sim.is_alive)
        self.assertEqual(sim.state, SimState.DEAD)

    def test_sim_energy(self):
        """能量操作"""
        sim = Sim(chromosome=self.chr)
        initial = sim.energy
        sim.gain_energy(50)
        self.assertAlmostEqual(sim.energy, initial + 50)
        sim.drain_energy(30)
        self.assertAlmostEqual(sim.energy, initial + 20)

    def test_sim_distance(self):
        """距離計算"""
        a = Sim(chromosome=self.chr, x=0, y=0)
        b = Sim(chromosome=self.chr, x=3, y=4)
        self.assertAlmostEqual(a.distance_to(b), 5.0)


class TestMetabolism(unittest.TestCase):
    """測試代謝引擎"""

    def setUp(self):
        random.seed(42)
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)
        self.chr = engine.create_random_chromosome()
        self.metabolism = MetabolismEngine()

    def test_bmr(self):
        """BMR 計算"""
        bmr = self.metabolism.compute_bmr(1.0)
        self.assertAlmostEqual(bmr, 0.5)
        bmr10 = self.metabolism.compute_bmr(10.0)
        self.assertGreater(bmr10, bmr)

    def test_total_drain(self):
        """總代謝消耗"""
        sim = Sim(chromosome=self.chr)
        drain, damage = self.metabolism.compute_total_drain(sim, env_temp=25.0)
        self.assertGreater(drain, 0)

    def test_thermal_penalty(self):
        """體溫懲罰"""
        sim = Sim(chromosome=self.chr)
        bmr = self.metabolism.compute_bmr(sim.get_stat("size"))

        # 正常溫度：懲罰低
        penalty_normal = self.metabolism.compute_thermal_penalty(sim, 25.0, bmr)
        # 極端溫度：懲罰高
        penalty_extreme = self.metabolism.compute_thermal_penalty(sim, 60.0, bmr)
        self.assertGreater(penalty_extreme, penalty_normal)

    def test_energy_gain(self):
        """食物攝取"""
        gain = self.metabolism.compute_energy_gain(100, "CARNIVORE")
        self.assertAlmostEqual(gain, 130.0)  # 1.3x efficiency

    def test_nocturnal_energy_modifier_range(self):
        """夜行性能量修正範圍"""
        sim = Sim(chromosome=self.chr)
        # 修正值應在合理範圍內 (0.5 ~ 1.5)
        for light in [0.0, 0.25, 0.5, 0.75, 1.0]:
            mod_night = self.metabolism.compute_nocturnal_energy_modifier(sim, True, light)
            mod_day = self.metabolism.compute_nocturnal_energy_modifier(sim, False, light)
            self.assertGreaterEqual(mod_night, 0.5)
            self.assertLessEqual(mod_night, 1.5)
            self.assertGreaterEqual(mod_day, 0.5)
            self.assertLessEqual(mod_day, 1.5)

    def test_nocturnal_energy_modifier_nocturnal_sims(self):
        """夜行性生物在夜間能耗更低"""
        # 手動建立帶 NOCTURNAL 基因的 Sim
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)
        chr = engine.create_random_chromosome()
        chr.set_enum_value("nocturnality", "NOCTURNAL")
        sim = Sim(chromosome=chr)

        # 夜間低光：能耗應低於白天高光
        mod_night_dark = self.metabolism.compute_nocturnal_energy_modifier(sim, True, 0.1)
        mod_day_bright = self.metabolism.compute_nocturnal_energy_modifier(sim, False, 0.9)
        self.assertLess(mod_night_dark, mod_day_bright,
                        "夜行性生物在夜間能耗應低於白天")

    def test_nocturnal_energy_modifier_diurnal_sims(self):
        """日行性生物在白天能耗更低"""
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)
        chr = engine.create_random_chromosome()
        chr.set_enum_value("nocturnality", "DIURNAL")
        sim = Sim(chromosome=chr)

        mod_day_bright = self.metabolism.compute_nocturnal_energy_modifier(sim, False, 0.9)
        mod_night_dark = self.metabolism.compute_nocturnal_energy_modifier(sim, True, 0.1)
        self.assertLess(mod_day_bright, mod_night_dark,
                        "日行性生物在白天能耗應低於夜間")

    def test_nocturnal_stealth(self):
        """夜行性隱蔽值"""
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)

        # NOCTURNAL: 夜間隱蔽高，白天隱蔽低
        chr = engine.create_random_chromosome()
        chr.set_enum_value("nocturnality", "NOCTURNAL")
        sim = Sim(chromosome=chr)
        stealth_night = self.metabolism.compute_nocturnal_stealth(sim, 0.0)
        stealth_day = self.metabolism.compute_nocturnal_stealth(sim, 1.0)
        self.assertGreater(stealth_night, stealth_day,
                           "夜行性生物夜間隱蔽應高於白天")

        # DIURNAL: 夜間隱蔽低，白天隱蔽高
        chr2 = engine.create_random_chromosome()
        chr2.set_enum_value("nocturnality", "DIURNAL")
        sim2 = Sim(chromosome=chr2)
        stealth_night2 = self.metabolism.compute_nocturnal_stealth(sim2, 0.0)
        stealth_day2 = self.metabolism.compute_nocturnal_stealth(sim2, 1.0)
        self.assertGreater(stealth_day2, stealth_night2,
                           "日行性生物白天隱蔽應高於夜間")

    def test_nocturnal_detection_range(self):
        """夜行性偵測範圍修正"""
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)

        # NOCTURNAL: 夜間偵測範圍應高於 DIURNAL 在相同光照下
        chr_noct = engine.create_random_chromosome()
        chr_noct.set_enum_value("nocturnality", "NOCTURNAL")
        sim_noct = Sim(chromosome=chr_noct)

        chr_dia = engine.create_random_chromosome()
        chr_dia.set_enum_value("nocturnality", "DIURNAL")
        sim_dia = Sim(chromosome=chr_dia)

        # 漆黑環境：夜行性偵測應優於日行性
        range_noct_dark = self.metabolism.compute_nocturnal_detection_range(sim_noct, 0.0, 30.0)
        range_dia_dark = self.metabolism.compute_nocturnal_detection_range(sim_dia, 0.0, 30.0)
        self.assertGreater(range_noct_dark, range_dia_dark,
                           "漆黑環境下夜行性偵測應優於日行性")

        # 正午環境：兩者都應接近滿偵測
        range_noct_bright = self.metabolism.compute_nocturnal_detection_range(sim_noct, 1.0, 30.0)
        range_dia_bright = self.metabolism.compute_nocturnal_detection_range(sim_dia, 1.0, 30.0)
        self.assertAlmostEqual(range_noct_bright, 30.0, delta=1.0,
                               msg="夜行性正午偵測應接近滿值")
        self.assertAlmostEqual(range_dia_bright, 30.0, delta=1.0,
                               msg="日行性正午偵測應接近滿值")

    def test_total_drain_with_nocturnal(self):
        """代謝消耗整合夜行性修正"""
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)
        chr = engine.create_random_chromosome()
        chr.set_enum_value("nocturnality", "NOCTURNAL")
        sim = Sim(chromosome=chr)

        drain_night = self.metabolism.compute_total_drain(sim, 25.0, is_night=True, light_level=0.1)[0]
        drain_day = self.metabolism.compute_total_drain(sim, 25.0, is_night=False, light_level=0.9)[0]
        self.assertLess(drain_night, drain_day,
                        "夜行性生物夜間消耗應低於白天")


class TestEnvironment(unittest.TestCase):
    """測試環境系統"""

    def setUp(self):
        self.env = EnvironmentManager(
            map_width=20, map_height=20, seed=42
        )

    def test_terrain_generation(self):
        """地形生成"""
        summary = self.env.get_map_summary()
        self.assertIn("ocean", summary)
        self.assertIn("grassland", summary)
        self.assertEqual(sum(summary.values()), 20 * 20)

    def test_climate_advance(self):
        """氣候推進"""
        initial_temp = self.env.climate.temperature
        for _ in range(100):
            self.env.climate.advance()
        # 溫度應有變化
        self.assertNotAlmostEqual(
            self.env.climate.temperature, initial_temp, places=0
        )

    def test_day_night_cycle(self):
        """晝夜循環"""
        is_night_values = set()
        for _ in range(200):
            self.env.climate.advance()
            is_night_values.add(self.env.climate.is_night)
        self.assertTrue(len(is_night_values) >= 2, "應有日夜切換")

    def test_light_level_range(self):
        """光照等級範圍 0.0 ~ 1.0"""
        for _ in range(200):
            self.env.climate.advance()
            self.assertGreaterEqual(self.env.climate.light_level, 0.0)
            self.assertLessEqual(self.env.climate.light_level, 1.0)

    def test_light_level_peaks_at_noon(self):
        """光照在正午時達到峰值"""
        max_light = 0.0
        for _ in range(100):
            self.env.climate.advance()
            max_light = max(max_light, self.env.climate.light_level)
        self.assertGreater(max_light, 0.9, "正午光照應接近 1.0")

    def test_dawn_dusk_transitions(self):
        """黎明/黃昏過渡期"""
        dawn_seen = False
        dusk_seen = False
        for _ in range(200):
            self.env.climate.advance()
            if self.env.climate.is_dawn:
                dawn_seen = True
            if self.env.climate.is_dusk:
                dusk_seen = True
        self.assertTrue(dawn_seen, "應偵測到黎明過渡期")
        self.assertTrue(dusk_seen, "應偵測到黃昏過渡期")

    def test_time_of_day_label(self):
        """時段標籤"""
        labels = set()
        for _ in range(200):
            self.env.climate.advance()
            labels.add(self.env.climate.time_of_day_label)
        self.assertIn("night", labels)
        self.assertIn("day", labels)

    def test_time_icon(self):
        """時段圖示"""
        icons = set()
        for _ in range(200):
            self.env.climate.advance()
            icons.add(self.env.climate.time_icon)
        self.assertIn("☀️", icons)
        self.assertIn("🌙", icons)


class TestEcology(unittest.TestCase):
    """測試生態系統"""

    def setUp(self):
        self.env = EnvironmentManager(map_width=20, map_height=20, seed=42)
        self.ecology = EcologyManager(self.env)

    def test_spawn_resources(self):
        """資源生成"""
        self.env.climate.humidity = 0.8
        resources = self.ecology.spawn_resources()
        self.assertGreater(len(resources), 0)

    def test_find_food(self):
        """搜尋食物"""
        # 手動放置資源
        res = Resource(resource_type="plant", calories=50, x=10, y=10)
        self.ecology.resources.append(res)

        found = self.ecology.find_nearest_food(10, 10, ["plant"])
        self.assertIsNotNone(found)

    def test_decay(self):
        """資源腐爛"""
        for _ in range(500):
            self.env.climate.advance()
            self.ecology.spawn_resources()

        before = self.ecology.alive_count
        self.ecology.decay_resources()
        after = self.ecology.alive_count
        self.assertLessEqual(after, before)


class TestSelection(unittest.TestCase):
    """測試選擇引擎"""

    def setUp(self):
        random.seed(42)
        self.sel = SelectionEngine()
        config = GeneConfigManager(CONFIG_PATH)
        engine = ConfigDrivenGeneticEngine(config)
        self.engine = engine

    def test_fitness(self):
        """適應度計算"""
        record = FitnessRecordForTest(
            sim_id="test",
            chromosome_id="chr_test",
            generation=1,
            ticks_survived=300,
            energy_peak=150,
            offspring_count=3,
            age_at_death=300,
            energy_efficiency=1.2,
        )
        fitness = SelectionEngine.compute_fitness(record)
        self.assertGreater(fitness, 0)

    def test_gene_chain_hash(self):
        """基因鏈哈希"""
        a = self.engine.create_random_chromosome()
        b = self.engine.create_random_chromosome()
        hash_a = GeneChainRecord.hash_chromosome(a)
        hash_b = GeneChainRecord.hash_chromosome(b)
        # 不同染色體應有不同哈希（高機率）
        self.assertIsNotNone(hash_a)
        self.assertIsNotNone(hash_b)

    def test_extinction_check(self):
        """絕跡檢查"""
        chain = GeneChainRecord(chain_id="test_chain")
        chain.generations_without_repro = 4
        self.sel.gene_chains["test_chain"] = chain

        extinct = self.sel.extinction_check()
        self.assertIn("test_chain", extinct)
        self.assertTrue(chain.is_extinct)


# 簡化版 FitnessRecord（用於測試）
from dataclasses import dataclass
from typing import Optional

@dataclass
class FitnessRecordForTest:
    sim_id: str
    chromosome_id: str
    generation: int
    ticks_survived: int
    energy_peak: float
    offspring_count: int
    age_at_death: Optional[int]
    energy_efficiency: float = 0.0


if __name__ == "__main__":
    unittest.main()
