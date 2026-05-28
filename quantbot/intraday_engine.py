"""인트라데이 시뮬레이션 엔진 — 당일 1분봉을 따라가며 단타.

각 봇은 같은 세션 데이터로 공정 비교. 종가(마지막 봉)에 전량 청산해
하루 실현 수익률을 측정한다. look-ahead 방지: 결정은 현재 분까지의 데이터로만.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config
from .portfolio import Portfolio
from .strategies_intraday import IntradayStrategy


@dataclass
class IntradayResult:
    name: str
    tagline: str
    leverage: float
    equity: pd.Series           # 분단위 평가액
    portfolio: Portfolio


def run_intraday(bots: list[IntradayStrategy], closes: pd.DataFrame,
                 volumes: pd.DataFrame, capital: float = 10_000.0,
                 flatten_eod: bool = True) -> list[IntradayResult]:
    closes = closes.sort_index()
    volumes = volumes.reindex(closes.index).fillna(0)
    idx = closes.index
    n = len(idx)
    open_px = closes.iloc[0]

    states = [(b, Portfolio(cash=capital, max_leverage=getattr(b, "leverage", 1.0)),
               {}) for b in bots]

    last_i = n - 1
    for i, ts in enumerate(idx):
        cur = closes.iloc[i]
        for strat, pf, eqlog in states:
            if flatten_eod and i == last_i:
                if pf.positions:                       # 종가 청산(전량 현금화)
                    pf.rebalance({}, cur, ts)
            elif i >= strat.warmup_min and (i - strat.warmup_min) % strat.rebalance_min == 0:
                w = strat.weights(closes.iloc[: i + 1], volumes.iloc[: i + 1], open_px)
                if w:
                    pf.rebalance(w, cur, ts)
            pf.check_solvency(cur)
            eqlog[ts] = max(pf.total_value(cur), 0.0)

    results = []
    for strat, pf, eqlog in states:
        results.append(IntradayResult(
            name=strat.name, tagline=strat.tagline,
            leverage=getattr(strat, "leverage", 1.0),
            equity=pd.Series(eqlog).sort_index(), portfolio=pf,
        ))
    return results
