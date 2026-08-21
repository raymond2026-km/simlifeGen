"""
SimLife Evolution System — 沙盒式人工生命模擬器

玩家不直接控制「模擬人 (Sims)」的行為，而是透過修改基因編碼、
調整物理環境與投放天敵/食物，觀察模擬人在世代交替中的自然選擇
與演化歷程。
"""

__version__ = "1.0.0"
__author__ = "SimLife Dev Team"

from .gene_config_manager import GeneConfigManager
from .genetic_engine import ConfigDrivenGeneticEngine, ConfigChromosome, GeneSlot
from .sim import Sim, SimState, DeathCause
from .metabolism import MetabolismEngine
from .environment import EnvironmentManager, ClimateState
from .ecology import EcologyManager, Resource
from .selection import SelectionEngine
from .simulation import SimulationEngine, SimulationConfig

__all__ = [
    "GeneConfigManager",
    "ConfigDrivenGeneticEngine",
    "ConfigChromosome",
    "GeneSlot",
    "Sim",
    "SimState",
    "DeathCause",
    "MetabolismEngine",
    "EnvironmentManager",
    "ClimateState",
    "EcologyManager",
    "Resource",
    "SelectionEngine",
    "SimulationEngine",
    "SimulationConfig",
]
