"""엔진 확장 지점과 Clean Architecture 경계를 고정한다."""

import ast
from pathlib import Path

from src.core.engine.base import TradingEngine


ENGINE_DIR = Path("src/core/engine")


def _engine_modules():
    return [
        path for path in ENGINE_DIR.glob("*.py")
        if path.name not in {"base.py", "__init__.py", "registry.py", "data_pipeline.py"}
    ]


def test_concrete_engines_cannot_override_common_cycle_flow():
    forbidden = {"run_one_cycle", "execute_cycle", "collect_data", "calculate_indicators"}
    violations = []
    for path in _engine_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden:
                violations.append(f"{path}:{node.lineno}:{node.name}")

    assert violations == []


def test_concrete_engines_do_not_call_infrastructure_ports_directly():
    forbidden_attributes = {"broker", "repo", "notifier"}
    violations = []
    for path in _engine_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr in forbidden_attributes
            ):
                violations.append(f"{path}:{node.lineno}:self.{node.attr}")

    assert violations == []


def test_core_does_not_import_outer_layers():
    forbidden_prefixes = (
        "src.infra",
        "src.backtest",
        "src.utils",
        "src.config",
    )
    violations = []
    for path in Path("src/core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden_prefixes):
                    violations.append(f"{path}:{node.lineno}:{node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden_prefixes):
                        violations.append(f"{path}:{node.lineno}:{alias.name}")

    assert violations == []


def test_trading_engine_owns_cycle_methods():
    assert "run_one_cycle" in TradingEngine.__dict__
    assert "execute_cycle" in TradingEngine.__dict__
