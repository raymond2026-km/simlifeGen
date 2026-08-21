"""
SelectionEngine — 自然選擇引擎

負責：
  1. 適應度評估（無人工分數，純粹基於存活與繁殖）
  2. 親本選擇（輪盤賭 / 錦標賽）
  3. 基因鏈追蹤
  4. 絕跡判定（連續 N 代未繁殖）
"""

from __future__ import annotations

import random
import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .sim import Sim, DeathCause
from .genetic_engine import ConfigChromosome, GeneSlot


# ════════════════════════════════════════════════════════════════
#  適應度記錄
# ════════════════════════════════════════════════════════════════

@dataclass
class FitnessRecord:
    """個體適應度追蹤記錄"""
    sim_id: str
    chromosome_id: str
    generation: int
    ticks_survived: int
    energy_peak: float
    offspring_count: int
    age_at_death: Optional[int]
    energy_efficiency: float = 0.0


# ════════════════════════════════════════════════════════════════
#  基因鏈追蹤
# ════════════════════════════════════════════════════════════════

@dataclass
class GeneChainRecord:
    """基因鏈追蹤記錄"""
    chain_id: str
    genotypes_seen: int = 0
    generations_without_repro: int = 0
    first_seen_tick: int = 0
    last_reproduction_tick: int = -1
    is_extinct: bool = False
    total_offspring: int = 0

    @staticmethod
    def hash_chromosome(chr: ConfigChromosome) -> str:
        """
        為染色體生成基因型指紋。
        相同列舉基因組合 = 同一鏈（連續基因取區間哈希）。
        """
        parts = []
        for slot in chr.slots:
            if slot.is_continuous:
                # 連續基因：取四捨五入到小數第一位
                parts.append(f"{slot.gene_name}:{round(slot.value, 1)}")
            else:
                parts.append(f"{slot.gene_name}:{slot.enum_value}")

        fingerprint = "|".join(parts)
        return hashlib.md5(fingerprint.encode()).hexdigest()[:12]


# ════════════════════════════════════════════════════════════════
#  選擇引擎
# ════════════════════════════════════════════════════════════════

class SelectionEngine:
    """
    自然選擇引擎

    ╔══════════════════════════════════════════════════════════╗
    ║              適應度函數                                  ║
    ║                                                        ║
    ║  fitness = survival_score × efficiency_mult             ║
    ║            + reproduction_bonus                          ║
    ║                                                        ║
    ║  survival_score = min(ticks / expected, 1.0) × 40      ║
    ║  efficiency_mult = 1.0 + min(eff, 5.0) × 0.1          ║
    ║  reproduction_bonus = min(offspring × 10, 50)          ║
    ╚══════════════════════════════════════════════════════════╝
    """

    EXTINCTION_THRESHOLD: int = 3  # 連續 3 代未繁殖即判定絕跡

    def __init__(self):
        self.gene_chains: dict[str, GeneChainRecord] = {}
        self._extinct_chains: set[str] = set()
        self._current_tick: int = 0

    def set_tick(self, tick: int) -> None:
        """更新當前 tick"""
        self._current_tick = tick

    # ── 適應度計算 ────────────────────────────────────────

    @staticmethod
    def compute_fitness(record: FitnessRecord) -> float:
        """
        適應度函數（0.0 ~ 100.0）
        """
        expected_lifespan = 500
        survival_score = min(record.ticks_survived / expected_lifespan, 1.0) * 40.0
        efficiency_mult = 1.0 + min(record.energy_efficiency, 5.0) * 0.1
        reproduction_bonus = min(record.offspring_count * 10, 50)
        return survival_score * efficiency_mult + reproduction_bonus

    @staticmethod
    def sim_to_fitness_record(sim: Sim) -> FitnessRecord:
        """將個體轉為適應度記錄"""
        return FitnessRecord(
            sim_id=sim.sim_id,
            chromosome_id=sim.chromosome.chromosome_id,
            generation=sim.chromosome.generation,
            ticks_survived=sim.age_ticks,
            energy_peak=sim.energy_peak,
            offspring_count=sim.offspring_count,
            age_at_death=None if sim.is_alive else sim.age_ticks,
            energy_efficiency=sim.energy_efficiency,
        )

    # ── 親本選擇 ──────────────────────────────────────────

    @staticmethod
    def roulette_select(
        population: list[Sim],
        num_parents: int = 2,
    ) -> list[Sim]:
        """輪盤賭選擇法"""
        if len(population) < num_parents:
            return random.sample(population, len(population))

        records = [SelectionEngine.sim_to_fitness_record(s) for s in population]
        fitnesses = [max(SelectionEngine.compute_fitness(r), 0.01) for r in records]
        total = sum(fitnesses)
        probs = [f / total for f in fitnesses]

        selected = []
        for _ in range(num_parents):
            r = random.random()
            cumulative = 0.0
            for i, prob in enumerate(probs):
                cumulative += prob
                if r <= cumulative:
                    selected.append(population[i])
                    break
            else:
                selected.append(population[-1])

        return selected

    @staticmethod
    def tournament_select(
        population: list[Sim],
        tournament_size: int = 5,
    ) -> Sim:
        """錦標賽選擇法"""
        contestants = random.sample(population, min(tournament_size, len(population)))
        return max(contestants, key=lambda s: SelectionEngine.compute_fitness(
            SelectionEngine.sim_to_fitness_record(s)
        ))

    # ── 基因鏈追蹤 ────────────────────────────────────────

    def track_birth(self, child: Sim) -> str:
        """
        追蹤新生代的基因鏈。
        回傳 chain_id。
        """
        chain_id = GeneChainRecord.hash_chromosome(child.chromosome)

        if chain_id not in self.gene_chains:
            self.gene_chains[chain_id] = GeneChainRecord(
                chain_id=chain_id,
                first_seen_tick=self._current_tick,
            )

        chain = self.gene_chains[chain_id]
        chain.genotypes_seen += 1
        chain.total_offspring += 1
        return chain_id

    def track_reproduction(self, chain_id: str) -> None:
        """標記某基因鏈在本 tick 有繁殖"""
        if chain_id in self.gene_chains:
            chain = self.gene_chains[chain_id]
            chain.last_reproduction_tick = self._current_tick
            chain.generations_without_repro = 0

    def advance_generation(self) -> None:
        """每代結束時呼叫：累加未繁殖計數"""
        for chain in self.gene_chains.values():
            if not chain.is_extinct:
                chain.generations_without_repro += 1

    # ── 絕跡檢查 ──────────────────────────────────────────

    def extinction_check(self) -> list[str]:
        """
        絕跡檢查 — 回傳所有被判定為絕跡的 chain_id。
        """
        extinct = []
        for chain_id, chain in self.gene_chains.items():
            if (
                chain.generations_without_repro >= self.EXTINCTION_THRESHOLD
                and chain_id not in self._extinct_chains
            ):
                extinct.append(chain_id)
                chain.is_extinct = True
                self._extinct_chains.add(chain_id)
        return extinct

    # ── 從死亡個體建立記錄 ────────────────────────────────

    def record_death(self, sim: Sim) -> FitnessRecord:
        """記錄死亡個體的適應度"""
        record = self.sim_to_fitness_record(sim)
        record.age_at_death = sim.age_ticks
        return record

    # ── 統計 ──────────────────────────────────────────────

    def get_stats(self) -> dict:
        """取得選擇引擎統計"""
        active = sum(1 for c in self.gene_chains.values() if not c.is_extinct)
        return {
            "total_chains": len(self.gene_chains),
            "active_chains": active,
            "extinct_chains": len(self._extinct_chains),
            "extinct_ids": list(self._extinct_chains),
        }
