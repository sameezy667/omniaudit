"""AST-only planning for Python modules.

The planner never imports or executes target code.  It produces stable, relative
work units that the local agents can use to generate focused edge-case tests.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class WorkUnit:
    """One function-level unit of work discovered in a module."""

    module: str
    function: str
    args: tuple[str, ...]
    defaults: tuple[str, ...]
    complexity: int
    lineno: int
    end_lineno: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModulePlan:
    """Parsed module metadata and its function work units."""

    path: str
    source: str
    work_units: tuple[WorkUnit, ...]
    module_complexity: int
    syntax_error: str | None = None
    file_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "work_units": [unit.to_dict() for unit in self.work_units],
            "module_complexity": self.module_complexity,
            "syntax_error": self.syntax_error,
        }


def _relative_path(path: Path, root: Path) -> str:
    """Return a stable relative path, never an absolute path."""

    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _display_default(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return ast.dump(node, annotate_fields=False)


def _function_arguments(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg:
        args.append(node.args.vararg)
    if node.args.kwarg:
        args.append(node.args.kwarg)
    return tuple(argument.arg for argument in args)


def _function_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    positional = [*node.args.posonlyargs, *node.args.args]
    positional_defaults: list[ast.expr | None] = [None] * (len(positional) - len(node.args.defaults))
    positional_defaults.extend(node.args.defaults)
    defaults: list[str] = [_display_default(value) for value in positional_defaults if value is not None]
    defaults.extend(_display_default(value) for value in node.args.kw_defaults if value is not None)
    return tuple(defaults)


def _branch_count(node: ast.AST) -> int:
    """Count decisions using a small, predictable cyclomatic metric."""

    count = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp)):
            count += 1
        elif isinstance(child, ast.BoolOp):
            count += max(0, len(child.values) - 1)
        elif isinstance(child, ast.ExceptHandler):
            count += 1
        elif isinstance(child, ast.comprehension):
            count += len(child.ifs)
        elif isinstance(child, ast.match_case) and child.guard is not None:
            count += 1
    return count


def cyclomatic_complexity(node: ast.AST) -> int:
    """Return McCabe-style complexity with a minimum of one."""

    return 1 + _branch_count(node)


def _iter_functions(tree: ast.AST) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def parse_module(path: Path, root: Path | None = None) -> ModulePlan:
    """Parse one file without importing it."""

    root = root or Path.cwd()
    source = path.read_text(encoding="utf-8")
    relative = _relative_path(path, root)
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"SyntaxError at line {exc.lineno or 0}, column {exc.offset or 0}: {exc.msg}"
        return ModulePlan(relative, source, (), 0, message, path)

    functions = tuple(
        WorkUnit(
            module=relative,
            function=node.name,
            args=_function_arguments(node),
            defaults=_function_defaults(node),
            complexity=cyclomatic_complexity(node),
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
        )
        for node in _iter_functions(tree)
    )
    functions = tuple(sorted(functions, key=lambda item: (item.lineno, item.function)))
    return ModulePlan(relative, source, functions, cyclomatic_complexity(tree), None, path)


def plan_directory(target_dir: Path) -> tuple[ModulePlan, ...]:
    """Discover Python modules below ``target_dir`` in deterministic order."""

    target_dir = Path(target_dir)
    root = Path.cwd()
    paths = sorted(
        path
        for path in target_dir.rglob("*.py")
        if "__pycache__" not in path.parts and not path.name.startswith("test_")
    )
    return tuple(parse_module(path, root=root) for path in paths)
