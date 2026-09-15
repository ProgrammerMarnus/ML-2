"""H-002 cross-sectional dollar-neutral portfolio construction.

DOCUMENTED DEVIATION FROM H-002 PREREGISTRATION:
The original H-002 preregistration specifies a cross-sectional, equal-weight,
dollar-neutral long/short portfolio with sector-neutral constraints. This
module implements that at the daily level using a static universe and the
liquidity_reversal feature signals.

Key deviations:
  - Universe is a static snapshot, not PIT Russell 3000 membership.
  - Signals come from the liquidity_reversal feature module (which uses
    return-signed volume as a proxy for the LIM, since we lack intraday
    trade classification).
  - Sector neutrality is approximate (uses the static GICS map).
  - No market-cap decile weighting (we don't have historical market cap).

The portfolio is constructed each day as:
  1. Compute the composite signal for each available stock (from features).
  2. Skip stocks with missing signal or insufficient history.
  3. Rank by signal; go long top decile, short bottom decile.
  4. Equal weight within each leg, dollar-neutral (long_sum == short_sum).
  5. Apply sector tilt correction: for each sector, net exposure capped.
  6. Apply position limits: max 2% per stock, max 10% net sector exposure.

Returns a weight matrix: rows = timestamps, columns = tickers.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

#: H-002 preregistered portfolio parameters (section 6.1).  Shared by the
#: pipeline and the robustness stresses so the evaluated book and the stressed
#: books are always built with identical rules.
H002_PREREG_PORTFOLIO_PARAMS = {
    "long_decile": 10,
    "short_decile": 10,
    "max_stock_weight": 0.02,
    "max_sector_net_exposure": 0.10,
    "max_sector_gross_exposure": 0.20,
    "gross_leverage": 1.0,
    "dollar_neutral": True,
    "min_members_per_day": 20,
    # H-002 predicts buying pressure reverses, so buy the low-signal names.
    "long_low_signal": True,
    # H-002 horizon: 1-5 day liquidity reversal -> hold the book for the
    # model's holding period rather than rebuilding it every session.
    "rebalance_bars": 5,
}


def construct_h002_portfolio(
    signal_panel: pd.DataFrame,
    sector_map: Dict[str, str],
    long_decile: int = 10,
    short_decile: int = 10,
    max_stock_weight: float = 0.02,
    max_sector_net_exposure: float = 0.10,
    max_sector_gross_exposure: float = 0.20,
    gross_leverage: float = 1.0,
    dollar_neutral: bool = True,
    min_members_per_day: int = 20,
    long_low_signal: bool = True,
    rebalance_bars: int = 1,
) -> pd.DataFrame:
    """Build the H-002 cross-sectional dollar-neutral portfolio.

    Parameters
    ----------
    signal_panel : pd.DataFrame
        Rows = timestamps (UTC), columns = tickers, values = composite signal.
    sector_map : Dict[str, str]
        ticker -> GICS sector name.
    long_decile, short_decile : int
        Size of the long / short leg expressed as a percentage of the
        available cross-section.  10 = one decile = top/bottom 10%
        (the H-002 preregistration's specification).  At least one name
        is always selected per leg.
    max_stock_weight : float
        Maximum absolute weight per stock (fraction of NAV).  H-002 prereg: 2%.
    max_sector_net_exposure : float
        Maximum net (long - short) exposure per sector as fraction of NAV.
        H-002 prereg: 10%.
    long_low_signal : bool
        When True the low-signal names are bought and the high-signal names are
        sold.  H-002 expects buying pressure (high composite) to reverse, so the
        pipeline uses ``long_low_signal=True``.
    max_sector_gross_exposure : float
        Maximum gross (|long| + |short|) exposure per sector as fraction of
        NAV.  H-002 prereg: 20%.
    gross_leverage : float
        Target |long| + |short| when the book is dollar-neutral.  H-002
        prereg: 1.0 (half to each leg).  A long-only book is left at 1.0
        rather than grossed up.  Cockpit defaults pass 2.0 for a fully
        invested two-sided book.
    dollar_neutral : bool
        When True, scale so abs(long_sum) == abs(short_sum).
    min_members_per_day : int
        Minimum number of stocks with valid signals to trade; otherwise flat.
    rebalance_bars : int
        Holding period in sessions.  The target book is recomputed every
        ``rebalance_bars`` sessions and HELD unchanged in between.  H-002's
        preregistration specifies a 1-5 day liquidity-reversal horizon, so the
        pipeline passes the model's ``hold_bars``.  The default of 1
        reconstructs the book every session (maximum turnover, maximum cost).
    long_low_signal : bool
        Direction of the trade.  H-002's preregistration specifies a negative
        relationship ("short high signal stocks, long low signal stocks"), i.e.
        the composite signal measures buying pressure that subsequently
        reverses.  True (default) implements that: long the lowest-signal
        names, short the highest-signal names.  False inverts it.

    Returns
    -------
    weights : pd.DataFrame
        Rows = timestamps, columns = tickers, values = portfolio weight.
        Zero weight for non-traded or missing stocks.  Long positive, short negative.
    """
    sig = signal_panel.copy().dropna(axis=1, how="all")
    weights_frames = []

    # Holding-period schedule: the book is recomputed only on rebalance
    # sessions and held unchanged in between (see ``rebalance_bars``).
    hold = max(1, int(rebalance_bars))
    rebalance_dates = set(sig.index[::hold])

    for ts, row in sig.iterrows():
        if ts not in rebalance_dates:
            continue
        valid = row.dropna()
        if len(valid) < min_members_per_day:
            w = pd.Series(0.0, index=sig.columns, name=ts)
            weights_frames.append(w)
            continue

        ranked = valid.rank(method="first", ascending=True)
        n = len(valid)

        # Leg sizes: the decile parameters are percentages of the cross-section
        # (10 = one decile = 10%), floored at one name and capped at the
        # available universe.
        leg_long = min(n, max(1, int(round(n * long_decile / 100.0))))
        leg_short = min(n, max(1, int(round(n * short_decile / 100.0))))

        if long_low_signal:
            # H-002 prereg: negative relationship -> short the highest-signal
            # (buying-pressure) names, long the lowest-signal names.
            long_mask = ranked <= leg_long
            short_mask = ranked > (n - leg_short)
        else:
            # Long: highest-ranked (largest signal) names
            long_mask = ranked > (n - leg_long)
            # Short: lowest-ranked names
            short_mask = ranked <= leg_short
        # A name is never simultaneously long and short.
        overlap = long_mask & short_mask
        if overlap.any():
            short_mask = short_mask & ~overlap

        raw = pd.Series(0.0, index=valid.index)
        raw[long_mask] = 1.0
        raw[short_mask] = -1.0

        if raw.abs().sum() == 0:
            w = pd.Series(0.0, index=sig.columns, name=ts)
            weights_frames.append(w)
            continue

        # Equal weight within each leg.  A dollar-neutral book splits the
        # target gross exposure across both legs; a one-sided book keeps the
        # full target rather than being left half-invested.
        n_long = int(long_mask.sum())
        n_short = int(short_mask.sum())
        if n_long > 0 and n_short > 0:
            leg_target = gross_leverage / 2.0
        elif n_long > 0 or n_short > 0:
            leg_target = gross_leverage
        else:
            leg_target = 0.0
        if n_long > 0:
            raw[long_mask] = leg_target / n_long
        if n_short > 0:
            raw[short_mask] = -leg_target / n_short

        # Max stock weight (H-002 prereg 6.1: 2% long or short).
        raw = raw.clip(-max_stock_weight, max_stock_weight)

        # Sector limits (H-002 prereg 6.1: 10% net, 20% gross per sector).
        sector_gross: Dict[str, float] = {}
        sector_net: Dict[str, float] = {}
        for ticker, weight in raw.items():
            if weight == 0:
                continue
            sector = sector_map.get(ticker, "Unknown")
            sector_gross[sector] = sector_gross.get(sector, 0.0) + abs(float(weight))
            sector_net[sector] = sector_net.get(sector, 0.0) + float(weight)

        for sector, gross_s in sector_gross.items():
            net_s = sector_net.get(sector, 0.0)
            scale = 1.0
            if gross_s > max_sector_gross_exposure:
                scale = min(scale, max_sector_gross_exposure / gross_s)
            if abs(net_s) > max_sector_net_exposure:
                scale = min(scale, max_sector_net_exposure / abs(net_s))
            if scale < 1.0:
                for ticker, weight in raw.items():
                    if weight != 0 and sector_map.get(ticker, "Unknown") == sector:
                        raw[ticker] *= scale

        raw = raw.clip(-max_stock_weight, max_stock_weight)

        # Re-establish exact dollar neutrality AFTER the caps.  Levelling the
        # smaller leg up could breach the position/sector caps, so the larger
        # leg is scaled down instead; the realized gross exposure is therefore
        # <= gross_leverage (documented, conservative).
        if dollar_neutral and n_long > 0 and n_short > 0:
            long_sum = float(raw[raw > 0].sum())
            short_sum = float(-raw[raw < 0].sum())
            if long_sum > 0 and short_sum > 0:
                scale = min(long_sum, short_sum) / max(long_sum, short_sum)
                if long_sum > short_sum:
                    raw[raw > 0] *= scale
                else:
                    raw[raw < 0] *= scale

        w = pd.Series(0.0, index=sig.columns, name=ts)
        w[raw.index] = raw.values
        weights_frames.append(w)

    if not weights_frames:  # pragma: no cover - defensive
        return pd.DataFrame(0.0, index=sig.index, columns=sig.columns)
    targets = pd.DataFrame(weights_frames)
    # Reindex the rebalance targets onto every session and carry the book
    # forward; sessions before the first rebalance are flat.
    held = targets.reindex(sig.index).ffill().fillna(0.0)
    return held.sort_index()