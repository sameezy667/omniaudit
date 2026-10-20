"""Disposable, offline-oriented pytest execution for generated tests."""

from __future__ import annotations

import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxResult:
    """Result of one isolated pytest invocation."""

    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    test_count: int

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _sanitize(text: str, sandbox_root: Path) -> str:
    """Remove disposable and machine-specific paths from captured diagnostics."""

    sanitized = text.replace(str(sandbox_root), "<sandbox>")
    sanitized = re.sub(r'(?<![A-Za-z0-9_])/(?:[^\s\"\']+)', "<absolute-path>", sanitized)
    return sanitized


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _safe_environment() -> dict[str, str]:
    path = os.environ.get("PATH", "")
    return {
        "PATH": path,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONHASHSEED": "0",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }


def _test_count(stdout: str) -> int:
    counts = re.findall(r"(\d+)\s+(?:passed|failed|error|errors)", stdout)
    return sum(int(count) for count in counts)


def run_pytest(
    module_path: Path,
    test_source: str,
    *,
    patched_source: str | None = None,
    timeout_seconds: float = 5.0,
) -> SandboxResult:
    """Copy a module and generated test to a temp directory and run pytest.

    The subprocess receives a minimal environment, no shell, no stdin, and a
    hard timeout.  The caller's source tree is never modified.
    """

    module_path = Path(module_path)
    module_name = module_path.stem
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="omniaudit-") as temporary:
        sandbox_root = Path(temporary)
        source = patched_source if patched_source is not None else module_path.read_text(encoding="utf-8")
        (sandbox_root / f"{module_name}.py").write_text(source, encoding="utf-8")
        (sandbox_root / "test_generated.py").write_text(test_source, encoding="utf-8")
        command = (sys.executable, "-m", "pytest", "-q", "test_generated.py")
        process = subprocess.Popen(
            command,
            cwd=sandbox_root,
            env=_safe_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            start_new_session=(os.name == "posix"),
        )
        try:
            stdout_text, stderr_text = process.communicate(timeout=timeout_seconds)
            stdout = _sanitize(_as_text(stdout_text), sandbox_root)
            stderr = _sanitize(_as_text(stderr_text), sandbox_root)
            return SandboxResult(
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=time.perf_counter() - started,
                timed_out=False,
                test_count=_test_count(stdout),
            )
        except subprocess.TimeoutExpired as exc:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                stdout_text, stderr_text = process.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                stdout_text, stderr_text = process.communicate()
            stdout = _sanitize(_as_text(stdout_text) or _as_text(exc.stdout), sandbox_root)
            stderr = _sanitize(_as_text(stderr_text) or _as_text(exc.stderr), sandbox_root)
            return SandboxResult(
                returncode=None,
                stdout=stdout,
                stderr=stderr or "pytest timed out",
                duration_seconds=time.perf_counter() - started,
                timed_out=True,
                test_count=0,
            )


def copy_for_inspection(module_path: Path, destination: Path) -> Path:
    """Small utility used by callers that need a named disposable copy."""

    destination.mkdir(parents=True, exist_ok=True)
    target = destination / module_path.name
    shutil.copyfile(module_path, target)
    return target
