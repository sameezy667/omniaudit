from __future__ import annotations

from pathlib import Path

from omniaudit.agents import audit_directory, run_module_agent
from omniaudit.cli import main
from omniaudit.planner import parse_module, plan_directory
from omniaudit.sandbox import run_pytest


EXAMPLE = Path("examples/buggy_pkg/math_ops.py")


def test_ast_planner_extracts_functions_arguments_defaults_and_complexity():
    plan = parse_module(EXAMPLE, root=Path.cwd())
    assert plan.path == "examples/buggy_pkg/math_ops.py"
    assert [unit.function for unit in plan.work_units] == ["average", "tail", "append_item"]
    assert plan.work_units[0].args == ("nums",)
    assert plan.work_units[2].defaults == ("[]",)
    assert all(unit.complexity == 1 for unit in plan.work_units)
    assert plan.module_complexity == 1


def test_ast_planner_handles_syntax_error_without_importing_code(tmp_path: Path):
    broken = tmp_path / "broken.py"
    broken.write_text("def broken(:\n    pass\n", encoding="utf-8")
    plan = parse_module(broken, root=tmp_path)
    assert plan.syntax_error is not None
    assert "SyntaxError" in plan.syntax_error
    assert plan.work_units == ()


def test_planner_directory_is_deterministic_and_relative():
    plans = plan_directory(Path("examples/buggy_pkg"))
    assert [plan.path for plan in plans] == ["examples/buggy_pkg/__init__.py", "examples/buggy_pkg/math_ops.py"]
    assert all(not Path(plan.path).is_absolute() for plan in plans)


def test_sandbox_executes_generated_tests_offline(tmp_path: Path):
    module = tmp_path / "sample.py"
    module.write_text("def answer():\n    return 42\n", encoding="utf-8")
    tests = "from sample import answer\n\ndef test_answer():\n    assert answer() == 42\n"
    result = run_pytest(module, tests)
    assert result.passed
    assert result.returncode == 0
    assert result.test_count == 1
    assert "sample.py" not in result.stderr


def test_sandbox_timeout_is_reported(tmp_path: Path):
    module = tmp_path / "slow.py"
    module.write_text("import time\n\ndef wait():\n    time.sleep(2)\n", encoding="utf-8")
    tests = "import time\nfrom slow import wait\n\ndef test_wait():\n    wait()\n"
    result = run_pytest(module, tests, timeout_seconds=0.1)
    assert result.timed_out
    assert not result.passed


def test_parallel_agent_triage_generates_and_verifies_patch_without_mutating_source():
    original_source = EXAMPLE.read_text(encoding="utf-8")
    plan = parse_module(EXAMPLE, root=Path.cwd())
    audit = run_module_agent(plan)
    assert {finding.status for finding in audit.findings} == {"REAL_BUG"}
    assert "--- examples/buggy_pkg/math_ops.py" in audit.patch_diff
    assert audit.patched is not None
    assert audit.patched.passed
    assert audit.patch_verified
    assert EXAMPLE.read_text(encoding="utf-8") == original_source


def test_parallel_audit_benchmark_compares_serial_and_parallel_execution():
    run = audit_directory(Path("examples/buggy_pkg"), workers=4, benchmark=True)
    assert len(run.modules) == 2
    assert run.serial_seconds is not None and run.serial_seconds > 0
    assert run.parallel_seconds is not None and run.parallel_seconds > 0
    assert run.speedup is not None and run.speedup > 0
    assert run.verified


def test_cli_writes_human_report_with_relative_paths(tmp_path: Path, capsys):
    report_path = tmp_path / "report.md"
    exit_code = main(
        [
            "scan",
            "examples/buggy_pkg",
            "--benchmark",
            "--output",
            str(report_path),
        ]
    )
    captured = capsys.readouterr()
    report = report_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "# OmniAudit Report" in report
    assert "## Benchmark" in report
    assert "REAL_BUG" in report
    assert "### Synthesized unified diff" in report
    assert "Target: `/" not in report
    assert "**Target:** `examples/buggy_pkg`" in captured.out


def test_sandbox_result_does_not_leak_machine_paths(tmp_path: Path):
    module = tmp_path / "failing.py"
    module.write_text("def fail():\n    raise RuntimeError('expected')\n", encoding="utf-8")
    tests = "from failing import fail\n\ndef test_fail():\n    fail()\n"
    result = run_pytest(module, tests)
    assert not result.passed
    assert str(tmp_path) not in result.stdout
    assert str(tmp_path) not in result.stderr
