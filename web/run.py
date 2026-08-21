#!/usr/bin/env python3
"""
SimLife Gene Config Editor — 啟動腳本

用法：
    python simlife/web/run.py [--port 5000]
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from simlife.web.server import create_app
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5000)
parser.add_argument('--host', type=str, default='127.0.0.1')
parser.add_argument('--config', type=str, default=None)
args = parser.parse_args()

config = args.config or os.path.join(os.path.dirname(__file__), '..', 'configs', 'gene_config.json')
app = create_app(config)

print(f"🧬 SimLife Gene Config Editor")
print(f"   http://{args.host}:{args.port}")
print(f"   Config: {config}")
app.run(host=args.host, port=args.port, debug=True)
