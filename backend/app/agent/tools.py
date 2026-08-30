"""
Tools the LangGraph agent can call.

The important design point is which arguments the *model* supplies and which the
*runtime* supplies. Previously `run_pandas_code` declared `dataframe_json` as a
model-supplied argument while the model was only ever told
"[spreadsheet available: yes]" — so the only way to call it correctly was to
hallucinate the entire dataset as a JSON string. The spreadsheet feature could
never have worked.

Now `workspace_id` and the spreadsheet location come from graph state via
`InjectedState`. They are invisible to the model — not in the tool schema, not
something it can spoof — and the model supplies only `query` or `code`.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Optional

import pandas as pd
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.agent.sandbox import run as run_sandboxed
from app.config import get_settings
from app.services.hybrid_search import hybrid_search
from app.services.ingestion import get_dataframe

logger = logging.getLogger(__name__)
settings = get_settings()

_df_cache: dict[tuple[str, float], pd.DataFrame] = {}


def load_dataframe(path: str, file_type: str) -> pd.DataFrame:
    """Load a spreadsheet, cached on (path, mtime) so repeat questions are free."""
    key = (path, os.path.getmtime(path))
    if key not in _df_cache:
        _df_cache.clear()  # only ever keep the most recent one
        _df_cache[key] = get_dataframe(path, file_type)
    return _df_cache[key]


@tool
def search_documents(
    query: str,
    workspace_id: Annotated[str, InjectedState("workspace_id")],
) -> str:
    """Search the user's uploaded documents for relevant passages.

    Use this for any question about written content: reports, policies,
    descriptions, contracts, web pages. Pass a focused search query rather than
    the user's whole sentence.
    """
    chunks = hybrid_search(workspace_id, query, top_k=5)
    if not chunks:
        return "No relevant content found in the uploaded documents."

    formatted = "\n\n---\n\n".join(
        f"[Passage {i + 1}]\n{chunk}" for i, chunk in enumerate(chunks)
    )
    return f"Found {len(chunks)} relevant passages:\n\n{formatted}"


@tool
def run_pandas_code(
    code: str,
    spreadsheet_path: Annotated[Optional[str], InjectedState("spreadsheet_path")],
    spreadsheet_type: Annotated[Optional[str], InjectedState("spreadsheet_type")],
) -> str:
    """Run pandas code against the uploaded spreadsheet to compute a real answer.

    Use this for any question involving numbers, totals, averages, counts,
    comparisons or trends in a CSV/Excel file.

    The DataFrame is already loaded as `df` and `pd` is available. Do not read
    any file. Print the answer with print().

    Example:
        print(df.groupby('region')['sales'].sum().sort_values(ascending=False))
    """
    if not spreadsheet_path:
        return "No spreadsheet has been uploaded to this workspace."

    try:
        df = load_dataframe(spreadsheet_path, spreadsheet_type or "csv")
    except FileNotFoundError:
        return "The spreadsheet file is no longer available on the server."
    except Exception as exc:
        logger.warning("Could not load spreadsheet %s: %s", spreadsheet_path, exc)
        return f"Could not read the spreadsheet: {exc}"

    result = run_sandboxed(code, df, timeout_seconds=settings.pandas_timeout_seconds)
    return result.output


ALL_TOOLS = [search_documents, run_pandas_code]
