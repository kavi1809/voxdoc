"""
A restricted execution environment for model-written pandas code.

The previous implementation was `exec(code, {}, local_vars)` with a docstring
claiming it ran "safely". It did not: empty globals still get `__builtins__`
auto-injected, so `__import__('os').system(...)` worked. Since a malicious
uploaded document can steer the agent via prompt injection, that was remote code
execution reachable by anyone who could get a file in front of the model.

Defence in depth, cheapest check first:

  1. Parse to an AST and reject the code outright if it contains an import,
     any dunder name or attribute, a call to a non-allowlisted builtin, a
     function/class definition, or an I/O-capable method.
  2. Execute with `__builtins__` replaced by a small curated mapping.
  3. Expose a `pd` proxy carrying only analysis helpers — the real module has
     `read_pickle` (straight RCE) and a family of `to_*` file writers.
  4. Cap wall-clock time and output size.

Blocking dunder access is the load-bearing rule: nearly every Python sandbox
escape routes through `__class__` / `__subclasses__` / `__globals__` to reach
the real builtins.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import threading
from dataclasses import dataclass

import pandas as pd

MAX_OUTPUT_CHARS = 4000

# Builtins the model may call by name. Note what is absent: eval, exec, compile,
# open, getattr, setattr, globals, locals, vars, dir, type, input, __import__.
ALLOWED_BUILTINS: dict[str, object] = {
    name: getattr(builtins, name)
    for name in (
        "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "float",
        "int", "isinstance", "len", "list", "max", "min", "print", "range",
        "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
    )
}

# pandas top-level functions that are safe: they transform values in memory and
# touch neither the filesystem nor the network.
_SAFE_PD_NAMES = (
    "DataFrame", "Series", "Categorical", "Index", "MultiIndex",
    "concat", "merge", "pivot_table", "crosstab", "cut", "qcut",
    "to_datetime", "to_numeric", "to_timedelta", "date_range",
    "isna", "notna", "isnull", "notnull", "unique", "factorize",
    "NA", "NaT", "Timestamp", "Timedelta", "options",
)

# Method names that can reach the filesystem, a database, or the clipboard.
# `eval` and `query` are here because pandas' expression engines accept
# `engine="python"`, which reopens arbitrary evaluation. Boolean masks do the
# same filtering job and stay inside the AST checker.
BLOCKED_ATTRS = frozenset(
    {
        "eval", "query", "pipe",
        "to_csv", "to_excel", "to_pickle", "to_parquet", "to_hdf", "to_sql",
        "to_feather", "to_orc", "to_stata", "to_gbq", "to_clipboard", "to_xml",
        "to_json", "to_latex", "to_html",
    }
    | {n for n in dir(pd) if n.startswith("read_")}
)

# These render a result but accept a `buf`/path first argument that would write
# to disk, so they are allowed only with no positional arguments.
NO_POSITIONAL_ATTRS = frozenset({"to_string", "to_markdown", "info"})

# Keyword arguments that name a file, connection, or evaluation engine.
BLOCKED_KWARGS = frozenset(
    {"buf", "path", "path_or_buf", "fname", "filepath_or_buffer", "con", "engine", "excel_writer"}
)


class SandboxError(Exception):
    """Raised when code is rejected before it ever runs."""


class _Validator(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:
        raise SandboxError("imports are not allowed")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise SandboxError("imports are not allowed")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        raise SandboxError("function definitions are not allowed")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        raise SandboxError("function definitions are not allowed")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        raise SandboxError("class definitions are not allowed")

    def visit_Global(self, node: ast.Global) -> None:
        raise SandboxError("global is not allowed")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        raise SandboxError("nonlocal is not allowed")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("_"):
            raise SandboxError(f"access to '{node.id}' is not allowed")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise SandboxError(f"access to attribute '{node.attr}' is not allowed")
        if node.attr in BLOCKED_ATTRS:
            hint = (
                "use a boolean mask instead, e.g. df[df.col > 5]"
                if node.attr in ("eval", "query")
                else "compute the answer in memory and print it"
            )
            raise SandboxError(f"'{node.attr}' is not allowed - {hint}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Bare-name calls must be an allowed builtin (or a sandbox-provided name).
        if isinstance(node.func, ast.Name):
            if node.func.id not in ALLOWED_BUILTINS and node.func.id not in ("pd", "df"):
                raise SandboxError(f"calling '{node.func.id}' is not allowed")

        if isinstance(node.func, ast.Attribute):
            if node.func.attr in NO_POSITIONAL_ATTRS and node.args:
                raise SandboxError(
                    f"'{node.func.attr}' must be called with no positional arguments"
                )

        for kw in node.keywords:
            if kw.arg in BLOCKED_KWARGS:
                raise SandboxError(f"the '{kw.arg}' argument is not allowed")

        self.generic_visit(node)


class _PandasProxy:
    """Exposes only the analysis surface of pandas."""

    def __init__(self) -> None:
        for name in _SAFE_PD_NAMES:
            if hasattr(pd, name):
                object.__setattr__(self, name, getattr(pd, name))

    def __setattr__(self, name: str, value: object) -> None:
        raise SandboxError("the pd namespace is read-only")


def validate(code: str) -> None:
    """Raise SandboxError if `code` is not safe to execute."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxError(f"syntax error: {exc.msg}") from exc
    _Validator().visit(tree)


@dataclass
class SandboxResult:
    ok: bool
    output: str


def run(code: str, df: pd.DataFrame, timeout_seconds: int = 10) -> SandboxResult:
    """
    Validate, then execute `code` with `df` and `pd` in scope.

    Whatever the code prints is the answer; a variable named `result` is used as
    a fallback if nothing was printed.
    """
    try:
        validate(code)
    except SandboxError as exc:
        return SandboxResult(False, f"Rejected: {exc}")

    # One namespace for both globals and locals. With two separate dicts, a list
    # comprehension cannot see `df` — comprehensions resolve free variables in
    # globals, not in an enclosing locals mapping — so `[x for x in df.col]`
    # would fail with NameError.
    namespace: dict[str, object] = {
        "__builtins__": dict(ALLOWED_BUILTINS),
        "df": df,
        "pd": _PandasProxy(),
    }

    stdout = io.StringIO()
    error: list[BaseException] = []

    def target() -> None:
        try:
            with contextlib.redirect_stdout(stdout):
                exec(compile(code, "<agent>", "exec"), namespace)  # noqa: S102
        except BaseException as exc:  # noqa: BLE001 — reported back to the model
            error.append(exc)

    # A worker thread gives us a wall-clock cap. Python cannot forcibly kill a
    # thread, so a runaway computation keeps burning CPU in the background until
    # it finishes; the daemon flag at least stops it blocking shutdown. This is
    # the accepted trade-off for staying single-process and cross-platform.
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout_seconds)

    if worker.is_alive():
        return SandboxResult(
            False, f"Timed out after {timeout_seconds}s — try a simpler computation."
        )

    if error:
        return SandboxResult(False, f"Error running code: {type(error[0]).__name__}: {error[0]}")

    output = stdout.getvalue().strip()
    if not output and "result" in namespace:
        output = str(namespace["result"]).strip()
    if not output:
        return SandboxResult(
            True, "The code ran but printed nothing. Use print() to show the answer."
        )

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n… (output truncated)"
    return SandboxResult(True, output)
