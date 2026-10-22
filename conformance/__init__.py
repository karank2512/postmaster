"""Cross-model MCP conformance suite (prototype). Run: python -m conformance run"""

from .harness import run_scenario, run_suite
from .scenarios import SCENARIOS, Scenario

__all__ = ["SCENARIOS", "Scenario", "run_scenario", "run_suite"]
