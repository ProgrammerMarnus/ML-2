"""Trading safeguards: explicit, testable pre-trade checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class SafeguardResult:
    name: str
    passed: bool
    detail: str


class Safeguards:
    """Position/loss limits, stale-data detection, kill switch."""

    def __init__(
        self,
        max_position: float = 1.0,
        max_daily_loss: float = 0.05,
        max_portfolio_drawdown: float = 0.20,
        max_data_age_bars: int = 3,
    ) -> None:
        self.max_position = max_position
        self.max_daily_loss = max_daily_loss
        self.max_portfolio_drawdown = max_portfolio_drawdown
        self.max_data_age_bars = max_data_age_bars
        self.kill_switch_active = False

    def check_position(self, intended: float) -> SafeguardResult:
        ok = abs(intended) <= self.max_position and not self.kill_switch_active
        return SafeguardResult("position_limit", ok,
                               f"|position| {abs(intended)} <= {self.max_position}, "
                               f"kill_switch={self.kill_switch_active}")

    def check_daily_loss(self, daily_return: float) -> SafeguardResult:
        ok = daily_return > -self.max_daily_loss
        if not ok:
            self.kill_switch_active = True
        return SafeguardResult("daily_loss", ok, f"daily return {daily_return}")

    def check_drawdown(self, current_drawdown: float) -> SafeguardResult:
        ok = current_drawdown >= -self.max_portfolio_drawdown
        if not ok:
            self.kill_switch_active = True
        return SafeguardResult("portfolio_drawdown", ok, f"drawdown {current_drawdown}")

    def check_data_freshness(self, last_bar_ts: pd.Timestamp, now: pd.Timestamp,
                             bar_freq_days: int = 1) -> SafeguardResult:
        age_bars = int((now - last_bar_ts) / pd.Timedelta(days=bar_freq_days))
        ok = age_bars <= self.max_data_age_bars
        return SafeguardResult("data_freshness", ok, f"data age {age_bars} bars")

    def trip_kill_switch(self, reason: str) -> None:
        self.kill_switch_active = True
        self._reason = reason
