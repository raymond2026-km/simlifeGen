"""
GeneticEngine — 進化演算法引擎（配置驅動版）

本模組是原始版 GeneticEngine 的升級替代。
所有硬編碼的演化路徑已被移除，改由 GeneConfigManager 從 JSON 動態載入。

使用方式：
    from gene_config_manager import GeneConfigManager
    from genetic_engine import ConfigDrivenGeneticEngine

    config = GeneConfigManager("configs/gene_config.json")
    engine = ConfigDrivenGeneticEngine(config)

    child = engine.crossover(parent_a, parent_b)
    child = engine.apply_mutation(child, base_mutation_rate=0.01)
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any, Optional

from gene_config_manager import GeneConfigManager, EnumGeneDefinition, GeneValue


# ════════════════════════════════════════════════════════════════
#  基因槽位 (Gene Slot) — 統一表示一個基因的值
# ════════════════════════════════════════════════════════════════

@dataclass
class GeneSlot:
    """
    一個基因槽位 — 可以是連續數值或離散列舉。
    交叉與突變都透過操作 GeneSlot 進行。
    """
    gene_name: str
    is_continuous: bool
    # 連續基因
    value: float = 0.0
    min_val: float = 0.0
    max_val: float = 1.0
    is_int: bool = False
    # 離散基因
    enum_value: str = ""
    gene_def: Optional[EnumGeneDefinition] = None

    @classmethod
    def continuous(
        cls,
        name: str,
        value: float,
        min_val: float = 0.0,
        max_val: float = 1.0,
        is_int: bool = False,
    ) -> GeneSlot:
        return cls(
            gene_name=name,
            is_continuous=True,
            value=max(min_val, min(value, max_val)),
            min_val=min_val,
            max_val=max_val,
            is_int=is_int,
        )

    @classmethod
    def discrete(
        cls,
        name: str,
        value: str,
        gene_def: EnumGeneDefinition,
    ) -> GeneSlot:
        if not gene_def.is_valid_value(value):
            raise ValueError(f"基因 '{name}' 沒有值 '{value}'")
        return cls(
            gene_name=name,
            is_continuous=False,
            enum_value=value,
            gene_def=gene_def,
        )

    def clone(self) -> GeneSlot:
        return copy.deepcopy(self)

    def __repr__(self) -> str:
        if self.is_continuous:
            return f"GeneSlot({self.gene_name}={self.value:.3f})"
        return f"GeneSlot({self.gene_name}={self.enum_value})"


# ════════════════════════════════════════════════════════════════
#  Chromosome — 由 GeneSlot 列表組成
# ════════════════════════════════════════════════════════════════

@dataclass
class ConfigChromosome:
    """
    配置驅動的染色體 — 用 GeneSlot 列表取代硬編碼的基因欄位。
    這使得染色體結構完全由 JSON 配置決定。
    """
    slots: list[GeneSlot]
    generation: int = 0
    parent_ids: tuple[str, str] = ("init", "init")
    chromosome_id: str = ""

    def __post_init__(self):
        if not self.chromosome_id:
            self.chromosome_id = f"chr_{random.randint(100000, 999999)}"

    def clone(self) -> ConfigChromosome:
        return copy.deepcopy(self)

    def get_slot(self, gene_name: str) -> GeneSlot:
        """依名稱取得基因槽位"""
        for slot in self.slots:
            if slot.gene_name == gene_name:
                return slot
        raise KeyError(f"染色體中沒有基因 '{gene_name}'")

    def get_enum_value(self, gene_name: str) -> str:
        """快速取得某離散基因的當前值"""
        slot = self.get_slot(gene_name)
        if slot.is_continuous:
            raise TypeError(f"基因 '{gene_name}' 是連續基因，不是離散基因")
        return slot.enum_value

    def get_continuous_value(self, gene_name: str) -> float:
        """快速取得某連續基因的當前值"""
        slot = self.get_slot(gene_name)
        if not slot.is_continuous:
            raise TypeError(f"基因 '{gene_name}' 是離散基因，不是連續基因")
        return slot.value

    def set_enum_value(self, gene_name: str, new_value: str) -> None:
        """設定某離散基因的值"""
        slot = self.get_slot(gene_name)
        if slot.is_continuous:
            raise TypeError(f"基因 '{gene_name}' 是連續基因")
        if not slot.gene_def.is_valid_value(new_value):
            raise ValueError(
                f"基因 '{gene_name}' 沒有值 '{new_value}'。"
                f"可用: {slot.gene_def.all_value_names()}"
            )
        slot.enum_value = new_value

    def __repr__(self) -> str:
        slot_strs = ", ".join(repr(s) for s in self.slots)
        return f"ConfigChromosome(gen={self.generation}, {slot_strs})"


# ════════════════════════════════════════════════════════════════
#  配置驅動的進化引擎
# ════════════════════════════════════════════════════════════════

class ConfigDrivenGeneticEngine:
    """
    進化演算法引擎 — 所有演化路徑由 GeneConfigManager 配置驅動。

    設計師只需編輯 JSON 即可：
      - 新增基因（夜行性、海洋適應等）
      - 調整演化路徑
      - 改變突變率
      - 新增/移除基因值
    """

    def __init__(self, config_manager: GeneConfigManager):
        self.config = config_manager
        self._mutation_cache: dict[str, float] = {}  # gene → effective mutation rate

    # ── 建立隨機染色體 ──────────────────────────────────────

    def create_random_chromosome(self) -> ConfigChromosome:
        """
        根據配置檔隨機建立一條染色體。
        會自動包含所有已啟用的基因（內建 + 自定義）。
        """
        slots = []

        # 內建連續基因（這些保持硬編碼範圍，因為它們沒有在 JSON 中定義）
        # 設計師如需調整，可擴展 JSON 的 continuous_genes 區段
        BUILTIN_CONTINUOUS = {
            "size":              (0.1, 10.0, False),
            "lifespan":          (50.0, 1000.0, True),
            "sociability":       (0.0, 1.0, False),
            "fear_aggression":   (0.0, 1.0, False),
            "base_hp":           (10.0, 500.0, True),
        }
        for name, (lo, hi, is_int) in BUILTIN_CONTINUOUS.items():
            val = random.uniform(lo, hi)
            slots.append(GeneSlot.continuous(name, val, lo, hi, is_int))

        # 所有列舉基因（內建 + 自定義）
        for gene_name in self.config.get_all_gene_names():
            gene_def = self.config.get_gene(gene_name)
            random_value = random.choice(gene_def.all_value_names())
            slots.append(GeneSlot.discrete(gene_name, random_value, gene_def))

        return ConfigChromosome(slots=slots, generation=0)

    # ── 交叉 (Crossover) ────────────────────────────────────

    def single_point_crossover(
        self,
        parent_a: ConfigChromosome,
        parent_b: ConfigChromosome,
    ) -> ConfigChromosome:
        """
        單點交叉 — 在隨機切點處切開，前段取自 A，後段取自 B。
        兩個父代的基因槽位順序必須一致（由建立時保證）。
        """
        n = len(parent_a.slots)
        if n != len(parent_b.slots):
            raise ValueError(
                f"父母染色體基因數量不一致: {len(parent_a.slots)} vs {len(parent_b.slots)}"
            )

        cut_point = random.randint(1, n - 1)
        child_slots = []

        for i in range(n):
            if i < cut_point:
                source = parent_a.slots[i]
            else:
                source = parent_b.slots[i]
            child_slots.append(source.clone())

        return ConfigChromosome(
            slots=child_slots,
            generation=max(parent_a.generation, parent_b.generation) + 1,
            parent_ids=(parent_a.chromosome_id, parent_b.chromosome_id),
        )

    def multi_point_crossover(
        self,
        parent_a: ConfigChromosome,
        parent_b: ConfigChromosome,
        num_points: int = 3,
    ) -> ConfigChromosome:
        """
        多點交叉 — 產生 num_points 個隨機切點，交替取用父母基因。
        """
        n = len(parent_a.slots)
        if n != len(parent_b.slots):
            raise ValueError("父母染色體基因數量不一致")

        points = sorted(random.sample(range(1, n), min(num_points, n - 1)))
        points = [0] + points + [n]

        child_slots = []
        use_a = True
        for i in range(len(points) - 1):
            source = parent_a if use_a else parent_b
            for j in range(points[i], points[i + 1]):
                child_slots.append(source.slots[j].clone())
            use_a = not use_a

        return ConfigChromosome(
            slots=child_slots,
            generation=max(parent_a.generation, parent_b.generation) + 1,
            parent_ids=(parent_a.chromosome_id, parent_b.chromosome_id),
        )

    def crossover(
        self,
        parent_a: ConfigChromosome,
        parent_b: ConfigChromosome,
        method: str = "single",
    ) -> ConfigChromosome:
        """
        統一交叉入口。method: "single" / "multi"
        """
        if method == "multi":
            return self.multi_point_crossover(parent_a, parent_b)
        return self.single_point_crossover(parent_a, parent_b)

    # ── 突變 (Mutation) ──────────────────────────────────────

    def apply_mutation(
        self,
        child: ConfigChromosome,
        base_mutation_rate: float = 0.01,
    ) -> ConfigChromosome:
        """
        配置驅動的突變引擎。

        對染色體中的每個 GeneSlot：
          連續基因：以 base_mutation_rate 機率觸發高斯擾動
          離散基因：以 base_mutation_rate × gene.mutation_rate_bonus 機率
                   從配置檔的 evolution_paths 中隨機選取突變目標
        """
        for slot in child.slots:
            if slot.is_continuous:
                self._mutate_continuous(slot, base_mutation_rate)
            else:
                self._mutate_discrete(slot, base_mutation_rate)

        return child

    def _mutate_continuous(self, slot: GeneSlot, rate: float) -> None:
        """突變連續基因：高斯擾動"""
        if random.random() >= rate:
            return

        gene_range = slot.max_val - slot.min_val
        delta = random.gauss(0, gene_range * 0.1)
        slot.value += delta

        if slot.is_int:
            slot.value = int(round(max(slot.min_val, min(slot.value, slot.max_val))))
        else:
            slot.value = max(slot.min_val, min(slot.value, slot.max_val))

    def _mutate_discrete(self, slot: GeneSlot, rate: float) -> None:
        """
        突變離散基因：從配置檔的演化路徑中選取新值。

        機率 = rate × gene.mutation_rate_bonus
        （器官演化在自然界罕見，但遊戲中需要較高頻率以在有限世代內觀察到）

        突變方向完全由 JSON 配置的 evolution_paths 決定。
        例：locomotion = "WALK" → 可突變到 ["CRAWL", "RUN", "FLY", "SWIM"]
        """
        if slot.gene_def is None:
            return

        effective_rate = rate * slot.gene_def.mutation_rate_bonus
        if random.random() >= effective_rate:
            return

        path = slot.gene_def.get_evolution_path(slot.enum_value)
        if not path:
            return  # 無可用突變路徑

        old_value = slot.enum_value
        new_value = random.choice(path)
        slot.enum_value = new_value

        # 記錄突變事件（可選：用於統計）
        self._log_mutation(
            slot.gene_name, old_value, new_value, slot.gene_def
        )

    @staticmethod
    def _log_mutation(
        gene_name: str,
        old_value: str,
        new_value: str,
        gene_def: EnumGeneDefinition,
    ) -> None:
        """記錄突變事件到控制台（可替換為遊戲 UI 事件）"""
        is_custom = " 🔧" if gene_def.is_custom else ""
        print(
            f"  🧬 突變: {gene_name}{is_custom} "
            f"{old_value} → {new_value}"
        )

    # ── 完整繁衍流程 ────────────────────────────────────────

    def reproduce(
        self,
        parent_a: ConfigChromosome,
        parent_b: Optional[ConfigChromosome] = None,
        base_mutation_rate: float = 0.01,
        is_sexual: bool = True,
    ) -> ConfigChromosome:
        """
        繁衍流程整合：交叉（有性）+ 突變。

        Args:
            parent_a: 第一個親本
            parent_b: 第二個親本（無性生殖時為 None）
            base_mutation_rate: 基礎突變率
            is_sexual: 是否為有性生殖

        Returns:
            子代染色體
        """
        if is_sexual and parent_b is not None:
            child = self.crossover(parent_a, parent_b)
        else:
            child = parent_a.clone()

        child = self.apply_mutation(child, base_mutation_rate)
        return child

    # ── 突變率計算 ──────────────────────────────────────────

    def get_effective_mutation_rate(self, gene_name: str) -> float:
        """取得某基因的有效突變率（base × bonus）"""
        return self.config.get_mutation_rate(gene_name)
