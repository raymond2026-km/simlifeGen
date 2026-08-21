"""
SimLife Evolution System — 主進入點

用法：
    python -m simlife.main [--ticks N] [--pop N] [--seed S]

範例：
    python -m simlife.main
    python -m simlife.main --ticks 5000 --pop 100 --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from .simulation import SimulationEngine, SimulationConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SimLife Evolution System — 沙盒式人工生命模擬器"
    )
    parser.add_argument(
        "--ticks", type=int, default=2000,
        help="模擬 tick 數 (default: 2000)"
    )
    parser.add_argument(
        "--pop", type=int, default=50,
        help="初始種群數量 (default: 50)"
    )
    parser.add_argument(
        "--max-pop", type=int, default=200,
        help="最大種群數量 (default: 200)"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="隨機種子 (default: None)"
    )
    parser.add_argument(
        "--mutation-rate", type=float, default=0.01,
        help="基礎突變率 (default: 0.01)"
    )
    parser.add_argument(
        "--map-size", type=int, default=50,
        help="地圖大小 (NxN) (default: 50)"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="靜默模式"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="輸出統計 JSON 檔案路徑"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = SimulationConfig(
        initial_population=args.pop,
        max_population=args.max_pop,
        ticks_per_season=200,
        ticks_per_day=100,
        base_mutation_rate=args.mutation_rate,
        max_ticks=args.ticks,
        map_width=args.map_size,
        map_height=args.map_size,
        seed=args.seed,
    )

    engine = SimulationEngine(config)

    start_time = time.time()
    stats = engine.run(verbose=not args.quiet)
    elapsed = time.time() - start_time

    if not args.quiet:
        print(f"\n⏱️  模擬耗時: {elapsed:.2f}s")
        print(f"   每 tick: {elapsed / max(1, args.ticks) * 1000:.1f}ms")

    # 輸出 JSON
    if args.output:
        output = {
            "config": {
                "ticks": args.ticks,
                "population": args.pop,
                "seed": args.seed,
            },
            "final_population": len(engine.population),
            "tick_stats": stats[-100:] if len(stats) > 100 else stats,
            "gene_chains": engine.selection.get_stats(),
            "death_summary": {},
        }

        # 死因統計
        for d in engine.death_log:
            cause = d["cause"]
            output["death_summary"][cause] = output["death_summary"].get(cause, 0) + 1

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"📄 統計已輸出至 {args.output}")


if __name__ == "__main__":
    main()
