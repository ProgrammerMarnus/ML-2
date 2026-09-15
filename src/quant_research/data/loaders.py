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
from .schemas import DataValidationError, DataQualityWarning, OHLCV_COLUMNS
from .calendar import library_version as calendar_library_version
from .validation import expected_sessions, validate_ohlcv


def generate_synthetic_ohlcv(
    assets: List[str],
    start: str = "2012-01-01",
    end: str = "2026-01-01",
    seed: int = 42,
    exchange_calendar: str = "XNYS",
) -> pd.DataFrame:
    """Deterministic synthetic OHLCV in the normalized long schema (UTC).

    Includes deterministic crisis/regime components so stress tests are
    meaningful. Bars are generated on the configured exchange calendar,
    timezone-aware UTC timestamps. Output is complete (no genuine missing
    sessions).
    """
    rng = np.random.default_rng(seed)
    idx = expected_sessions(
        pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), exchange_calendar
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
    """Convert a wide CSV (timestamp, Close_<SYM>, Volume_<SYM>) to long schema.

    Wide CSVs typically contain only close and volume (no measured open/high/low).
    The returned long OHLCV rows have open/high/low set equal to close for schema
    compatibility, with ``_synthetic_range=True`` to mark that the intraday range
    is NOT measured.  Downstream range-dependent features (e.g. Parkinson
    volatility) must check ``_synthetic_range`` before consuming OHLC.
    """
    if "timestamp" not in raw.columns:
        raw = raw.rename(columns={raw.columns[0]: "timestamp"})
    # E18: reject timezone-naive CSV timestamps so forex/local-time inputs can
    # never be silently shifted into the wrong session (same rule as PIT
    # events: tz must be explicit).
    _ts_check = pd.to_datetime(raw["timestamp"], errors="coerce")
    if _ts_check.isna().any():
        raise DataValidationError("CSV contains unparseable timestamps")
    if _ts_check.apply(lambda t: t.tzinfo is None).any():
        raise DataValidationError(
            "CSV contains timezone-naive timestamps; timestamps must carry "
            "an explicit timezone so UTC conversion can never move bars"
        )
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
                    "_synthetic_range": True,
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
    return _clean_provider_ohlc(long)


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


def _clean_provider_ohlc(long: pd.DataFrame) -> pd.DataFrame:
    """yfinance adapter-specific OHLC containment repair (documented).

    yfinance occasionally emits a close/open a few bps outside [low, high]
    (provider rounding artifact).  The shared, strict validator still rejects
    such bars everywhere else; here we clip ONLY tiny violations back into the
    band and surface a DataQualityWarning.  Any violation beyond the tolerance
    band fails loudly rather than being repaired.
    """
    tol = 0.005  # 0.5% band - beyond this treat as corruption
    ll, hh = long["low"], long["high"]
    oc = long["close"], long["open"]
    big = (
        (oc[0] < ll * (1 - tol)) | (oc[0] > hh * (1 + tol))
        | (oc[1] < ll * (1 - tol)) | (oc[1] > hh * (1 + tol))
    )
    if big.any():
        raise DataValidationError(
            f"yfinance rows violate OHLC containment beyond {tol * 100:.1f}% "
            f"tolerance ({int(big.sum())} rows); refusing to repair large disagreements"
        )
    repair = (oc[0] < ll) | (oc[0] > hh) | (oc[1] < ll) | (oc[1] > hh)
    if repair.any():
        long.loc[repair, "close"] = oc[0].clip(lower=ll, upper=hh)
        long.loc[repair, "open"] = oc[1].clip(lower=ll, upper=hh)
        import warnings
        warnings.warn(
            f"Clipped {int(repair.sum())} yfinance OHLC containment violation(s) "
            f"into [low, high] (provider rounding artifact; documented repair)",
            DataQualityWarning,
        )
    return validate_ohlcv(long)


def load_market_data(cfg: DataConfig) -> Tuple[pd.DataFrame, dict]:
    """Load validated OHLCV for the configured universe.

    Returns (ohlcv_long, metadata).  Metadata records mode, universe, period,
    dataset hash, and any documented assumptions.

    B05 FIX: Validate that all requested assets are present in the loaded data
    and that the data covers the requested period. Missing assets and truncated
    history are now explicitly detected.

    For ``mode='h002'``, redirects to the H-002 universe loader.
    """
    if cfg.mode == "h002":
        from .h002_universe import load_h002_universe
        ohlcv, vix, sector_map, meta = load_h002_universe(
            cfg.start, cfg.end,
            universe_path=getattr(cfg, "h002_universe_path", None),
            max_tickers=getattr(cfg, "h002_max_tickers", None),
        )
        # H-002 returns (ohlcv, vix, sector_map, meta) but load_market_data
        # expects (ohlcv, metadata).  Flatten the extra outputs into metadata.
        meta["vix_available"] = not vix.empty
        meta["vix_n_obs"] = len(vix)
        meta["sector_map_n"] = len(sector_map)
        # JSON-safe extras consumed downstream by the H-002 pipeline.  The VIX
        # Series is deliberately not embedded here (it would be repr-coerced and
        # inflate the snapshot metadata).
        meta["sector_map"] = sector_map
        return ohlcv, meta
    elif cfg.mode == "synthetic":
        ohlcv = generate_synthetic_ohlcv(
            cfg.assets, cfg.start, cfg.end, seed=42,
            exchange_calendar=cfg.exchange_calendar,
        )
        assumption = "synthetic data; NOT market evidence"
    elif cfg.mode == "csv":
        ohlcv = load_csv_ohlcv(cfg.csv_path, cfg.assets)  # type: ignore[arg-type]
        assumption = "user-provided csv; corporate-action basis is the user's responsibility"
    elif cfg.mode in {"yfinance", "h003", "h006"}:
        ohlcv = load_yfinance_ohlcv(cfg.assets, cfg.start, cfg.end)
        assumption = (
            "yfinance daily bars, auto_adjust=True: split/dividend-adjusted OHLC "
            "(documented corporate-action basis)"
            + ("; H-003-R1 amended 17-ETF plus VIX-spot contract"
               if cfg.mode == "h003" else "")
            + ("; H-006 17-ETF factor mean reversion universe"
               if cfg.mode == "h006" else "")
        )
    else:  # pragma: no cover - DataConfig validates modes
        raise DataValidationError(f"unsupported data mode {cfg.mode!r}")

    ohlcv = ohlcv[ohlcv["timestamp"] >= pd.Timestamp(cfg.start, tz="UTC")]
    ohlcv = ohlcv[ohlcv["timestamp"] < pd.Timestamp(cfg.end, tz="UTC")]
    ohlcv = ohlcv.sort_values(["timestamp", "symbol"], kind="stable").reset_index(drop=True)
    ohlcv = validate_ohlcv(ohlcv)

    # B05: Validate requested universe against realized data
    observed_symbols = set(ohlcv["symbol"].unique())
    requested_symbols = set(cfg.assets)
    missing_symbols = requested_symbols - observed_symbols
    if missing_symbols:
        raise DataValidationError(
            f"requested assets not found in data: {sorted(missing_symbols)}. "
            f"Available assets: {sorted(observed_symbols)}"
        )

    # B05: Validate data covers requested period (check first/last dates per symbol)
    # For synthetic data, the start date may be before the first trading day, which is
    # expected. For real data, we check more strictly.
    from .validation import expected_sessions
    start_ts = pd.Timestamp(cfg.start, tz="UTC")
    end_ts = pd.Timestamp(cfg.end, tz="UTC")

    for symbol in cfg.assets:
        sym_data = ohlcv[ohlcv["symbol"] == symbol]
        if len(sym_data) == 0:
            continue  # Already caught by missing_symbols check
        first_date = sym_data["timestamp"].min()
        last_date = sym_data["timestamp"].max()
        # C02: Compare requested coverage against expected exchange sessions,
        # not against raw calendar-day tolerance.  A 1-day tolerance rejects
        # complete data when the interval starts/ends around weekends or
        # exchange holidays (e.g. requested 2012-01-01, first SPY bar 2012-01-03
        # is the first NYSE session after New Year's weekend + holiday).
        #
        # For synthetic data the start may precede the first trading day by design
        # (expected_sessions is used to generate bars).  For real yfinance/CSV
        # data we require the observed data to cover the expected sessions inside
        # [start, end), with explicit exceptions for known listing-history gaps.
        if cfg.mode == "synthetic":
            # Synthetic: the first bar must be the first expected session on/after
            # the requested start (data generation uses expected_sessions + exclusive
            # end cut).  Verify the leading edge; the trailing edge is bounded by the
            # end-ts exclusive cut applied above.
            expected_first = expected_sessions(start_ts, end_ts, exchange=cfg.exchange_calendar)[0]
            if first_date != expected_first:
                raise DataValidationError(
                    f"asset {symbol}: synthetic data starts {first_date.date()} but "
                    f"expected first session {expected_first.date()} for the requested "
                    f"start; data generation may have used a different calendar"
                )
        else:
            # Real data: the first observed session should be the first expected
            # session on/after start, and the last should be the last expected
            # session strictly before end (the data is cut with < end_ts above).
            expected_all = expected_sessions(start_ts, end_ts, exchange=cfg.exchange_calendar)
            if len(expected_all) == 0:
                raise DataValidationError(
                    f"asset {symbol}: no expected exchange sessions between "
                    f"{start_ts.date()} and {end_ts.date()}; check the requested period"
                )
            expected_first = expected_all[0]
            # The last expected session for an EXCLUSIVE end: if end_ts is itself
            # a trading day it is excluded by the data cut, so the last expected
            # observed bar is the second-to-last session.
            if expected_all[-1].date() == end_ts.date():
                expected_last = expected_all[-2] if len(expected_all) >= 2 else expected_all[-1]
            else:
                expected_last = expected_all[-1]
            if first_date != expected_first:
                # Could be a listing-date gap (asset listed after requested start).
                # Count sessions strictly between start and the first observed bar;
                # a single missing session can be a listing-date gap, more than one
                # indicates truncation or a non-existent asset history.
                missing_leading = expected_sessions(start_ts, first_date, exchange=cfg.exchange_calendar)
                # Exclude the first observed bar itself from the missing count
                n_missing = len(missing_leading) - 1 if len(missing_leading) > 0 else 0
                if n_missing > 0:  # D08 fix: reject ANY missing boundary session
                    raise DataValidationError(
                        f"asset {symbol}: data starts {first_date.date()} but requested "
                        f"start is {start_ts.date()}; expected first session "
                        f"{expected_first.date()}; {n_missing} leading sessions "
                        f"missing — asset may have been listed after the requested start "
                        f"or data is truncated"
                    )
            if last_date != expected_last:
                n_missing = len(expected_sessions(last_date, end_ts, exchange=cfg.exchange_calendar)) - 1 \
                    if last_date < end_ts else 0
                if n_missing > 0:  # D08 fix: reject ANY missing boundary session
                    raise DataValidationError(
                        f"asset {symbol}: data ends {last_date.date()} but requested end "
                        f"is {end_ts.date()}; expected last session {expected_last.date()}; "
                        f"{n_missing} trailing sessions missing — data is truncated"
                    )
        # For all modes, verify we have a reasonable amount of data
        expected_min = len(expected_sessions(start_ts, end_ts, exchange=cfg.exchange_calendar)) // 10
        if len(sym_data) < expected_min:
            raise DataValidationError(
                f"asset {symbol}: only {len(sym_data)} observations, expected at least "
                f"{expected_min} for the requested period"
            )

    from .snapshots import dataset_hash

    meta = {
        "mode": cfg.mode,
        "assets": list(cfg.assets),
        "target": cfg.target,
        "start": cfg.start,
        "end": cfg.end,
        "frequency": cfg.frequency,
        "exchange_calendar": cfg.exchange_calendar,
        "exchange_calendar_library_version": calendar_library_version(),
        "dataset_hash": dataset_hash(ohlcv),
        "assumptions": assumption,
        "n_observed_symbols": len(observed_symbols),
        "n_requested_symbols": len(requested_symbols),
    }
    return ohlcv, meta


def to_panels(ohlcv: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Convert validated long OHLCV to (close_panel, volume_panel) wide frames."""
    close = ohlcv.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    volume = ohlcv.pivot(index="timestamp", columns="symbol", values="volume").sort_index()
    return close, volume


def to_price_panels(ohlcv: pd.DataFrame):
    """Convert validated long OHLCV to wide (open, high, low, close, volume) frames.

    E18: OHLC provenance propagates.  When the long frame carries
    ``_synthetic_range`` (close-only CSV imports fabricate
    open==high==low==close), every derived OHLC panel is tagged with the
    ``_synthetic_range`` DataFrame attribute so range-dependent consumers
    (signal extensions, Parkinson) can reject fabricated inputs instead of
    silently treating them as measured ranges.
    """
    open_ = ohlcv.pivot(index="timestamp", columns="symbol", values="open").sort_index()
    high = ohlcv.pivot(index="timestamp", columns="symbol", values="high").sort_index()
    low = ohlcv.pivot(index="timestamp", columns="symbol", values="low").sort_index()
    close = ohlcv.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    volume = ohlcv.pivot(index="timestamp", columns="symbol", values="volume").sort_index()
    if "_synthetic_range" in ohlcv.columns and bool(ohlcv["_synthetic_range"].any()):
        for _panel in (open_, high, low):
            try:
                _panel._synthetic_range = True
            except Exception:
                pass
    return open_, high, low, close, volume
