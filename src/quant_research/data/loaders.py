"""Data loaders: synthetic (offline/tests), csv, and yfinance (real data).

Real-data mode is first-class; yfinance needs no credentials.  Provider
credentials, when needed in the future, must come from environment variables,
never from source code.  All loaders return the normalized long OHLCV schema
validated by data.validation.validate_ohlcv.  Nothing is forward-filled.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from ..config import DataConfig
from .schemas import DataValidationError, OHLCV_COLUMNS
from .validation import expected_sessions, validate_ohlcv


def generate_synthetic_ohlcv(
    assets: List[str],
    start: str = "2012-01-01",
    end: str = "2026-01-01",
    seed: int = 42,
) -> pd.DataFrame:
    """Deterministic synthetic OHLCV in the normalized long schema (UTC).

    Includes deterministic crisis/regime components so stress tests are
    meaningful.  Bars are generated on a real US exchange calendar (weekends
    and US market holidays excluded), timezone-aware UTC timestamps.  Output is
    complete (no genuine missing sessions).
    """
    rng = np.random.default_rng(seed)
    idx = expected_sessions(
        pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), "US"
    )
    idx = idx[(idx >= pd.Timestamp(start, tz="UTC")) & (idx < pd.Timestamp(end, tz="UTC"))]
    common = rng.normal(0, 0.0004, len(idx))
    drifts = np.linspace(0.0001, 0.0004, len(assets))
    frames = []
    for i, asset in enumerate(assets):
        eps = rng.normal(0, 0.010 + 0.001 * i, len(idx))
        latent = common + eps + drifts[i]
        shock = np.zeros(len(idx))
        for a, b, mag in [
            ("2020-02-01", "2020-04-01", -0.0025),
            ("2022-01-01", "2022-10-01", -0.0010),
            ("2024-01-01", "2024-04-01", 0.0007),
        ]:
            mask = (idx >= pd.Timestamp(a, tz="UTC")) & (idx < pd.Timestamp(b, tz="UTC"))
            shock[mask] = mag
        ret = latent + shock
        close = 100.0 * np.exp(np.cumsum(ret))
        open_ = np.roll(close, 1)
        open_[0] = close[0]
        spread = np.abs(rng.normal(0, 0.002, len(idx)))
        high = np.maximum(open_, close) * (1 + spread)
        low = np.minimum(open_, close) * (1 - spread)
        base_vol = 1_000_000 * (1 + 0.25 * np.abs(ret) / max(np.std(ret), 1e-8))
        vol = base_vol * rng.lognormal(0, 0.20, len(idx))
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": idx,
                    "symbol": asset,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": vol,
                }
            )
        )
    return pd.concat(frames, ignore_index=True).sort_values(
        ["timestamp", "symbol"], kind="stable").reset_index(drop=True)


def _long_from_wide_csv(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert a wide CSV (timestamp, Close_<SYM>, Volume_<SYM>) to long schema."""
    if "timestamp" not in raw.columns:
        raw = raw.rename(columns={raw.columns[0]: "timestamp"})
    close_cols = [c for c in raw.columns if c.startswith("Close_")]
    if not close_cols:
        raise DataValidationError("CSV must contain Close_<ASSET> columns")
    vol_cols = [c for c in raw.columns if c.startswith("Volume_")]
    frames = []
    for cc in close_cols:
        sym = cc.replace("Close_", "")
        vc = f"Volume_{sym}"
        if vc not in raw.columns:
            raise DataValidationError(f"CSV missing volume column '{vc}' for symbol {sym}")
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": raw["timestamp"],
                    "symbol": sym,
                    "open": raw[cc],
                    "high": raw[cc],
                    "low": raw[cc],
                    "close": raw[cc],
                    "volume": raw[vc],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def load_csv_ohlcv(csv_path: str, assets: List[str]) -> pd.DataFrame:
    """Load OHLCV from a CSV file (long normalized schema, or wide format)."""
    raw = pd.read_csv(csv_path)
    if set(OHLCV_COLUMNS).issubset(raw.columns):
        long = raw
    else:
        long = _long_from_wide_csv(raw)
    long = long[long["symbol"].isin(assets)].copy()
    return validate_ohlcv(long)


def load_yfinance_ohlcv(assets: List[str], start: str, end: str) -> pd.DataFrame:
    """Download real daily OHLCV via yfinance and normalize to the long schema.

    Raises DataValidationError when the provider returns nothing usable.
    Documented corporate-action basis: auto_adjust=True, i.e. split/dividend
    adjusted OHLC so historical returns are tradable-return-consistent.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise DataValidationError(
            "yfinance is not installed; install with the [market] extra"
        ) from exc
    raw = yf.download(
        sorted(set(assets)),
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    if raw is None or len(raw) == 0:
        raise DataValidationError("yfinance returned no data (check connectivity/universe)")
    frames = []
    if isinstance(raw.columns, pd.MultiIndex):
        level_syms = set(raw.columns.get_level_values(-1)) | set(raw.columns.get_level_values(0))
        for sym in sorted(set(assets)):
            if sym not in level_syms:
                continue
            # group_by="column" gives (field, ticker); xs(level=-1) handles
            # either layout robustly
            try:
                sub = raw.xs(sym, axis=1, level=-1)
            except KeyError:
                try:
                    sub = raw.xs(sym, axis=1, level=0)
                except KeyError:
                    continue
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            sub = sub.reset_index()
            date_col = "Date" if "Date" in sub.columns else sub.columns[0]
            frames.append(_frame_from_provider(sym, sub, date_col))
    else:
        raw = raw.dropna(subset=["Close"]).reset_index()
        date_col = "Date" if "Date" in raw.columns else raw.columns[0]
        frames.append(_frame_from_provider(assets[0], raw, date_col))
    if not frames:
        raise DataValidationError("yfinance normalization produced no rows")
    long = pd.concat(frames, ignore_index=True).sort_values(
        ["timestamp", "symbol"], kind="stable").reset_index(drop=True)
    return validate_ohlcv(long)


def _frame_from_provider(symbol: str, sub: pd.DataFrame, date_col: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(sub[date_col], utc=True),
            "symbol": symbol,
            "open": sub["Open"].to_numpy(dtype="float64"),
            "high": sub["High"].to_numpy(dtype="float64"),
            "low": sub["Low"].to_numpy(dtype="float64"),
            "close": sub["Close"].to_numpy(dtype="float64"),
            "volume": sub["Volume"].to_numpy(dtype="float64"),
        }
    )


def load_market_data(cfg: DataConfig) -> Tuple[pd.DataFrame, dict]:
    """Load validated OHLCV for the configured universe.

    Returns (ohlcv_long, metadata).  Metadata records mode, universe, period,
    dataset hash, and any documented assumptions.
    """
    if cfg.mode == "synthetic":
        ohlcv = generate_synthetic_ohlcv(cfg.assets, cfg.start, cfg.end, seed=42)
        assumption = "synthetic data; NOT market evidence"
    elif cfg.mode == "csv":
        ohlcv = load_csv_ohlcv(cfg.csv_path, cfg.assets)  # type: ignore[arg-type]
        assumption = "user-provided csv; corporate-action basis is the user's responsibility"
    elif cfg.mode == "yfinance":
        ohlcv = load_yfinance_ohlcv(cfg.assets, cfg.start, cfg.end)
        assumption = (
            "yfinance daily bars, auto_adjust=True: split/dividend-adjusted OHLC "
            "(documented corporate-action basis)"
        )
    else:  # pragma: no cover - DataConfig validates modes
        raise DataValidationError(f"unsupported data mode {cfg.mode!r}")

    ohlcv = ohlcv[ohlcv["timestamp"] >= pd.Timestamp(cfg.start, tz="UTC")]
    ohlcv = ohlcv[ohlcv["timestamp"] < pd.Timestamp(cfg.end, tz="UTC")]
    ohlcv = ohlcv.sort_values(["timestamp", "symbol"], kind="stable").reset_index(drop=True)
    ohlcv = validate_ohlcv(ohlcv)

    from .snapshots import dataset_hash

    meta = {
        "mode": cfg.mode,
        "assets": list(cfg.assets),
        "target": cfg.target,
        "start": cfg.start,
        "end": cfg.end,
        "frequency": cfg.frequency,
        "dataset_hash": dataset_hash(ohlcv),
        "assumptions": assumption,
    }
    return ohlcv, meta


def to_panels(ohlcv: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Convert validated long OHLCV to (close_panel, volume_panel) wide frames."""
    close = ohlcv.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    volume = ohlcv.pivot(index="timestamp", columns="symbol", values="volume").sort_index()
    return close, volume
