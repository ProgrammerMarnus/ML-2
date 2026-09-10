"""Tests for the strictly lagged Parkinson volatility feature.

Deterministic fixtures only: no network calls, no persistent artifact
writes.  Feature contract under test:

- strict 20-bar symbol-local lag (row i consumes bars i-20..i-1),
- exactly 20 warm-up NaN rows per symbol,
- no current-bar or future-bar contribution,
- exact index/row-order preservation with an unmodified input frame,
- strict input validation via DataValidationError/TypeError.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.data.schemas import DataValidationError
from quant_research.features import lagged_parkinson_volatility
from quant_research.features.parkinson import (
    ANNUALIZATION_FACTOR,
    FEATURE_NAME,
    PARKINSON_FEATURE_VERSION,
    WINDOW,
)
from quant_research.features.registry import (
    PRICE_VOLUME_SOURCE,
    information_feature_specs,
    price_volume_feature_specs,
    registry,
    registry_hash,
)


# --------------------------------------------------------------------------
# Deterministic fixture builders
# --------------------------------------------------------------------------

def make_frame(
    high,
    low,
    symbol="AAA",
    volume=None,
    index=None,
    start="2024-01-01",
    freq="D",
):
    """Deterministic long OHLCV frame; only high/low drive the feature."""
    high = np.asarray(high, dtype="float64")
    low = np.asarray(low, dtype="float64")
    n = high.shape[0]
    if volume is None:
        volume = np.full(n, 1000.0)
    volume = np.asarray(volume, dtype="float64")
    symbols = symbol if isinstance(symbol, (list, np.ndarray)) else np.full(n, symbol)
    timestamps = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": symbols,
            "open": low,
            "high": high,
            "low": low,
            "close": (high + low) / 2.0,
            "volume": volume,
        },
        index=index,
    )
    return frame


def varied_frame(n_rows, symbol="AAA", seed=7, **kwargs):
    """Random but deterministic positive high/low ranges."""
    rng = np.random.default_rng(seed)
    low = 1.0 + rng.uniform(0.0, 0.5, n_rows)
    high = low + rng.uniform(0.1, 1.0, n_rows)
    return make_frame(high, low, symbol=symbol, **kwargs)


# 1. Analytical value and exact warm-up -------------------------------------

def test_analytical_value_and_exact_warmup():
    n = 25
    frame = make_frame(np.full(n, 2.0), np.full(n, 1.0))
    out = lagged_parkinson_volatility(frame)
    assert out.iloc[:WINDOW].isna().all()
    assert out.iloc[WINDOW:].notna().all()
    # q = ln(2)^2 / (4 ln 2) = ln(2)/4; mean_20 of identical q, annualized
    expected = np.sqrt(ANNUALIZATION_FACTOR * np.log(2.0) / 4.0)
    np.testing.assert_allclose(
        out.iloc[WINDOW:].to_numpy(), expected, rtol=1e-12
    )


@pytest.mark.parametrize("n_rows", [1, 19, 20, 21])
def test_warmup_boundary_lengths(n_rows):
    frame = make_frame(np.full(n_rows, 2.0), np.full(n_rows, 1.0))
    out = lagged_parkinson_volatility(frame)
    assert out.shape == (n_rows,)
    assert int(out.isna().sum()) == min(n_rows, WINDOW)
    if n_rows > WINDOW:
        assert bool(pd.notna(out.iloc[WINDOW]))


# 2. Constant prices and zero volume ----------------------------------------

def test_constant_prices_and_zero_volume():
    n = 30
    frame = make_frame(
        np.full(n, 100.0), np.full(n, 100.0), volume=np.zeros(n)
    )
    out = lagged_parkinson_volatility(frame)  # all-zero volume is valid
    assert out.iloc[:WINDOW].isna().all()
    assert (out.iloc[WINDOW:] == 0.0).all()


def test_volume_values_do_not_change_feature():
    n = 30
    base = make_frame(np.full(n, 2.0), np.full(n, 1.0), volume=np.full(n, 10.0))
    alt = base.copy()
    alt["volume"] = np.linspace(0.0, 5.0e6, n)  # valid: finite, >= 0
    pd.testing.assert_series_equal(
        lagged_parkinson_volatility(base), lagged_parkinson_volatility(alt)
    )


# 3. Panel isolation and positional alignment -------------------------------

def test_panel_isolation_and_positional_alignment():
    rng = np.random.default_rng(3)
    n_a, n_b = 30, 10
    low_a = 1.0 + rng.uniform(0.0, 0.5, n_a)
    high_a = low_a + rng.uniform(0.1, 1.0, n_a)
    low_b = 1.0 + rng.uniform(0.0, 0.5, n_b)
    high_b = low_b + rng.uniform(0.5, 2.0, n_b)

    frames = {}
    for sym, high, low, n in (
        ("AAA", high_a, low_a, n_a),
        ("BBB", high_b, low_b, n_b),
    ):
        frames[sym] = make_frame(high, low, symbol=sym)
    a, b = frames["AAA"], frames["BBB"]

    # Interleave rows while preserving each symbol's chronology.
    parts = []
    for i in range(max(n_a, n_b)):
        if i < n_a:
            parts.append(a.iloc[[i]])
        if i < n_b:
            parts.append(b.iloc[[i]])
    panel = pd.concat(parts, ignore_index=True)
    panel_out = lagged_parkinson_volatility(panel).to_numpy()

    a_out = lagged_parkinson_volatility(a).to_numpy()
    b_out = lagged_parkinson_volatility(b).to_numpy()

    pos_a = np.flatnonzero((panel["symbol"] == "AAA").to_numpy())
    pos_b = np.flatnonzero((panel["symbol"] == "BBB").to_numpy())

    # Panel results match independent single-symbol results by row position.
    np.testing.assert_array_equal(panel_out[pos_a], a_out)
    np.testing.assert_array_equal(panel_out[pos_b], b_out)

    # Each symbol retains its own warm-up period.
    assert np.isnan(panel_out[pos_a][:WINDOW]).all()
    assert not np.isnan(panel_out[pos_a][WINDOW:]).any()
    assert np.isnan(panel_out[pos_b]).all()  # BBB has fewer than 21 bars


# 4. Current-bar exclusion ---------------------------------------------------

def test_current_bar_exclusion():
    n = 50
    j = 25
    base = varied_frame(n)
    v0 = lagged_parkinson_volatility(base).to_numpy()

    perturbed = base.copy()
    high_col = perturbed.columns.get_loc("high")
    low_col = perturbed.columns.get_loc("low")
    old_high = perturbed.iloc[j, high_col]
    perturbed.iloc[j, high_col] = (
        perturbed.iloc[j, low_col] + 2.0 * (old_high - perturbed.iloc[j, low_col])
    )
    v1 = lagged_parkinson_volatility(perturbed).to_numpy()

    # Through j: identical (row j uses bars j-20..j-1 only).
    np.testing.assert_array_equal(v0[: j + 1], v1[: j + 1])
    # j+1 changes and the whole affected window j+1..j+20 differs.
    assert v1[j + 1] != v0[j + 1]
    assert not np.array_equal(v0[j + 1 : j + 21], v1[j + 1 : j + 21])
    # After j+20: back to the original values.  Rolling means accumulate
    # incrementally, so recomputed windows may differ in the last bits only.
    np.testing.assert_allclose(
        v0[j + 21 :], v1[j + 21 :], rtol=1e-12, atol=0.0, equal_nan=True
    )


# 5. Future-data invariance ---------------------------------------------------

def test_future_data_invariance():
    n = 60
    base = varied_frame(n)
    full = lagged_parkinson_volatility(base).to_numpy()

    # A prefix reproduces the matching prefix of the longer panel exactly.
    prefix = base.iloc[:40]
    prefix_out = lagged_parkinson_volatility(prefix).to_numpy()
    np.testing.assert_array_equal(prefix_out, full[:40])

    # Perturb valid ranges at and after the evaluation timestamp (row 45).
    evaluation_row = 45
    perturbed = base.copy()
    high_col = perturbed.columns.get_loc("high")
    low_col = perturbed.columns.get_loc("low")
    perturbed.iloc[evaluation_row:, high_col] *= 1.3
    perturbed.iloc[evaluation_row:, low_col] *= 0.7  # positive, high >= low
    out = lagged_parkinson_volatility(perturbed).to_numpy()
    # Outputs through the evaluation timestamp unchanged, NaN masks included.
    np.testing.assert_array_equal(
        out[: evaluation_row + 1], full[: evaluation_row + 1]
    )


# 6. Index and input preservation ---------------------------------------------

@pytest.mark.parametrize(
    "index_kind", ["duplicated_int", "nonmonotonic_named", "named_multi"]
)
def test_index_and_input_preservation(index_kind):
    n = 30
    frame = varied_frame(n)
    if index_kind == "duplicated_int":
        frame.index = pd.Index(np.arange(n) // 3)
    elif index_kind == "nonmonotonic_named":
        rng = np.random.default_rng(5)
        frame.index = pd.Index(
            rng.permutation(np.arange(100, 100 + n)), name="row"
        )
    else:
        frame.index = pd.MultiIndex.from_tuples(
            [(f"g{i % 3}", i) for i in range(n)], names=["group", "pos"]
        )

    original = frame.copy(deep=True)
    out = lagged_parkinson_volatility(frame)

    pd.testing.assert_index_equal(out.index, frame.index)
    assert out.shape == (n,)
    assert out.dtype == np.dtype("float64")
    assert out.name == FEATURE_NAME
    # Input frame untouched: shape, columns, dtypes, index, values.
    pd.testing.assert_frame_equal(frame, original)


# 7. Boundary rejection -------------------------------------------------------

def _set_object_symbol(frame, value):
    out = frame.copy()
    sym = out["symbol"].astype(object).copy()
    sym.iloc[0] = value
    out["symbol"] = sym
    return out


def _set_at(frame, column, value, pos=4):
    out = frame.copy()
    out.iloc[pos, out.columns.get_loc(column)] = value
    return out


def _swap_timestamps(frame, i=2, j=3):
    out = frame.copy()
    arr = out["timestamp"].array.copy()
    arr[i], arr[j] = arr[j], arr[i]
    out["timestamp"] = arr
    return out


BOUNDARY_CASES = {
    "missing_column": lambda f: f.drop(columns=["low"]),
    "duplicate_column": lambda f: pd.concat([f, f[["high"]]], axis=1),
    "numeric_symbol": lambda f: _set_object_symbol(f, 42.0),
    "null_symbol": lambda f: _set_object_symbol(f, None),
    "empty_symbol": lambda f: _set_object_symbol(f, ""),
    "naive_timestamps": lambda f: f.assign(
        timestamp=f["timestamp"].dt.tz_localize(None)
    ),
    "non_utc_timestamps": lambda f: f.assign(
        timestamp=f["timestamp"].dt.tz_convert("America/New_York")
    ),
    "nat_timestamp": lambda f: _set_at(f, "timestamp", pd.NaT),
    "duplicate_symbol_timestamp": lambda f: pd.concat(
        [f, f.iloc[[3]]], ignore_index=True
    ),
    "reversed_chronology": lambda f: _swap_timestamps(f),
    "float32_market": lambda f: f.assign(high=f["high"].astype("float32")),
    "integer_market": lambda f: f.assign(open=f["open"].astype("int64")),
    "raw_nan": lambda f: _set_at(f, "high", np.nan),
    "infinity": lambda f: _set_at(f, "close", np.inf),
    "nonpositive_price": lambda f: _set_at(f, "open", 0.0),
    "negative_volume": lambda f: _set_at(f, "volume", -1.0),
    "high_below_low": lambda f: _set_at(f, "high", f["low"].iloc[4] / 2.0),
}


@pytest.mark.parametrize("case_id", sorted(BOUNDARY_CASES))
def test_boundary_rejection(case_id):
    bad = BOUNDARY_CASES[case_id](varied_frame(25))
    with pytest.raises(DataValidationError):
        lagged_parkinson_volatility(bad)


def test_empty_input_rejected():
    with pytest.raises(DataValidationError):
        lagged_parkinson_volatility(pd.DataFrame())
    with pytest.raises(DataValidationError):
        lagged_parkinson_volatility(varied_frame(25).iloc[:0])


@pytest.mark.parametrize(
    "bad_input", [None, [], {"high": [1.0]}, np.arange(6.0), "not a frame"]
)
def test_non_dataframe_input_rejected(bad_input):
    # D09 fix: non-DataFrame inputs raise DataValidationError per updated contract
    with pytest.raises(DataValidationError):
        lagged_parkinson_volatility(bad_input)


# 8. Historical context across a fold boundary --------------------------------

def test_historical_context_across_fold_boundary():
    n = 80
    evaluation_start = 40
    base = varied_frame(n)
    full = lagged_parkinson_volatility(base).to_numpy()

    # Recompute with exactly the 20 preceding bars plus the evaluation slice.
    context = base.iloc[evaluation_start - WINDOW :]
    sliced = lagged_parkinson_volatility(context).to_numpy()

    # Context region restarts warm-up (expected NaN), but the evaluation
    # rows match the full-history computation without restarting warm-up.
    # (Rolling accumulation order may differ in the last bits only.)
    assert np.isnan(sliced[:WINDOW]).all()
    np.testing.assert_allclose(
        sliced[WINDOW:], full[evaluation_start:], rtol=1e-12, atol=0.0
    )


# 9. Public API and registry ---------------------------------------------------

def test_public_api_package_level_import():
    import quant_research.features as features_pkg

    assert features_pkg.lagged_parkinson_volatility is lagged_parkinson_volatility


def test_registry_has_exactly_one_new_entry_with_required_metadata():
    matches = [s for s in registry() if s.feature_name == FEATURE_NAME]
    assert len(matches) == 1
    spec = matches[0]
    assert spec.definition == (
        "sqrt(252 * mean_20(group_shift_1((log(high)-log(low))**2 / (4*log(2)))))"
    )
    assert spec.source == PRICE_VOLUME_SOURCE == "price_volume"
    assert spec.required_history == 21
    assert spec.availability_rule == (
        "symbol-local prior 20 observed bars ending at t-1; explicit shift(1)"
    )
    assert spec.missing_data_policy == (
        "first 20 rows per symbol are NaN; invalid raw OHLCV rejected"
    )
    assert spec.normalization_rule == (
        "none in feature; downstream imputer/scaler fit on training fold only"
    )
    assert spec.version == PARKINSON_FEATURE_VERSION == "parkinson-1.0.0"


def test_registry_hash_deterministic_for_new_feature():
    h1 = registry_hash([FEATURE_NAME])
    assert h1 == registry_hash([FEATURE_NAME])
    assert len(h1) == 16


def test_preexisting_registry_hashes_unchanged():
    legacy_pv = [
        s.feature_name
        for s in price_volume_feature_specs()
        if s.feature_name != FEATURE_NAME
    ]
    legacy_info = [s.feature_name for s in information_feature_specs()]
    assert registry_hash(["momentum_63"]) == "6566acb216cd4dd9"
    assert registry_hash(["momentum_63", "trend_50"]) == "41defd3a42afc18f"
    assert registry_hash(legacy_pv) == "bed4faf87a02829e"
    # info hash consciously updated with INFO_FEATURE_VERSION bump info-2.1.0
    # -> info-2.1.1: A01 prefix-invariant corroboration (PIT story counts) and
    # A18 first-eligible-session decay changed the feature definitions.
    assert registry_hash(legacy_info) == "c76876a9cc703644"