"""
The pandas sandbox.

These are the regression tests for the worst hole in the original code: an
unguarded `exec()` of model-written Python, reachable through prompt injection
from any uploaded document.
"""

import pandas as pd
import pytest

from app.agent.sandbox import SandboxError, run, validate


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "region": ["North", "South", "North", "South"],
            "sales": [100, 250, 150, 300],
            "units": [10, 20, 15, 30],
        }
    )


ESCAPES = [
    ("import os\nprint(os.listdir('.'))", "import"),
    ("from os import system", "from-import"),
    ("print(().__class__.__bases__[0].__subclasses__())", "dunder subclass walk"),
    ("print(__import__('os').getcwd())", "dunder import"),
    ("print(open('secret.txt').read())", "open"),
    ("print(eval('1+1'))", "eval"),
    ("print(exec('x=1'))", "exec"),
    ("print(globals())", "globals"),
    ("print(getattr(df, 'to_csv'))", "getattr"),
    ("print(df.__class__.__module__)", "dunder attribute"),
    ("df.to_csv('/tmp/leak.csv')", "file write"),
    ("df.to_pickle('/tmp/x.pkl')", "pickle write"),
    ("print(pd.read_pickle('/tmp/x.pkl'))", "pickle read (RCE)"),
    ("print(pd.read_csv('/etc/passwd'))", "arbitrary file read"),
    ("print(df.to_string(buf='/tmp/out.txt'))", "buf keyword"),
    ("print(df.to_string('/tmp/out.txt'))", "buf positional"),
    ("print(df.query('sales > 100'))", "query engine"),
    ("print(df.eval('sales * 2'))", "eval engine"),
    ("def f():\n    return 1", "function definition"),
    ("class C:\n    pass", "class definition"),
]


@pytest.mark.parametrize("code,label", ESCAPES, ids=[label for _, label in ESCAPES])
def test_escape_attempts_are_rejected(code, label, df):
    result = run(code, df)
    assert not result.ok, f"{label} was NOT blocked"
    assert result.output.startswith("Rejected:"), result.output


LEGITIMATE = [
    ("print(df['sales'].sum())", "800"),
    ("print(df['sales'].mean())", "200.0"),
    ("print(len(df))", "4"),
    ("result = int(df['units'].max())", "30"),
]


@pytest.mark.parametrize("code,expected", LEGITIMATE)
def test_legitimate_analysis_runs(code, expected, df):
    result = run(code, df)
    assert result.ok, result.output
    assert expected in result.output


def test_groupby_aggregation(df):
    result = run("print(df.groupby('region')['sales'].sum())", df)
    assert result.ok, result.output
    assert "250" in result.output and "550" in result.output


def test_boolean_mask_filtering_is_the_supported_alternative_to_query(df):
    result = run("print(df[df.sales > 150].shape[0])", df)
    assert result.ok, result.output
    assert "2" in result.output


def test_list_comprehension_can_see_df(df):
    """
    Regression test for the two-dict exec bug. With separate globals and locals
    mappings, a comprehension resolves free variables in globals and cannot see
    `df`, so this raised NameError.
    """
    result = run("print(sum([x for x in df.units]))", df)
    assert result.ok, result.output
    assert "75" in result.output


def test_runtime_error_is_reported_not_raised(df):
    result = run("print(df['nonexistent_column'])", df)
    assert not result.ok
    assert "Error running code" in result.output


def test_syntax_error_is_reported(df):
    result = run("print(", df)
    assert not result.ok
    assert "syntax error" in result.output.lower()


def test_timeout_is_enforced(df):
    result = run("x = 0\nwhile True:\n    x += 1", df, timeout_seconds=1)
    assert not result.ok
    assert "timed out" in result.output.lower()


def test_output_is_truncated(df):
    result = run("print('a' * 100000)", df)
    assert result.ok
    assert len(result.output) < 5000
    assert "truncated" in result.output


def test_validate_raises_for_unsafe_code():
    with pytest.raises(SandboxError):
        validate("import os")
    validate("print(df.head())")  # must not raise
