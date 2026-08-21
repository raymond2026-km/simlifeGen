"""
EcologyManager — 生態閉環管理器

負責：
  1. 資源（食物方塊）的生成、腐爛、清除
  2. 資源搜尋 API（供 Sim 找食物）
  3. 資源爭奪邏輯（多 Sim 搶同一資源）
  4. 濕度 → 生成速率 的耦合
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .environment import EnvironmentManager


# ════════════════════════════════════════════════════════════════
#  資源物件
# ════════════════════════════════════════════════════════════════

# 資源類型 → 基礎卡路里
RESOURCE_CALORIES = {
    "plant":   50,
    "fruit":   70,
    "fungus":  30,
    "meat":    100,
    "corpse":  80,
    "plankton": 20,
    "algae":   25,
}

# 資源類型 → 季節出現權重
RESOURCE_SEASON_WEIGHTS = {
    "spring": [("plant", 40), ("fruit", 30), ("fungus", 10)],
    "summer": [("fruit", 50), ("plant", 30), ("algae", 15)],
    "autumn": [("plant", 30), ("fungus", 40), ("fruit", 20)],
    "winter": [("fungus", 20), ("plant", 10)],
}


@dataclass
class Resource:
    """一個能量方塊（植物/果實/肉類等）"""
    resource_id: str = field(default_factory=lambda: f"res_{uuid.uuid4().hex[:8]}")
    resource_type: str = "plant"
    calories: float = 50.0
    x: float = 0.0
    y: float = 0.0
    terrain: str = "grassland"
    is_alive: bool = True
    spawn_tick: int = 0
    decay_timer: int = 0  # 生命 tick 數

    def consume(self) -> float:
        """消耗此資源，回傳卡路里"""
        self.is_alive = False
        return self.calories

    def __repr__(self) -> str:
        return (
            f"Resource({self.resource_type}, "
            f"cal={self.calories:.0f}, "
            f"pos=({self.x:.0f},{self.y:.0f}), "
            f"alive={self.is_alive})"
        )


# ════════════════════════════════════════════════════════════════
#  生態閉環管理器
# ════════════════════════════════════════════════════════════════

class EcologyManager:
    """
    生態閉環管理器

    ╔═══════════════════════════════════════════════════════════╗
    ║         資源生成公式                                     ║
    ║                                                         ║
    ║  spawn_count ~ Poisson(base_rate × humidity_factor      ║
    ║                        × season_factor × terrain_mult)  ║
    ║                                                         ║
    ║  humidity_factor = 0.2 (h<0.1) .. h×1.5 (0.1≤h≤0.9)    ║
    ║                     1.5 (h>0.9)                          ║
    ║  season_factor = spring:1.2, summer:0.8, ...            ║
    ║  terrain_mult = 取決於生成位置的地形                      ║
    ╚═══════════════════════════════════════════════════════════╝
    """

    BASE_SPAWN_RATE: float = 5.0
    MAX_RESOURCES: int = 500
    DECAY_RATE: float = 0.005  # 每 tick 資源腐爛機率
    MAX_LIFETIME_TICKS: int = 300  # 資源最長存活 tick

    def __init__(self, env_manager: EnvironmentManager):
        self.env = env_manager
        self.resources: list[Resource] = []
        self._resource_counter: int = 0
        self._total_spawned: int = 0
        self._total_consumed: int = 0
        self._total_decayed: int = 0

    # ── 資源生成 ──────────────────────────────────────────

    def spawn_resources(self) -> list[Resource]:
        """
        根據當前氣候生成資源。
        回傳本 tick 新生成的資源列表。
        """
        if len(self.resources) >= self.MAX_RESOURCES:
            return []

        # 計算有效生成率
        h_factor = self.env.compute_humidity_factor()
        s_factor = self.env.climate.get_season_factor()
        effective_rate = self.BASE_SPAWN_RATE * h_factor * s_factor

        # 泊松分佈決定數量
        num_spawn = min(
            random.poissonvariate(effective_rate) if hasattr(random, 'poissonvariate')
            else max(0, int(random.gauss(effective_rate, max(1, effective_rate ** 0.5)))),
            50,
        )

        if num_spawn <= 0:
            return []

        # 選擇資源類型（根據季節）
        season = self.env.climate.season
        type_pool = RESOURCE_SEASON_WEIGHTS.get(season, [("plant", 50)])
        type_names = [t[0] for t in type_pool]
        type_weights = [t[1] for t in type_pool]

        new_resources = []
        positions = self.env.get_resource_spawn_positions(num_spawn)

        for px, py, terrain in positions:
            if len(self.resources) + len(new_resources) >= self.MAX_RESOURCES:
                break

            res_type = random.choices(type_names, weights=type_weights, k=1)[0]
            base_cal = RESOURCE_CALORIES.get(res_type, 50)
            # 濕度越高，營養越豐富
            cal = base_cal * (0.8 + 0.4 * self.env.climate.humidity)
            # 地形乘數
            terrain_mult = self.env.get_cell_at(px, py).resource_mult
            cal *= terrain_mult

            self._resource_counter += 1
            res = Resource(
                resource_id=f"res_{self._resource_counter:06d}",
                resource_type=res_type,
                calories=cal,
                x=px,
                y=py,
                terrain=terrain,
                spawn_tick=self.env.climate.tick,
            )
            new_resources.append(res)

        self.resources.extend(new_resources)
        self._total_spawned += len(new_resources)
        return new_resources

    # ── 資源腐爛 ──────────────────────────────────────────

    def decay_resources(self) -> int:
        """
        資源自然衰減。
        每 tick 有一定機率腐爛，或超過最長存活時間自動清除。
        回傳被清除的數量。
        """
        current_tick = self.env.climate.tick
        remaining = []
        removed = 0

        for res in self.resources:
            age = current_tick - res.spawn_tick

            # 超過最長存活時間
            if age > self.MAX_LIFETIME_TICKS:
                removed += 1
                self._total_decayed += 1
                continue

            # 隨機腐爛
            if random.random() < self.DECAY_RATE:
                removed += 1
                self._total_decayed += 1
                continue

            remaining.append(res)

        self.resources = remaining
        return removed

    # ── 資源搜尋 ──────────────────────────────────────────

    def find_nearest_food(
        self,
        x: float,
        y: float,
        edible_prefixes: list[str],
        max_range: float = 200.0,
    ) -> Optional[Resource]:
        """
        找到最近的可食用資源。

        Args:
            x, y: 搜尋中心座標
            edible_prefixes: 可食用的資源 ID 前綴列表
            max_range: 最大搜尋範圍

        Returns:
            最近的 Resource 或 None
        """
        best = None
        best_dist = max_range

        for res in self.resources:
            if not res.is_alive:
                continue
            if not self._can_eat(res.resource_type, edible_prefixes):
                continue

            dist = ((res.x - x) ** 2 + (res.y - y) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = res

        return best

    def find_food_in_radius(
        self,
        x: float,
        y: float,
        radius: float,
        edible_prefixes: list[str],
    ) -> list[Resource]:
        """找到指定範圍內的所有可食用資源"""
        results = []
        r_sq = radius ** 2

        for res in self.resources:
            if not res.is_alive:
                continue
            if not self._can_eat(res.resource_type, edible_prefixes):
                continue
            dist_sq = (res.x - x) ** 2 + (res.y - y) ** 2
            if dist_sq <= r_sq:
                results.append(res)

        return results

    @staticmethod
    def _can_eat(resource_type: str, edible_prefixes: list[str]) -> bool:
        """檢查某資源類型是否可被食用"""
        return any(resource_type.startswith(p) for p in edible_prefixes)

    # ── 資源爭奪 ──────────────────────────────────────────

    def compete_for_resource(
        self,
        resource: Resource,
        claimant_ids: list[str],
    ) -> Optional[str]:
        """
        當多個 Sim 同時靠近同一資源時，決定誰獲得。
        使用隨機加權（能量越低越優先飢餓）。

        Args:
            resource: 爭奪的資源
            claimant_ids: 爭奪者 ID 列表

        Returns:
            獲勝的 Sim ID，或 None（資源被破壞）
        """
        if not claimant_ids:
            return None
        if len(claimant_ids) == 1:
            return claimant_ids[0]

        # 20% 機率資源在爭奪中被破壞
        if random.random() < 0.2:
            resource.is_alive = False
            return None

        # 隨機選取（簡化版；真實版應考慮距離和攻擊力）
        return random.choice(claimant_ids)

    # ── 統計 ──────────────────────────────────────────────

    def get_resource_counts(self) -> dict[str, int]:
        """統計各類型資源數量"""
        counts = {}
        for res in self.resources:
            if res.is_alive:
                counts[res.resource_type] = counts.get(res.resource_type, 0) + 1
        return counts

    @property
    def alive_count(self) -> int:
        return sum(1 for r in self.resources if r.is_alive)

    def get_stats(self) -> dict:
        """取得生態統計"""
        return {
            "alive": self.alive_count,
            "total_spawned": self._total_spawned,
            "total_consumed": self._total_consumed,
            "total_decayed": self._total_decayed,
            "by_type": self.get_resource_counts(),
        }
