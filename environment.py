"""
EnvironmentManager — 環境管理器

負責：
  1. 氣候狀態（溫度、濕度、季節）
  2. 2D 地圖與地形分佈
  3. 晝夜循環
  4. 提供 Sim 當前位置的地形資訊
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional


# ════════════════════════════════════════════════════════════════
#  氣候狀態
# ════════════════════════════════════════════════════════════════

@dataclass
class ClimateState:
    """
    氣候狀態 — 以正弦波模擬四季溫度變化與日夜循環。

    溫度模型：
      temp(t) = base_temp + amplitude × sin(2π × t / period - π/2)

    濕度模型：
      humidity(t) = base_humidity + humidity_amplitude × sin(2π × t / period)

    晝夜模型：
      light_level: 0.0（漆黑）→ 1.0（正午）平滑過渡
      dawn/dusk 各佔 10% 的日循環，有漸變
    """
    temperature: float = 25.0       # °C
    humidity: float = 0.5           # 0.0 ~ 1.0
    season: str = "spring"
    time_of_day: float = 0.0       # 0.0 ~ 1.0（0.0=午夜, 0.5=正午）
    is_night: bool = False
    light_level: float = 0.0       # 0.0（漆黑）~ 1.0（正午）
    is_dawn: bool = False          # 黎明過渡期
    is_dusk: bool = False          # 黃昏過渡期

    # 氣候參數
    base_temp: float = 25.0
    temp_amplitude: float = 15.0
    base_humidity: float = 0.5
    humidity_amplitude: float = 0.3
    ticks_per_season: int = 200
    ticks_per_day: int = 100       # 一個日夜循環的 tick 數

    tick: int = 0

    def advance(self) -> None:
        """推進一個 tick"""
        self.tick += 1

        # 季節 & 溫度
        year_progress = (self.tick % (self.ticks_per_season * 4)) / (self.ticks_per_season * 4)
        self.temperature = self.base_temp + self.temp_amplitude * math.sin(
            2 * math.pi * year_progress - math.pi / 2
        )
        # 濕度
        self.humidity = self.base_humidity + self.humidity_amplitude * math.sin(
            2 * math.pi * year_progress
        )
        self.humidity = max(0.0, min(1.0, self.humidity))

        # 季節判定
        phase = (self.tick // self.ticks_per_season) % 4
        self.season = ["spring", "summer", "autumn", "winter"][phase]

        # ── 晝夜循環（平滑過渡） ──
        day_progress = (self.tick % self.ticks_per_day) / self.ticks_per_day
        self.time_of_day = day_progress

        # 溫度日變化：正午最熱，凌晨最冷
        daily_temp_offset = 3.0 * math.sin(2 * math.pi * day_progress - math.pi / 2)
        self.temperature += daily_temp_offset

        # 光照等級：正弦波平滑過渡
        # 0.0=午夜, 0.25=日出, 0.5=正午, 0.75=日落
        # light_level = sin(π × day_progress) → 0 at midnight, 1 at noon
        self.light_level = max(0.0, math.sin(math.pi * day_progress))

        # 時段判定（含黎明/黃昏過渡）
        # 黎明: 0.20 ~ 0.30 (light 0.0→~0.59)
        # 白天: 0.30 ~ 0.70
        # 黃昏: 0.70 ~ 0.80 (light ~0.59→0.0)
        # 夜晚: 0.80 ~ 1.00 + 0.00 ~ 0.20
        self.is_dawn = 0.20 <= day_progress < 0.30
        self.is_dusk = 0.70 <= day_progress < 0.80
        self.is_night = day_progress < 0.20 or day_progress >= 0.80

    def get_season_factor(self) -> float:
        """取得季節對資源生成的乘數"""
        factors = {
            "spring": 1.2,
            "summer": 0.8,
            "autumn": 1.0,
            "winter": 0.4,
        }
        return factors.get(self.season, 1.0)

    def get_light_level(self) -> float:
        """取得當前光照等級 (0.0 ~ 1.0)"""
        return self.light_level

    @property
    def time_of_day_label(self) -> str:
        """取得當前時段標籤"""
        if self.is_night:
            return "night"
        elif self.is_dawn:
            return "dawn"
        elif self.is_dusk:
            return "dusk"
        return "day"

    @property
    def time_icon(self) -> str:
        """取得時段圖示"""
        if self.is_night:
            return "🌙"
        elif self.is_dawn:
            return "🌅"
        elif self.is_dusk:
            return "🌇"
        return "☀️"


# ════════════════════════════════════════════════════════════════
#  地圖格子
# ════════════════════════════════════════════════════════════════

# 地形類型及其基本屬性
TERRAIN_PROPS = {
    "grassland": {"label": "草原", "resource_mult": 1.0, "move_cost": 1.0, "color": "#4CAF50"},
    "desert":    {"label": "沙漠", "resource_mult": 0.3, "move_cost": 1.3, "color": "#F9A825"},
    "forest":    {"label": "森林", "resource_mult": 1.5, "move_cost": 1.2, "color": "#2E7D32"},
    "snow":      {"label": "雪地", "resource_mult": 0.4, "move_cost": 1.5, "color": "#B3E5FC"},
    "ocean":     {"label": "海洋", "resource_mult": 0.8, "move_cost": 1.0, "color": "#1565C0"},
    "river":     {"label": "河流", "resource_mult": 0.6, "move_cost": 1.0, "color": "#42A5F5"},
    "swamp":     {"label": "沼澤", "resource_mult": 1.2, "move_cost": 1.4, "color": "#6D4C41"},
}

# 地形連通圖：哪些地形相鄰時可以通行
TERRAIN_CONNECTIVITY = {
    "grassland": {"grassland", "forest", "desert", "snow", "river"},
    "desert":    {"desert", "grassland", "swamp"},
    "forest":    {"forest", "grassland", "river", "swamp"},
    "snow":      {"snow", "grassland", "river"},
    "ocean":     {"ocean", "river", "swamp"},
    "river":     {"river", "ocean", "grassland", "forest", "snow"},
    "swamp":     {"swamp", "forest", "desert", "ocean"},
}


@dataclass
class MapCell:
    """地圖上的一個格子"""
    terrain: str
    x: int = 0
    y: int = 0
    elevation: float = 0.0  # 海拔（可用於影響溫度）

    @property
    def resource_mult(self) -> float:
        return TERRAIN_PROPS.get(self.terrain, {}).get("resource_mult", 1.0)

    @property
    def move_cost(self) -> float:
        return TERRAIN_PROPS.get(self.terrain, {}).get("move_cost", 1.0)


# ════════════════════════════════════════════════════════════════
#  環境管理器
# ════════════════════════════════════════════════════════════════

class EnvironmentManager:
    """
    環境管理器

    管理氣候、2D 地圖、地形生成。
    """

    def __init__(
        self,
        map_width: int = 50,
        map_height: int = 50,
        ticks_per_season: int = 200,
        ticks_per_day: int = 100,
        seed: Optional[int] = None,
    ):
        if seed is not None:
            random.seed(seed)

        self.map_width = map_width
        self.map_height = map_height

        self.climate = ClimateState(
            ticks_per_season=ticks_per_season,
            ticks_per_day=ticks_per_day,
        )

        # 2D 地圖
        self.grid: list[list[MapCell]] = []
        self._generate_terrain()

    def _generate_terrain(self) -> None:
        """
        程式化地形生成 — 使用簡化的 Perlin-like 噪聲。
        產生中心為陸地、邊緣為海洋的地圖。
        """
        self.grid = []
        cx, cy = self.map_width / 2, self.map_height / 2
        max_dist = math.sqrt(cx ** 2 + cy ** 2)

        for y in range(self.map_height):
            row = []
            for x in range(self.map_width):
                # 到中心的距離比例
                dx = x - cx
                dy = y - cy
                dist = math.sqrt(dx * dx + dy * dy) / max_dist

                # 簡易地形判定
                noise = random.random() * 0.3  # 加入隨機擾動

                if dist + noise > 0.85:
                    terrain = "ocean"
                elif dist + noise > 0.75:
                    terrain = random.choice(["river", "swamp", "ocean"])
                elif dist + noise > 0.6:
                    terrain = random.choice(["desert", "snow", "grassland"])
                elif dist + noise > 0.3:
                    terrain = random.choice(["grassland", "forest", "grassland"])
                else:
                    terrain = random.choice(["forest", "grassland", "forest"])

                row.append(MapCell(terrain=terrain, x=x, y=y))
            self.grid.append(row)

    def get_cell(self, x: int, y: int) -> MapCell:
        """取得地圖格子（含邊界保護）"""
        x = max(0, min(x, self.map_width - 1))
        y = max(0, min(y, self.map_height - 1))
        return self.grid[y][x]

    def get_terrain_at(self, world_x: float, world_y: float) -> str:
        """世界座標 → 地形類型"""
        grid_x = int(world_x) % self.map_width
        grid_y = int(world_y) % self.map_height
        return self.grid[grid_y][grid_x].terrain

    def get_cell_at(self, world_x: float, world_y: float) -> MapCell:
        """世界座標 → MapCell"""
        grid_x = int(world_x) % self.map_width
        grid_y = int(world_y) % self.map_height
        return self.grid[grid_y][grid_x]

    def is_passable(
        self,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        locomotion_passable: list[str],
    ) -> bool:
        """
        判斷移動是否可行。
        locomotion_passable: 該 Sim 的移動方式可通過的地形列表。
        """
        to_cell = self.get_cell(to_x, to_y)
        if "all" in locomotion_passable:
            return True
        return to_cell.terrain in locomotion_passable

    def get_resource_spawn_positions(
        self,
        count: int,
        resource_type: str = "plant",
    ) -> list[tuple[float, float, str]]:
        """
        隨機產生資源生成位置。
        根據地形的 resource_mult 加權選擇。

        Returns:
            list of (x, y, terrain)
        """
        positions = []
        attempts = 0
        while len(positions) < count and attempts < count * 5:
            attempts += 1
            x = random.randint(0, self.map_width - 1)
            y = random.randint(0, self.map_height - 1)
            cell = self.grid[y][x]

            # 濕度 + 地形資源乘數 決定是否生成
            spawn_chance = cell.resource_mult * self.climate.humidity
            if resource_type in ("fruit", "fungus"):
                spawn_chance *= self.climate.get_season_factor()

            if random.random() < spawn_chance:
                positions.append((float(x), float(y), cell.terrain))

        return positions

    def compute_humidity_factor(self) -> float:
        """濕度對資源生成的因子"""
        h = self.climate.humidity
        if h < 0.1:
            return 0.2
        elif h > 0.9:
            return 1.5
        else:
            return h * 1.5

    def advance(self) -> None:
        """推進環境一個 tick"""
        self.climate.advance()

    def get_map_summary(self) -> dict[str, int]:
        """統計地圖上各地形數量"""
        counts = {}
        for row in self.grid:
            for cell in row:
                counts[cell.terrain] = counts.get(cell.terrain, 0) + 1
        return counts
