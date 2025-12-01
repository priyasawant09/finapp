# finance.py
from typing import Dict, List, Optional
import math
import numpy as np
import pandas as pd
import yfinance as yf


# ---------- Small helpers ----------

def _clean_scalar(x: Optional[float]) -> Optional[float]:
    """
    Convert x to a plain Python float, or return None if it is NaN/inf/non-numeric.
    This guarantees JSON-safe numeric values.
    """
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _is_valid_number(x) -> bool:
    """
    True if x is a normal finite number (no NaN/inf) that can be cast to float.
    """
    return _clean_scalar(x) is not None


# ---------- yfinance wrappers ----------

def fetch_price_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    """
    Always returns a DataFrame. If yfinance gives only NaNs or fails, returns an empty DataFrame.
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period)
        if not isinstance(hist, pd.DataFrame) or hist.empty:
            return pd.DataFrame()
        # If all values are NaN, treat as empty
        if pd.isna(hist).all().all():
            return pd.DataFrame()
        return hist
    except Exception:
        return pd.DataFrame()


def fetch_fundamentals(ticker: str) -> Dict[str, pd.DataFrame]:
    """
    Fetch income statement, balance sheet, cash flow and info as DataFrames.
    DataFrames may be empty, but never None.
    """
    tk = yf.Ticker(ticker)

    income = getattr(tk, "income_stmt", None)
    if income is None or not isinstance(income, pd.DataFrame) or income.empty:
        income = tk.financials

    balance = getattr(tk, "balance_sheet", None)
    if balance is None or not isinstance(balance, pd.DataFrame) or balance.empty:
        balance = tk.balance_sheet

    cashflow = getattr(tk, "cashflow", None)
    if cashflow is None or not isinstance(cashflow, pd.DataFrame) or cashflow.empty:
        cashflow = tk.cashflow

    info = {}
    try:
        info = tk.info
    except Exception:
        info = {}

    for df in (income, balance, cashflow):
        if isinstance(df, pd.DataFrame) and not df.empty:
            df.index = df.index.astype(str)

    info_df = (
        pd.DataFrame.from_dict(info, orient="index", columns=["value"])
        if isinstance(info, dict)
        else pd.DataFrame()
    )

    return {
        "income": income if isinstance(income, pd.DataFrame) else pd.DataFrame(),
        "balance": balance if isinstance(balance, pd.DataFrame) else pd.DataFrame(),
        "cashflow": cashflow if isinstance(cashflow, pd.DataFrame) else pd.DataFrame(),
        "info": info_df,
    }


# ---------- Statement item getter ----------

def _get_item(df: pd.DataFrame, candidates: List[str]) -> Optional[float]:
    """
    Safely extract a scalar number from a financial statement row by label.
    Handles:
      - exact label
      - case-insensitive contains match
      - numpy arrays / Series in the cell
    Always returns a clean float or None.
    """
    if df is None or df.empty:
        return None

    def _extract_scalar(val):
        # Handle arrays / series / lists
        if isinstance(val, (np.ndarray, pd.Series, list, tuple)):
            arr = np.array(val).flatten()
            # All NA? -> None
            if arr.size == 0 or np.all(pd.isna(arr)):
                return None
            # Take first non-NA element
            mask = ~pd.isna(arr)
            if not mask.any():
                return None
            val = arr[mask][0]
        return _clean_scalar(val)

    for label in candidates:
        # 1. Exact label
        if label in df.index:
            cell = df.loc[label].iloc[0]
            scalar = _extract_scalar(cell)
            if scalar is not None:
                return scalar

        # 2. Fuzzy, case-insensitive contains
        matches = [idx for idx in df.index if label.lower() in idx.lower()]
        if matches:
            cell = df.loc[matches[0]].iloc[0]
            scalar = _extract_scalar(cell)
            if scalar is not None:
                return scalar

    return None


# ---------- Ratios ----------

def compute_ratios(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    price_hist: pd.DataFrame,
) -> Dict[str, Optional[float]]:
    """
    Compute basic financial ratios. Output dict is guaranteed JSON-safe:
      - Only None or normal floats (no NaN/inf, no numpy types).
    """
    metrics: Dict[str, Optional[float]] = {
        "revenue": None,
        "net_income": None,
        "net_margin": None,
        "roe": None,
        "debt_to_equity": None,
        "current_ratio": None,
        "one_year_return": None,
        "price": None,
    }

    # ----- Income statement -----
    revenue = _get_item(income, ["Total Revenue", "TotalRevenue", "Revenue"])
    net_income = _get_item(
        income, ["Net Income", "NetIncome", "Net Income Common Stockholders"]
    )

    # ----- Balance sheet -----
    total_equity = _get_item(
        balance, ["Total Stockholder Equity", "Total Equity", "TotalEquity"]
    )
    total_debt = _get_item(
        balance, ["Total Debt", "TotalDebt", "Long Term Debt", "LongTermDebt"]
    )
    current_assets = _get_item(
        balance, ["Total Current Assets", "Current Assets", "CurrentAssets"]
    )
    current_liab = _get_item(
        balance,
        ["Total Current Liabilities", "Current Liabilities", "CurrentLiabilities"],
    )

    # Store raw numbers (already cleaned or None)
    metrics["revenue"] = revenue
    metrics["net_income"] = net_income

    # Net margin
    if _is_valid_number(revenue) and _is_valid_number(net_income) and revenue != 0:
        metrics["net_margin"] = _clean_scalar(net_income / revenue)

    # ROE
    if _is_valid_number(total_equity) and _is_valid_number(net_income) and total_equity != 0:
        metrics["roe"] = _clean_scalar(net_income / total_equity)

    # Debt/Equity
    if _is_valid_number(total_equity) and _is_valid_number(total_debt) and total_equity != 0:
        metrics["debt_to_equity"] = _clean_scalar(total_debt / total_equity)

    # Current ratio
    if _is_valid_number(current_assets) and _is_valid_number(current_liab) and current_liab != 0:
        metrics["current_ratio"] = _clean_scalar(current_assets / current_liab)

    # ----- Price & returns -----
    if isinstance(price_hist, pd.DataFrame) and not price_hist.empty:
        try:
            price_val = price_hist["Close"].iloc[-1]
            metrics["price"] = _clean_scalar(price_val)
        except Exception:
            metrics["price"] = None

        if len(price_hist) > 252:
            try:
                px_now = float(price_hist["Close"].iloc[-1])
                px_1y = float(price_hist["Close"].iloc[-252])
                if px_1y != 0:
                    metrics["one_year_return"] = _clean_scalar(px_now / px_1y - 1.0)
            except Exception:
                metrics["one_year_return"] = None

    # Final safety pass (not strictly needed, but cheap)
    for k, v in list(metrics.items()):
        metrics[k] = _clean_scalar(v)

    return metrics


# ---------- Statements to JSON-safe dict ----------

def dataframe_to_statement(df: pd.DataFrame, max_cols: int = 3):
    """
    Convert a wide financial DataFrame (years as columns) into a JSON-friendly dict.
    Ensures:
      - NaN/inf -> None
      - numpy scalars -> Python floats
      - other types -> str or None
    """
    if df is None or df.empty:
        return None

    cols = list(df.columns[:max_cols])
    sub = df[cols]

    clean_data: List[List[Optional[float]]] = []

    for _, row in sub.iterrows():
        clean_row: List[Optional[float]] = []
        for v in row.tolist():
            # Missing value?
            if pd.isna(v):
                clean_row.append(None)
                continue

            # Numeric?
            if isinstance(v, (int, float, np.integer, np.floating)):
                clean_row.append(_clean_scalar(v))
                continue

            # Numpy array / list / Series: take first scalar value if possible
            if isinstance(v, (np.ndarray, pd.Series, list, tuple)):
                arr = np.array(v).flatten()
                if arr.size == 0 or np.all(pd.isna(arr)):
                    clean_row.append(None)
                else:
                    clean_row.append(_clean_scalar(arr[0]))
                continue

            # Fallback: string representation (JSON-safe)
            clean_row.append(str(v))

        clean_data.append(clean_row)

    return {
        "columns": [str(c) for c in cols],
        "index": [str(i) for i in sub.index],
        "data": clean_data,
    }
