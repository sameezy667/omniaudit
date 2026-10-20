"""Command-line interface for OmniAudit."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from .agents import AuditRun, audit_directory


def _relative_display(path: Path) -> str:
    path = Path(path)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name or "."


def _format_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def render_report(run: AuditRun, target_dir: Path, *, benchmark: bool) -> str:
    """Render a deterministic Markdown report with only relative paths."""

    status = "PASS" if run.verified else "REVIEW REQUIRED"
    lines = [
        "# OmniAudit Report",
        "",
        f"- **Status:** {status}",
        f"- **Target:** `{_relative_display(target_dir)}`",
        f"- **Workers:** `{run.workers}`",
        f"- **Modules analyzed:** `{len(run.modules)}`",
        f"- **Findings:** `{len(run.findings)}`",
        "",
        "## Architecture flow",
        "",
        "```text",
        "CLI -> AST planner -> ThreadPool agents -> disposable pytest sandbox",
        "                                      -> triage -> unified diff -> verify",
        "```",
        "",
    ]
    if benchmark:
        lines.extend(
            [
                "## Benchmark",
                "",
                "| Mode | Workers | Wall-clock seconds |",
                "| --- | ---: | ---: |",
                f"| Serial | 1 | {_format_seconds(run.serial_seconds)} |",
                f"| Parallel | {run.workers} | {_format_seconds(run.parallel_seconds)} |",
                f"| Speedup | - | {_format_seconds(run.speedup)}x |",
                "",
            ]
        )
    for module in run.modules:
        lines.extend(
            [
                f"## Module: `{module.path}`",
                "",
                f"- Module complexity: `{module.plan.module_complexity}`",
                f"- Generated tests: `{module.original.test_count}` collected result(s)",
                f"- Original run: `{'PASS' if module.original.passed else 'FAIL'}`",
                f"- Patched verification: `{'PASS' if module.patch_verified else 'FAIL'}`",
                "",
                "### Planned functions",
                "",
                "| Function | Arguments | Defaults | Complexity | Line |",
                "| --- | --- | --- | ---: | ---: |",
            ]
        )
        for unit in module.plan.work_units:
            lines.append(
                f"| `{unit.function}` | `{', '.join(unit.args) or '-'}` | "
                f"`{', '.join(unit.defaults) or '-'}` | {unit.complexity} | {unit.lineno} |"
            )
        lines.append("")
        if module.findings:
            lines.extend(["### Triage findings", ""])
            for finding in module.findings:
                lines.extend(
                    [
                        f"- **{finding.status}** `{finding.function}`: {finding.message}",
                        f"  - Evidence: `{finding.evidence[:240]}`",
                    ]
                )
            lines.append("")
        if module.patch_diff:
            lines.extend(["### Synthesized unified diff", "", "```diff", module.patch_diff, "```", ""])
        if module.patched:
            lines.extend(
                [
                    "### Verification output",
                    "",
                    "```text",
                    (module.patched.stdout or module.patched.stderr).strip(),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omniaudit",
        description="Agentic AST test-generation, sandboxed triage, and auto-patch CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan", help="scan a Python target directory")
    scan.add_argument("target_dir", type=Path)
    scan.add_argument("--benchmark", action="store_true", help="compare serial and parallel agent execution")
    scan.add_argument("--output", type=Path, default=Path("reports/latest_report.md"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "scan":
        return 2
    target_dir = Path(args.target_dir)
    if not target_dir.is_dir():
        print(f"error: target directory does not exist: {_relative_display(target_dir)}")
        return 2
    try:
        workers = max(1, int(os.environ.get("OMNIAUDIT_WORKERS", "4")))
    except ValueError:
        workers = 4
    run = audit_directory(target_dir, workers=workers, benchmark=args.benchmark)
    report = render_report(run, target_dir, benchmark=args.benchmark)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report, end="")
    return 0 if run.verified else 3
