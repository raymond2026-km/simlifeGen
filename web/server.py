"""
SimLife Gene Config Editor — Web Server

Flask-based web UI for designers to visually edit gene_config.json,
add/remove genes, and preview evolution paths as a graph.

用法：
    python -m simlife.web.server [--port 5000] [--config path/to/gene_config.json]

或從 Python：
    from simlife.web.server import create_app
    app = create_app("configs/gene_config.json")
    app.run(port=5000)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from flask import Flask, render_template, jsonify, request, send_from_directory

# 嘗試載入 GeneConfigManager
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from simlife.gene_config_manager import GeneConfigManager


def create_app(config_path: str | Path | None = None) -> Flask:
    """建立 Flask 應用"""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    if config_path is None:
        config_path = Path(__file__).parent.parent / "configs" / "gene_config.json"
    config_path = Path(config_path)

    manager = GeneConfigManager(config_path)

    # ════════════════════════════════════════════════════════
    #  頁面路由
    # ════════════════════════════════════════════════════════

    @app.route("/")
    def index():
        return render_template("index.html")

    # ════════════════════════════════════════════════════════
    #  API 路由 — 基因配置 CRUD
    # ════════════════════════════════════════════════════════

    @app.route("/api/config", methods=["GET"])
    def get_full_config():
        """取得完整配置（JSON 格式）"""
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return jsonify(raw)

    @app.route("/api/genes", methods=["GET"])
    def list_genes():
        """列出所有基因"""
        genes = []
        for name in manager.get_all_gene_names():
            gene = manager.get_gene(name)
            genes.append({
                "name": name,
                "description": gene.description,
                "default_value": gene.default_value,
                "mutation_rate_bonus": gene.mutation_rate_bonus,
                "is_custom": gene.is_custom,
                "num_values": len(gene.values),
                "num_paths": sum(len(v) for v in gene.evolution_paths.values()),
                "values": list(gene.values.keys()),
                "simulation_hooks": gene.simulation_hooks,
            })
        return jsonify({"genes": genes})

    @app.route("/api/genes/<gene_name>", methods=["GET"])
    def get_gene(gene_name: str):
        """取得單個基因的完整資訊"""
        try:
            gene = manager.get_gene(gene_name)
        except KeyError as e:
            return jsonify({"error": str(e)}), 404

        values = {}
        for val_name, gv in gene.values.items():
            values[val_name] = {
                "name": val_name,
                "attributes": gv.attributes,
            }

        return jsonify({
            "name": gene.gene_name,
            "description": gene.description,
            "default_value": gene.default_value,
            "mutation_rate_bonus": gene.mutation_rate_bonus,
            "is_custom": gene.is_custom,
            "values": values,
            "evolution_paths": gene.evolution_paths,
            "attributes_schema": gene.attributes_schema,
            "simulation_hooks": gene.simulation_hooks,
        })

    @app.route("/api/genes", methods=["POST"])
    def create_gene():
        """新增一個基因"""
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Gene name is required"}), 400

        if name in [n for n in manager.get_all_gene_names()]:
            return jsonify({"error": f"Gene '{name}' already exists"}), 409

        values = data.get("values", {})
        evolution_paths = data.get("evolution_paths", {})

        if not values:
            return jsonify({"error": "At least one value is required"}), 400

        # 確保所有 evolution_paths 引用的值都存在
        for source, targets in evolution_paths.items():
            if source not in values:
                return jsonify({
                    "error": f"Evolution path source '{source}' not in values"
                }), 400
            for t in targets:
                if t not in values:
                    return jsonify({
                        "error": f"Evolution path target '{t}' not in values"
                    }), 400

        try:
            gene_def = manager.register_gene(
                gene_name=name,
                description=data.get("description", ""),
                values=values,
                evolution_paths=evolution_paths,
                default_value=data.get("default_value", list(values.keys())[0]),
                mutation_rate_bonus=data.get("mutation_rate_bonus", 3.0),
                attributes_schema=data.get("attributes_schema", {}),
                simulation_hooks=data.get("simulation_hooks", {}),
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({
            "success": True,
            "gene": {
                "name": gene_def.gene_name,
                "description": gene_def.description,
                "num_values": len(gene_def.values),
            }
        }), 201

    @app.route("/api/genes/<gene_name>", methods=["PUT"])
    def update_gene(gene_name: str):
        """更新一個基因"""
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        try:
            existing = manager.get_gene(gene_name)
        except KeyError as e:
            return jsonify({"error": str(e)}), 404

        # 先移除舊的，再重新註冊
        manager.remove_gene(gene_name)

        values = data.get("values", {})
        if not values:
            # 如果沒有提供 values，用原本的
            values = {v.name: v.attributes for v in existing.values.values()}

        evolution_paths = data.get("evolution_paths", existing.evolution_paths)

        try:
            gene_def = manager.register_gene(
                gene_name=gene_name,
                description=data.get("description", existing.description),
                values=values,
                evolution_paths=evolution_paths,
                default_value=data.get("default_value", existing.default_value),
                mutation_rate_bonus=data.get("mutation_rate_bonus", existing.mutation_rate_bonus),
                attributes_schema=data.get("attributes_schema", existing.attributes_schema),
                simulation_hooks=data.get("simulation_hooks", existing.simulation_hooks),
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({
            "success": True,
            "gene": {
                "name": gene_def.gene_name,
                "num_values": len(gene_def.values),
            }
        })

    @app.route("/api/genes/<gene_name>", methods=["DELETE"])
    def delete_gene(gene_name: str):
        """刪除一個基因（僅限自定義基因）"""
        try:
            gene = manager.get_gene(gene_name)
            if not gene.is_custom:
                return jsonify({"error": "Cannot delete built-in genes"}), 403
            manager.remove_gene(gene_name)
            return jsonify({"success": True, "deleted": gene_name})
        except KeyError as e:
            return jsonify({"error": str(e)}), 404

    # ════════════════════════════════════════════════════════
    #  API 路由 — 演化路徑圖
    # ════════════════════════════════════════════════════════

    @app.route("/api/evolution-graph/<gene_name>", methods=["GET"])
    def get_evolution_graph(gene_name: str):
        """取得基因的演化路徑圖（節點 + 邊）"""
        try:
            gene = manager.get_gene(gene_name)
        except KeyError as e:
            return jsonify({"error": str(e)}), 404

        nodes = []
        for val_name, gv in gene.values.items():
            nodes.append({
                "id": val_name,
                "label": val_name,
                "attributes": gv.attributes,
            })

        edges = []
        seen_edges = set()
        for source, targets in gene.evolution_paths.items():
            for target in targets:
                edge_key = f"{source}->{target}"
                reverse_key = f"{target}->{source}"
                if edge_key not in seen_edges and reverse_key not in seen_edges:
                    edges.append({
                        "source": source,
                        "target": target,
                        "bidirectional": reverse_key in [
                            f"{s}->{t}"
                            for s, ts in gene.evolution_paths.items()
                            for t in ts
                        ],
                    })
                    seen_edges.add(edge_key)

        return jsonify({
            "gene_name": gene_name,
            "nodes": nodes,
            "edges": edges,
        })

    # ════════════════════════════════════════════════════════
    #  API 路由 — 儲存
    # ════════════════════════════════════════════════════════

    @app.route("/api/save", methods=["POST"])
    def save_config():
        """將當前配置儲存回 JSON 檔案"""
        try:
            manager.export_config(config_path)
            return jsonify({"success": True, "path": str(config_path)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reload", methods=["POST"])
    def reload_config():
        """從磁碟重新載入配置"""
        try:
            manager.load()
            return jsonify({"success": True, "genes": manager.get_all_gene_names()})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ════════════════════════════════════════════════════════
    #  API 路由 — 配置驗證
    # ════════════════════════════════════════════════════════

    @app.route("/api/validate", methods=["GET"])
    def validate_config():
        """驗證當前配置的完整性"""
        issues = []
        for name in manager.get_all_gene_names():
            gene = manager.get_gene(name)
            # 檢查 evolution_paths 引用
            for source, targets in gene.evolution_paths.items():
                if source not in gene.values:
                    issues.append(f"{name}: path source '{source}' not in values")
                for t in targets:
                    if t not in gene.values:
                        issues.append(f"{name}: path target '{t}' not in values")
            # 檢查 default_value
            if gene.default_value not in gene.values:
                issues.append(f"{name}: default_value '{gene.default_value}' not in values")

        return jsonify({
            "valid": len(issues) == 0,
            "issues": issues,
        })

    return app


# ════════════════════════════════════════════════════════════════
#  CLI 入口
# ════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="SimLife Gene Config Editor")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app(args.config)
    print(f"🧬 SimLife Gene Config Editor")
    print(f"   http://{args.host}:{args.port}")
    print(f"   Config: {args.config or 'auto-detect'}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
