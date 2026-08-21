"""
GeneConfigManager — 基因配置管理器

功能：
  1. 從 JSON 配置檔動態載入列舉基因定義
  2. 提供演化路徑查詢 API
  3. 支援熱重載 (hot-reload)，設計師修改 JSON 後無需重啟模擬
  4. 動態產生 Enum-like 物件，供 GeneticEngine 使用
  5. 支援自定義基因（夜行性、海洋適應等）

用法：
    manager = GeneConfigManager("configs/gene_config.json")

    # 查詢演化路徑
    targets = manager.get_evolution_path("locomotion", "WALK")
    # → ["CRAWL", "RUN", "FLY", "SWIM"]

    # 隨機選取突變目標
    target = manager.get_random_mutation_target("locomotion", "CRAWL")
    # → "WALK" (隨機)

    # 取得基因屬性
    attrs = manager.get_gene_attributes("nocturnality", "NOCTURNAL")
    # → {"label": "night_active", "night_vision": 0.8, ...}

    # 取得所有已啟用的基因名稱
    names = manager.get_all_gene_names()
    # → ["locomotion", "digestive", "mating", "territory",
    #    "nocturnality", "ocean_adaptation", "thermal_insulation"]
"""

from __future__ import annotations

import json
import os
import time
import random
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ════════════════════════════════════════════════════════════════
#  核心資料結構
# ════════════════════════════════════════════════════════════════

@dataclass
class GeneValue:
    """一個列舉基因的單一值（如 CRAWL、FLY）"""
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, key: str) -> Any:
        """讓 GeneValue 可以用點號存取屬性：gene.speed_mult"""
        if key in ("name", "attributes"):
            return object.__getattribute__(self, key)
        if key in self.attributes:
            return self.attributes[key]
        raise AttributeError(f"GeneValue '{self.name}' has no attribute '{key}'")

    def __repr__(self) -> str:
        return f"GeneValue({self.name})"


@dataclass
class EnumGeneDefinition:
    """
    一個列舉基因的完整定義。
    對應 JSON 中 enum_genes 或 custom_genes 的一個 key。
    """
    gene_name: str
    description: str
    default_value: str
    mutation_rate_bonus: float
    values: dict[str, GeneValue]
    evolution_paths: dict[str, list[str]]
    attributes_schema: dict[str, str]
    is_custom: bool = False
    simulation_hooks: dict[str, bool] = field(default_factory=dict)

    def get_value(self, name: str) -> GeneValue:
        """取得特定枚舉值"""
        if name not in self.values:
            raise ValueError(
                f"基因 '{self.gene_name}' 沒有值 '{name}'。"
                f"可用值: {list(self.values.keys())}"
            )
        return self.values[name]

    def get_evolution_path(self, current: str) -> list[str]:
        """
        查詢某個當前值的演化路徑（可突變到的候選值）。
        如果找不到路徑，回傳空列表。
        """
        return list(self.evolution_paths.get(current, []))

    def is_valid_value(self, name: str) -> bool:
        return name in self.values

    def all_value_names(self) -> list[str]:
        return list(self.values.keys())


# ════════════════════════════════════════════════════════════════
#  設定管理器
# ════════════════════════════════════════════════════════════════

class GeneConfigManager:
    """
    基因配置管理器 — 核心類別。

    從 JSON 配置檔載入所有基因定義，提供統一 API 供
    GeneticEngine 與 Sim 使用。

    支援：
      - 熱重載：呼叫 reload() 即可從磁碟重新讀取
      - 動態新增：呼叫 register_gene() 新增基因
      - 完整驗證：載入時檢查所有路徑引用的值是否存在
    """

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self._genes: dict[str, EnumGeneDefinition] = {}
        self._mutation_defaults: dict[str, float] = {}
        self._terrain_types: dict[str, dict] = {}
        self._meta: dict[str, Any] = {}
        self._last_modified: float = 0.0

        self.load()

    # ── 載入與驗證 ──────────────────────────────────────────

    def load(self) -> None:
        """從磁碟載入 JSON 配置並驗證"""
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self._meta = raw.get("_meta", {})
        self._mutation_defaults = raw.get("mutation_defaults", {})
        self._terrain_types = raw.get("terrain_types", {})

        # 載入內建基因
        for gene_name, gene_def in raw.get("enum_genes", {}).items():
            self._genes[gene_name] = self._parse_gene(
                gene_name, gene_def, is_custom=False
            )

        # 載入自定義基因（僅載入 enabled=true 的）
        for gene_name, gene_def in raw.get("custom_genes", {}).items():
            if gene_def.get("enabled", False):
                self._genes[gene_name] = self._parse_gene(
                    gene_name, gene_def, is_custom=True
                )

        # 驗證所有演化路徑
        self._validate_evolution_paths()

        self._last_modified = os.path.getmtime(self.config_path)

    def _parse_gene(
        self,
        gene_name: str,
        raw_def: dict,
        is_custom: bool,
    ) -> EnumGeneDefinition:
        """將 JSON 物件解析為 EnumGeneDefinition"""
        values = {}
        for val_name, val_attrs in raw_def.get("values", {}).items():
            values[val_name] = GeneValue(name=val_name, attributes=val_attrs)

        return EnumGeneDefinition(
            gene_name=gene_name,
            description=raw_def.get("description", ""),
            default_value=raw_def.get("default_value", list(values.keys())[0] if values else ""),
            mutation_rate_bonus=raw_def.get("mutation_rate_bonus", 3.0),
            values=values,
            evolution_paths=raw_def.get("evolution_paths", {}),
            attributes_schema=raw_def.get("attributes_schema", {}),
            is_custom=is_custom,
            simulation_hooks=raw_def.get("simulation_hooks", {}),
        )

    def _validate_evolution_paths(self) -> None:
        """
        驗證所有演化路徑中引用的值是否存在。
        無法通過驗證的路徑會被移除並發出警告。
        """
        for gene_name, gene in self._genes.items():
            invalid_refs = []
            for source, targets in gene.evolution_paths.items():
                # 檢查來源是否存在
                if not gene.is_valid_value(source):
                    invalid_refs.append(f"來源 '{source}' 不存在於基因 '{gene_name}'")
                    continue
                # 檢查目標是否存在
                valid_targets = [t for t in targets if gene.is_valid_value(t)]
                invalid_targets = [t for t in targets if not gene.is_valid_value(t)]
                if invalid_targets:
                    invalid_refs.append(
                        f"路徑 {source}→{invalid_targets} 引用了不存在的值"
                    )
                    gene.evolution_paths[source] = valid_targets

            if invalid_refs:
                print(f"⚠️  基因 '{gene_name}' 配置警告:")
                for ref in invalid_refs:
                    print(f"    - {ref}")

    # ── 查詢 API ────────────────────────────────────────────

    def get_gene(self, gene_name: str) -> EnumGeneDefinition:
        """取得完整的基因定義"""
        if gene_name not in self._genes:
            raise KeyError(
                f"找不到基因 '{gene_name}'。"
                f"可用基因: {list(self._genes.keys())}"
            )
        return self._genes[gene_name]

    def get_all_gene_names(self) -> list[str]:
        """取得所有已啟用的基因名稱（內建 + 自定義）"""
        return list(self._genes.keys())

    def get_builtin_genes(self) -> list[str]:
        """取得內建基因名稱"""
        return [n for n, g in self._genes.items() if not g.is_custom]

    def get_custom_genes(self) -> list[str]:
        """取得自定義基因名稱"""
        return [n for n, g in self._genes.items() if g.is_custom]

    def get_evolution_path(self, gene_name: str, current_value: str) -> list[str]:
        """
        查詢某基因當前值的演化路徑。

        Args:
            gene_name: 基因名稱 (e.g. "locomotion")
            current_value: 當前枚舉值名稱 (e.g. "WALK")

        Returns:
            可突變到的候選值列表 (e.g. ["CRAWL", "RUN", "FLY", "SWIM"])

        Raises:
            KeyError: 基因不存在
            ValueError: 當前值不存在於該基因
        """
        gene = self.get_gene(gene_name)
        if not gene.is_valid_value(current_value):
            raise ValueError(
                f"基因 '{gene_name}' 沒有值 '{current_value}'。"
                f"可用值: {gene.all_value_names()}"
            )
        return gene.get_evolution_path(current_value)

    def get_random_mutation_target(
        self,
        gene_name: str,
        current_value: str,
    ) -> Optional[str]:
        """
        隨機選取一個突變目標。
        如果沒有可用的演化路徑，回傳 None（表示該基因不可突變）。
        """
        path = self.get_evolution_path(gene_name, current_value)
        if not path:
            return None
        return random.choice(path)

    def get_gene_attributes(self, gene_name: str, value_name: str) -> dict[str, Any]:
        """取得某基因某值的所有屬性"""
        gene = self.get_gene(gene_name)
        gv = gene.get_value(value_name)
        return copy.deepcopy(gv.attributes)

    def get_mutation_rate(self, gene_name: str) -> float:
        """
        取得某基因的突變率倍數。
        = base_mutation_rate × mutation_rate_bonus
        """
        base = self._mutation_defaults.get("base_mutation_rate", 0.01)
        gene = self.get_gene(gene_name)
        return base * gene.mutation_rate_bonus

    def get_simulation_hook(self, gene_name: str, hook_name: str) -> bool:
        """檢查某基因是否啟用了特定模擬鉤子"""
        gene = self.get_gene(gene_name)
        return gene.simulation_hooks.get(hook_name, False)

    def get_terrain_types(self) -> dict[str, dict]:
        """取得所有地形類型定義"""
        return copy.deepcopy(self._terrain_types)

    # ── 動態修改 API ────────────────────────────────────────

    def register_gene(
        self,
        gene_name: str,
        description: str,
        values: dict[str, dict[str, Any]],
        evolution_paths: dict[str, list[str]],
        default_value: Optional[str] = None,
        mutation_rate_bonus: float = 3.0,
        attributes_schema: Optional[dict[str, str]] = None,
        simulation_hooks: Optional[dict[str, bool]] = None,
    ) -> EnumGeneDefinition:
        """
        動態新增一個基因（用於運行時擴展）。

        Example:
            manager.register_gene(
                gene_name="social_display",
                description="社交展示基因 — 影響同族辨識與群聚吸引力",
                values={
                    "CAMOUFLAGE":  {"label": "camouflage", "visibility": 0.2},
                    "BRIGHT":      {"label": "bright",     "visibility": 0.9},
                    "PATTERN":     {"label": "pattern",    "visibility": 0.5},
                },
                evolution_paths={
                    "CAMOUFLAGE": ["PATTERN", "BRIGHT"],
                    "BRIGHT":     ["PATTERN", "CAMOUFLAGE"],
                    "PATTERN":    ["CAMOUFLAGE", "BRIGHT"],
                },
            )
        """
        parsed_values = {}
        for val_name, val_attrs in values.items():
            parsed_values[val_name] = GeneValue(name=val_name, attributes=val_attrs)

        if default_value is None:
            default_value = list(parsed_values.keys())[0] if parsed_values else ""

        gene_def = EnumGeneDefinition(
            gene_name=gene_name,
            description=description,
            default_value=default_value,
            mutation_rate_bonus=mutation_rate_bonus,
            values=parsed_values,
            evolution_paths=evolution_paths,
            attributes_schema=attributes_schema or {},
            is_custom=True,
            simulation_hooks=simulation_hooks or {},
        )

        self._genes[gene_name] = gene_def
        self._validate_evolution_paths()
        return gene_def

    def remove_gene(self, gene_name: str) -> bool:
        """移除一個自定義基因。內建基因不可移除。"""
        if gene_name not in self._genes:
            return False
        gene = self._genes[gene_name]
        if not gene.is_custom:
            print(f"⚠️  內建基因 '{gene_name}' 不可移除")
            return False
        del self._genes[gene_name]
        return True

    def set_gene_enabled(self, gene_name: str, enabled: bool) -> None:
        """啟用或停用一個自定義基因"""
        if gene_name in self._genes:
            if not enabled:
                del self._genes[gene_name]
        else:
            raise KeyError(f"基因 '{gene_name}' 不存在")

    # ── 熱重載 ──────────────────────────────────────────────

    def reload(self) -> bool:
        """
        熱重載：從磁碟重新讀取 JSON。
        如果檔案未修改則跳過。
        回傳是否實際重新載入了。
        """
        try:
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime <= self._last_modified:
                return False  # 檔案未變更
            self.load()
            print(f"✅ 基因配置已重新載入 ({self.config_path})")
            return True
        except Exception as e:
            print(f"❌ 配置重載失敗: {e}")
            return False

    # ── 匯出 ────────────────────────────────────────────────

    def export_config(self, output_path: str | Path) -> None:
        """將當前配置（含動態新增的基因）匯出為 JSON"""
        output = {
            "_meta": self._meta,
            "mutation_defaults": self._mutation_defaults,
            "enum_genes": {},
            "custom_genes": {},
            "terrain_types": self._terrain_types,
        }

        for gene_name, gene in self._genes.items():
            entry = {
                "description": gene.description,
                "default_value": gene.default_value,
                "mutation_rate_bonus": gene.mutation_rate_bonus,
                "attributes_schema": gene.attributes_schema,
                "values": {v.name: v.attributes for v in gene.values.values()},
                "evolution_paths": gene.evolution_paths,
            }
            if gene.simulation_hooks:
                entry["simulation_hooks"] = gene.simulation_hooks

            if gene.is_custom:
                entry["enabled"] = True
                output["custom_genes"][gene_name] = entry
            else:
                output["enum_genes"][gene_name] = entry

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✅ 配置已匯出至 {output_path}")

    # ── 統計 ────────────────────────────────────────────────

    def summary(self) -> str:
        """產生配置摘要文字"""
        lines = [
            f"📋 基因配置摘要 (v{self._meta.get('version', '?')})",
            f"   {self._meta.get('description', '')}",
            "=" * 50,
        ]
        for name, gene in self._genes.items():
            tag = "🔧 自定義" if gene.is_custom else "🧬 內建"
            vals = gene.all_value_names()
            path_count = sum(len(v) for v in gene.evolution_paths.values())
            lines.append(
                f"  {tag} {name}: {len(vals)} 值, "
                f"{path_count} 條演化路徑"
            )
            lines.append(f"    值: {', '.join(vals)}")
            lines.append(f"    預設: {gene.default_value}")
            lines.append(f"    突變倍數: ×{gene.mutation_rate_bonus}")
            if gene.description:
                lines.append(f"    說明: {gene.description}")
            lines.append("")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"GeneConfigManager(genes={len(self._genes)}, "
            f"path='{self.config_path}')"
        )
