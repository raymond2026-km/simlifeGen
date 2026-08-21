"""
Sim — 模擬人個體實體

每個 Sim 擁有一條 ConfigChromosome（基因組）、能量、HP 與行為狀態機。
Sim 不包含代邏輯（代謝在 MetabolismEngine 中），也不包含環境互動
（環境互動在 SimulationEngine 中）。
"""

from __future__ import annotations

import uuid
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .genetic_engine import ConfigChromosome, GeneSlot


# ════════════════════════════════════════════════════════════════
#  狀態列舉
# ════════════════════════════════════════════════════════════════

class SimState(Enum):
    IDLE      = "idle"
    FORAGING  = "foraging"
    FLEEING   = "fleeing"
    FIGHTING  = "fighting"
    MATING    = "mating"
    DEAD      = "dead"


class DeathCause(Enum):
    STARVATION = "starvation"
    DAMAGE     = "damage"
    OLD_AGE    = "old_age"
    HYPOTHERMIA = "hypothermia"
    HEATSTROKE  = "heatstroke"
    DROWNING    = "drowning"


# ════════════════════════════════════════════════════════════════
#  Sim 個體
# ════════════════════════════════════════════════════════════════

@dataclass
class Sim:
    """
    模擬人個體

    職責：
      - 持有基因組 (ConfigChromosome)
      - 管理能量、HP、狀態
      - 追蹤個體統計（存活 tick 數、子代數、能量效率等）
      - 處理個體 tick（代謝消耗 + 死亡判定由外部引擎觸發）

    不做：
      - 不自行計算代謝（交給 MetabolismEngine）
      - 不自行搜尋食物（交給 SimulationEngine）
      - 不自行繁殖（交給 SelectionEngine）
    """
    sim_id: str = field(default_factory=lambda: f"sim_{uuid.uuid4().hex[:8]}")
    chromosome: ConfigChromosome = field(default_factory=lambda: ConfigChromosome(slots=[]))

    # ── 運行時狀態 ──
    energy: float = 100.0
    hp: float = 100.0
    age_ticks: int = 0
    state: SimState = SimState.IDLE
    is_alive: bool = True
    death_cause: Optional[DeathCause] = None

    # ── 空間座標 ──
    x: float = 0.0
    y: float = 0.0

    # ── 統計追蹤 ──
    offspring_count: int = 0
    energy_peak: float = 100.0
    total_energy_intake: float = 0.0
    total_energy_drain: float = 0.0
    ticks_in_water: int = 0
    resource_eaten: int = 0

    # ── 冷卻計時器 ──
    repro_cooldown: int = 0

    # ── 地形追蹤 ──
    current_terrain: str = "grassland"

    def __post_init__(self):
        if not self.chromosome.slots:
            return  # 允許空染色體（測試用）
        self.hp = self.get_stat("base_hp")
        self.energy = self.hp * 0.5

    # ── 基因存取捷徑 ──

    def get_stat(self, name: str) -> float:
        """取得連續基因的值"""
        return self.chromosome.get_continuous_value(name)

    def get_gene(self, name: str) -> str:
        """取得離散基因的值"""
        return self.chromosome.get_enum_value(name)

    def get_gene_attrs(self, name: str) -> dict:
        """取得離散基因的所有屬性"""
        slot = self.chromosome.get_slot(name)
        if slot.gene_def is None:
            return {}
        gv = slot.gene_def.get_value(slot.enum_value)
        return gv.attributes

    # ── 狀態管理 ──

    def set_state(self, new_state: SimState) -> None:
        """設定行為狀態"""
        if self.state == SimState.DEAD:
            return
        self.state = new_state

    def kill(self, cause: DeathCause) -> None:
        """標記死亡"""
        self.is_alive = False
        self.state = SimState.DEAD
        self.death_cause = cause

    # ── 能量操作 ──

    def gain_energy(self, amount: float) -> None:
        """攝取能量"""
        self.energy += amount
        self.total_energy_intake += amount
        self.energy_peak = max(self.energy_peak, self.energy)
        self.resource_eaten += 1

    def drain_energy(self, amount: float) -> None:
        """扣除能量"""
        self.energy -= amount
        self.total_energy_drain += amount

    def take_damage(self, amount: float) -> None:
        """扣除 HP"""
        self.hp -= amount

    # ── 代謝消耗（由 MetabolismEngine 回填） ──

    def apply_drain(self, drain: float, damage: float = 0.0) -> None:
        """
        應用代謝消耗（由外部引擎計算後調用）。

        Args:
            drain: 能量扣除量
            damage: HP 扣除量（體溫結構性損傷）
        """
        self.drain_energy(drain)
        if damage > 0:
            self.take_damage(damage)

    # ── 死亡判定 ──

    def check_death(self) -> bool:
        """
        檢查是否死亡。回傳 True 表示仍存活。
        """
        if not self.is_alive:
            return False

        # 壽命極限
        lifespan = self.get_stat("lifespan")
        if self.age_ticks >= lifespan:
            self.kill(DeathCause.OLD_AGE)
            return False

        # 能量耗盡
        if self.energy <= 0:
            self.kill(DeathCause.STARVATION)
            return False

        # HP 耗盡
        if self.hp <= 0:
            self.kill(DeathCause.DAMAGE)
            return False

        return True

    # ── Tick 推進 ──

    def advance_tick(self) -> None:
        """每個 tick 推進年齡與冷卻"""
        self.age_ticks += 1
        if self.repro_cooldown > 0:
            self.repro_cooldown -= 1

    # ── 繁殖就緒檢查 ──

    @property
    def can_reproduce(self) -> bool:
        """是否具備繁殖資格"""
        return (
            self.is_alive
            and self.repro_cooldown <= 0
            and self.energy >= 80.0  # 能量門檻
        )

    # ── 適應度 ──

    @property
    def energy_efficiency(self) -> float:
        """能量效率比"""
        if self.total_energy_drain == 0:
            return 0.0
        return self.total_energy_intake / self.total_energy_drain

    # ── 空間 ──

    def distance_to(self, other: Sim) -> float:
        """計算與另一個 Sim 的歐氏距離"""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def distance_to_point(self, px: float, py: float) -> float:
        """計算與座標點的距離"""
        return math.sqrt((self.x - px) ** 2 + (self.y - py) ** 2)

    def move_towards(self, tx: float, ty: float, speed: float) -> None:
        """向目標移動（含速度限制）"""
        dx = tx - self.x
        dy = ty - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.1:
            return
        move_dist = min(speed, dist)
        self.x += dx / dist * move_dist
        self.y += dy / dist * move_dist

    # ── 序列化 ──

    def to_dict(self) -> dict:
        """序列化為字典（用於日誌/JSON 輸出）"""
        return {
            "sim_id": self.sim_id,
            "generation": self.chromosome.generation,
            "age": self.age_ticks,
            "energy": round(self.energy, 2),
            "hp": round(self.hp, 2),
            "state": self.state.value,
            "alive": self.is_alive,
            "death_cause": self.death_cause.value if self.death_cause else None,
            "offspring": self.offspring_count,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "terrain": self.current_terrain,
            "genes": {
                slot.gene_name: slot.enum_value if not slot.is_continuous else round(slot.value, 3)
                for slot in self.chromosome.slots
            },
        }

    def __repr__(self) -> str:
        g = self.chromosome.generation
        e = round(self.energy, 1)
        hp = round(self.hp, 1)
        return (
            f"Sim({self.sim_id}, gen={g}, "
            f"hp={hp}, energy={e}, "
            f"state={self.state.value}, "
            f"age={self.age_ticks})"
        )
