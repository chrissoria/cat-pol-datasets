from __future__ import annotations

from typing import Iterable

import pandas as pd


def validate_required_columns(df: pd.DataFrame, required_columns: Iterable[str]) -> list[str]:
    """Return missing required column names."""
    return [col for col in required_columns if col not in df.columns]


def validate_unique_key(df: pd.DataFrame, key_columns: list[str]) -> int:
    """Return the number of duplicate rows for the provided key columns."""
    if df.empty:
        return 0
    return int(df.duplicated(subset=key_columns).sum())


def validate_row_count_change(
    previous_df: pd.DataFrame,
    current_df: pd.DataFrame,
    min_ratio: float = 0.5,
) -> bool:
    """Guard against unexpected row-count collapses between pipeline stages."""
    if previous_df.empty:
        return True
    return len(current_df) >= len(previous_df) * min_ratio
