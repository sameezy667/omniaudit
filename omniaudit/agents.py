"""Deterministic local agents for test generation, triage, and patch checking."""

from __future__ import annotations

import difflib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .planner import ModulePlan, WorkUnit, plan_directory
from .sandbox import SandboxResult, run_pytest


@dataclass(frozen=True)
class Finding:
    module: str
    function: str
    category: str
    message: str
    evidence: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModuleAudit:
    plan: ModulePlan
    generated_tests: str
    original: SandboxResult
    patched: SandboxResult | None
    findings: tuple[Finding, ...]
    patch_diff: str
    patch_verified: bool
    duration_seconds: float

    @property
    def path(self) -> str:
        return self.plan.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.plan.path,
            "module_complexity": self.plan.module_complexity,
            "syntax_error": self.plan.syntax_error,
            "work_units": [unit.to_dict() for unit in self.plan.work_units],
            "findings": [finding.to_dict() for finding in self.findings],
            "original": _result_dict(self.original),
            "patched": _result_dict(self.patched) if self.patched else None,
            "patch_diff": self.patch_diff,
            "patch_verified": self.patch_verified,
            "duration_seconds": round(self.duration_seconds, 6),
        }


@dataclass(frozen=True)
class AuditRun:
    modules: tuple[ModuleAudit, ...]
    serial_seconds: float | None
    parallel_seconds: float | None
    speedup: float | None
    workers: int

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(finding for module in self.modules for finding in module.findings)

    @property
    def verified(self) -> bool:
        return all(module.patch_verified for module in self.modules)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modules": [module.to_dict() for module in self.modules],
            "findings": [finding.to_dict() for finding in self.findings],
            "serial_seconds": self.serial_seconds,
            "parallel_seconds": self.parallel_seconds,
            "speedup": self.speedup,
            "workers": self.workers,
            "verified": self.verified,
        }


def _result_dict(result: SandboxResult) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": round(result.duration_seconds, 6),
        "timed_out": result.timed_out,
        "test_count": result.test_count,
        "passed": result.passed,
    }


def _function_map(plan: ModulePlan) -> dict[str, WorkUnit]:
    return {unit.function: unit for unit in plan.work_units}


def generate_edge_case_tests(plan: ModulePlan) -> str:
    """Generate focused tests for known edge-case patterns.

    The generated suite intentionally expresses the desired contract, so a
    failing test is actionable evidence rather than an implementation detail.
    """

    module_name = Path(plan.path).stem
    functions = _function_map(plan)
    lines = ["import pytest", f"from {module_name} import *", ""]
    if "average" in functions:
        lines.extend(
            [
                "def test_average_empty_input_is_explicit():",
                "    with pytest.raises(ValueError):",
                "        average([])",
                "",
                "def test_average_regular_input():",
                "    assert average([2, 4, 6]) == 4.0",
                "",
                "def test_average_zero_value():",
                "    assert average([0]) == 0.0",
                "",
            ]
        )
    if "tail" in functions:
        lines.extend(
            [
                "def test_tail_returns_last_n_items():",
                "    assert tail([0, 1, 2, 3], 2) == [2, 3]",
                "",
                "def test_tail_empty_input_is_safe():",
                "    assert tail([], 1) == []",
                "",
                "def test_tail_non_positive_n_is_empty():",
                "    assert tail([0, 1, 2], 0) == []",
                "    assert tail([0, 1, 2], -1) == []",
                "",
            ]
        )
    if "append_item" in functions:
        lines.extend(
            [
                "def test_append_item_does_not_share_default_state():",
                "    first = append_item('first')",
                "    second = append_item('second')",
                "    assert first == ['first']",
                "    assert second == ['second']",
                "",
            ]
        )
    if len(lines) == 3:
        lines.extend(
            [
                "def test_module_imports():",
                f"    assert __import__('{module_name}')",
                "",
            ]
        )
    return "\n".join(lines)


def _patch_source(plan: ModulePlan) -> str | None:
    """Apply deterministic, narrow fixes to the demonstration patterns."""

    source = plan.source
    if "average" in _function_map(plan) and "if not nums:" not in source:
        marker = "def average(nums):\n"
        if marker in source:
            source = source.replace(
                marker,
                marker + '    if not nums:\n        raise ValueError("nums must not be empty")\n',
                1,
            )
    if "tail" in _function_map(plan):
        source = source.replace("return items[:n]", "return items[-n:] if n > 0 else []", 1)
    if "append_item" in _function_map(plan) and "bucket=None" not in source:
        source = source.replace("bucket=[]", "bucket=None", 1)
        marker = "def append_item(val, bucket=None):\n"
        if marker in source:
            source = source.replace(marker, marker + "    if bucket is None:\n        bucket = []\n", 1)
    return source if source != plan.source else None


def _unified_diff(plan: ModulePlan, patched_source: str | None) -> str:
    if patched_source is None:
        return ""
    diff = difflib.unified_diff(
        plan.source.splitlines(),
        patched_source.splitlines(),
        fromfile=plan.path,
        tofile=plan.path,
        lineterm="",
    )
    return "\n".join(diff)


def _triage(plan: ModulePlan, result: SandboxResult) -> tuple[Finding, ...]:
    if result.passed:
        return ()
    collection_error = "ERROR collecting" in result.stdout or "SyntaxError" in result.stderr
    status = "TEST_ERROR" if collection_error else "REAL_BUG"
    evidence = (result.stderr or result.stdout).strip().splitlines()
    evidence_text = evidence[-1] if evidence else "pytest returned a non-zero status"
    findings: list[Finding] = []
    for unit in plan.work_units:
        if unit.function in {"average", "tail", "append_item"}:
            message = {
                "average": "empty input should raise ValueError instead of dividing by zero",
                "tail": "tail should return the last n items",
                "append_item": "default bucket must not be shared between calls",
            }[unit.function]
            findings.append(
                Finding(plan.path, unit.function, "REAL_BUG" if status == "REAL_BUG" else "TEST_ERROR", message, evidence_text, status)
            )
    if not findings:
        findings.append(Finding(plan.path, "<module>", status, "generated test execution failed", evidence_text, status))
    return tuple(findings)


def run_module_agent(plan: ModulePlan, *, timeout_seconds: float = 5.0) -> ModuleAudit:
    """Run one local agent for one module and verify its synthesized patch."""

    started = time.perf_counter()
    if plan.syntax_error:
        result = SandboxResult(1, "", plan.syntax_error, 0.0, False, 0)
        return ModuleAudit(plan, "", result, None, _triage(plan, result), "", False, time.perf_counter() - started)

    generated = generate_edge_case_tests(plan)
    module_path = plan.file_path or Path(plan.path)
    original = run_pytest(module_path, generated, timeout_seconds=timeout_seconds)
    findings = _triage(plan, original)
    patch = _patch_source(plan) if any(finding.status == "REAL_BUG" for finding in findings) else None
    patched = None
    verified = original.passed
    if patch is not None:
        patched = run_pytest(module_path, generated, patched_source=patch, timeout_seconds=timeout_seconds)
        verified = patched.passed
    return ModuleAudit(
        plan=plan,
        generated_tests=generated,
        original=original,
        patched=patched,
        findings=findings,
        patch_diff=_unified_diff(plan, patch),
        patch_verified=verified,
        duration_seconds=time.perf_counter() - started,
    )


def _run_modules(plans: Iterable[ModulePlan], workers: int) -> tuple[ModuleAudit, ...]:
    ordered = tuple(sorted(plans, key=lambda plan: plan.path))
    if workers <= 1 or len(ordered) <= 1:
        return tuple(run_module_agent(plan) for plan in ordered)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="omniaudit") as executor:
        audits = list(executor.map(run_module_agent, ordered))
    return tuple(audits)


def audit_directory(target_dir: Path, *, workers: int = 4, benchmark: bool = False) -> AuditRun:
    """Audit all modules and optionally compare serial and parallel execution."""

    plans = plan_directory(Path(target_dir))
    serial_seconds: float | None = None
    parallel_seconds: float | None = None
    if benchmark:
        started = time.perf_counter()
        _run_modules(plans, 1)
        serial_seconds = time.perf_counter() - started
        started = time.perf_counter()
        modules = _run_modules(plans, workers)
        parallel_seconds = time.perf_counter() - started
    else:
        modules = _run_modules(plans, workers)
    speedup = None
    if serial_seconds is not None and parallel_seconds is not None and parallel_seconds > 0:
        speedup = serial_seconds / parallel_seconds
    return AuditRun(modules, serial_seconds, parallel_seconds, speedup, max(1, workers))
