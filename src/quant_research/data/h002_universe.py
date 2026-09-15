"""H-002 real-data universe loader.

DOCUMENTED DEVIATION FROM H-002 PREREGISTRATION:
The original H-002 preregistration requires POINT-IN-TIME Russell 3000
membership, intraday trade classification, and market-cap data. This module
provides what is obtainable for free:

  - A static ticker list (data/universe_russell3000.csv) — NOT PIT membership.
  - Daily OHLCV via yfinance (auto_adjust=True) — NOT intraday classified trades.
  - VIX daily close for vol regime — NOT VIX futures term structure.
  - A simple GICS sector mapping (JSON, best-effort) — NOT a proper sector feed.

This is sufficient for an INITIAL real-data exploration of the H-002 economic
mechanism. Results are NOT valid preregistered H-002 evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from .loaders import load_yfinance_ohlcv, validate_ohlcv
from .schemas import DataValidationError


UNIVERSE_CSV = Path(__file__).resolve().parent.parent.parent.parent / "data" / "universe_russell3000.csv"
SECTOR_JSON = Path(__file__).resolve().parent / "h002_sectors.json"
VIX_TICKER = "^VIX"

# Disk cache for raw universe downloads.  A full H-002 run downloads ~30 batches
# from yfinance; without a cache every iteration re-pays that network cost.
# Batches are content-addressed by (tickers, start, end), so adding or removing
# tickers only invalidates the batches that actually changed.  Set
# ``QUANT_H002_CACHE=0`` to force a full refetch.
CACHE_DIR = (Path(__file__).resolve().parent.parent.parent.parent
             / "data_cache" / "h002_universe")


def _cache_enabled() -> bool:
    return os.environ.get("QUANT_H002_CACHE", "1").strip().lower() not in {
        "0", "false", "no",
    }


def _batch_cache_path(batch: List[str], start: str, end: str) -> Path:
    """Content-addressed cache file for one download batch."""
    payload = json.dumps(
        {"tickers": sorted(batch), "start": str(start), "end": str(end)},
        sort_keys=True,
    )
    key = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"batch_{key}.csv"


def _read_cached_batch(path: Path) -> pd.DataFrame | None:
    """Return the cached batch, or None when absent/unreadable/off-schema."""
    if path is None or not path.exists():
        return None
    try:
        df = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    required = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns) or df.empty:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _write_cached_batch(path: Path, df: pd.DataFrame) -> None:
    """Atomically persist a downloaded batch; caching never fails a run."""
    if path is None or df.empty:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except OSError:
        pass


def _read_universe_csv(universe_path: Path | None = None,
                       max_tickers: int | None = None) -> List[str]:
    """Read the static universe ticker list, returning deduplicated uppercase symbols.

    Parameters
    ----------
    universe_path : Path, optional
        Override for the universe CSV (defaults to ``data/universe_russell3000.csv``).
        Used by smoke tests to point at a small, fast-downloading subset.
    max_tickers : int, optional
        Keep only the first N symbols (by sorted order).  Smoke-test convenience;
        ``None`` uses the whole universe.
    """
    path = universe_path or UNIVERSE_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"Universe file not found at {path}. "
            f"Create data/universe_russell3000.csv with a 'symbol' column."
        )
    df = pd.read_csv(path)
    if "symbol" not in df.columns:
        raise ValueError(
            f"Universe CSV at {path} must have a 'symbol' column; "
            f"found columns: {list(df.columns)}"
        )
    syms = [str(s).strip().upper() for s in df["symbol"].dropna()]
    syms = sorted(set(s for s in syms if s and len(s) >= 1 and s != "SYMBOL"))
    if max_tickers is not None and max_tickers > 0:
        syms = syms[:max_tickers]
    return syms


def _load_sector_map() -> Dict[str, str]:
    """Load the static GICS sector map from JSON."""
    if not SECTOR_JSON.exists():
        return {}
    with open(SECTOR_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _sector_for(ticker: str, sector_map: Dict[str, str]) -> str:
    """Return the GICS sector for a ticker, or 'Unknown' if not in the map."""
    return sector_map.get(ticker.upper(), "Unknown")


def load_h002_universe(
    start: str = "2010-01-01",
    end: str = "2023-12-31",
    min_adl: float = 1_000_000.0,
    exclude_before_listing: bool = True,
    universe_path: Path | str | None = None,
    max_tickers: int | None = None,
) -> Tuple[pd.DataFrame, pd.Series, Dict[str, str], dict]:
    """Load H-002 universe data from yfinance.

    Parameters
    ----------
    start, end : str
        Date range (inclusive start, exclusive end per the loaders convention).
    min_adl : float
        Minimum average daily volume (shares) to include a ticker.  Matches
        the H-002 preregistration's $1M ADV filter (approximated by share count
        since we don't have historical market cap).
    exclude_before_listing : bool
        When True, trim each ticker's history to start at its first available
        session (no forward-fill of pre-listing zeros).  This is the correct
        causal behavior but reduces coverage for stocks listed after `start`.

    Returns
    -------
    ohlcv : pd.DataFrame
        Long OHLCV schema for all available universe tickers, validated.
    vix : pd.Series
        VIX daily close indexed by UTC timestamp.
    sector_map : Dict[str, str]
        ticker -> GICS sector name for every ticker in the OHLCV.
    meta : dict
        Coverage report: requested vs observed tickers, exclusions, assumptions.
    """
    requested = _read_universe_csv(
        Path(universe_path) if universe_path else None, max_tickers=max_tickers)
    universe_tickers = sorted(set(requested))
    
    # Download universe in batches to avoid yfinance failures on large universes.
    batch_size = 10
    batches = [universe_tickers[i:i+batch_size] for i in range(0, len(universe_tickers), batch_size)]
    all_frames = []
    missing_from_yf = []
    
    for batch in batches:
        cache_path = None
        if _cache_enabled():
            cache_path = _batch_cache_path(batch, start, end)
            cached = _read_cached_batch(cache_path)
            if cached is not None:
                all_frames.append(cached)
                continue
        try:
            batch_raw = load_yfinance_ohlcv(batch, start, end)
            if not batch_raw.empty:
                all_frames.append(batch_raw)
                if cache_path is not None:
                    _write_cached_batch(cache_path, batch_raw)
        except DataValidationError:
            for t in batch:
                missing_from_yf.append(t)
    
    if not all_frames:
        raise DataValidationError(
            f"Failed to download data for all {len(universe_tickers)} tickers. "
            f"Missing from yfinance: {missing_from_yf[:20]}"
        )
    
    raw = pd.concat(all_frames, ignore_index=True).sort_values(
        ["timestamp", "symbol"], kind="stable").reset_index(drop=True)
    
    # Pull VIX separately (^VIX is not handled well in multi-ticker downloads
    # and has zero volume which fails the standard OHLCV validator)
    vix_series = pd.Series(dtype=float, name="VIX")
    try:
        import yfinance as yf
        vix_raw = yf.download(
            VIX_TICKER, start=start, end=end,
            interval="1d", auto_adjust=True, progress=False,
        )
        if vix_raw is not None and not vix_raw.empty:
            # _clean_provider_ohlc would reject VIX (zero volume), so build
            # the long schema manually from the downloaded data
            if isinstance(vix_raw.columns, pd.MultiIndex):
                close_col = vix_raw.xs("Close", axis=1, level=0)
                # Handle both (field, ticker) and (ticker, field) layouts
                try:
                    close_series = close_col[VIX_TICKER]
                except KeyError:
                    close_series = close_col
            else:
                close_series = vix_raw["Close"]
            vix_ts = pd.to_datetime(close_series.index, utc=True)
            vix_series = pd.Series(
                close_series.to_numpy(dtype="float64"),
                index=vix_ts.sort_values(),
                name="VIX",
            )
            # Validate what we can: non-null, finite, sorted
            if vix_series.isna().any():
                vix_series = vix_series.dropna()
            if not np.isfinite(vix_series.to_numpy()).all():
                vix_series = vix_series[np.isfinite(vix_series.to_numpy())]
            vix_series = vix_series.sort_index()
    except Exception:
        pass  # VIX is optional; proceed without it
    
    universe_raw = raw.copy()

    if universe_raw.empty:
        raise DataValidationError("No universe tickers returned from yfinance")

    # Apply volume filter (approximate ADV filter using daily volume)
    if min_adl > 0:
        avg_vol = universe_raw.groupby("symbol")["volume"].transform("mean")
        universe_raw = universe_raw[avg_vol >= min_adl].copy()

    observed = sorted(universe_raw["symbol"].unique())
    missing = sorted(set(requested) - set(observed))

    # Trim to first listing date per ticker (causal)
    if exclude_before_listing:
        frames = []
        for sym in observed:
            sym_df = universe_raw[universe_raw["symbol"] == sym].sort_values("timestamp")
            frames.append(sym_df)
        universe_raw = pd.concat(frames, ignore_index=True).sort_values(
            ["timestamp", "symbol"], kind="stable").reset_index(drop=True)
    else:
        universe_raw = universe_raw.sort_values(
            ["timestamp", "symbol"], kind="stable").reset_index(drop=True)

    universe_raw = validate_ohlcv(universe_raw)

    sector_map_raw = _load_sector_map()
    sector_map = {sym: _sector_for(sym, sector_map_raw) for sym in observed}

    meta = {
        "requested_tickers": len(requested),
        "observed_tickers": len(observed),
        "missing_tickers": missing + missing_from_yf,
        "vix_available": not vix_series.empty,
        "vix_n_obs": len(vix_series),
        "date_range": (str(universe_raw["timestamp"].min()),
                       str(universe_raw["timestamp"].max())),
        "assumptions": (
            "Static universe snapshot (NOT PIT Russell 3000 membership); "
            "yfinance daily OHLCV auto_adjust=True; simple GICS sector map "
            "(NOT a proper sector feed); volume filter approximates ADV filter."
        ),
    }

    return universe_raw, vix_series, sector_map, meta