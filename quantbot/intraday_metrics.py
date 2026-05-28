"""인트라데이 성과 지표 — 하루 단위 비교에 맞춤.

핵심은 '하루 수익률'. 그 외 장중 변동성/최대낙폭/매매횟수 등 보조 지표.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .intraday_engine import IntradayResult


def _clean(x):
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(xf) or math.isinf(xf)) else xf


def metrics(eq: pd.Series, initial: float) -> dict:
    eq = eq.dropna()
    if eq.shape[0] < 2:
        return {}
    rets = eq.pct_change().dropna()
    daily_return = eq.iloc[-1] / initial - 1.0
    dd = (eq / eq.cummax() - 1.0).min()
    intraday_vol = rets.std()                      # 분단위 변동성(연율화 안 함)
    win = (rets > 0).mean()
    peak_gain = eq.max() / initial - 1.0
    return {
        "DailyReturn": daily_return,
        "PeakGain": peak_gain,
        "MaxDrawdown": dd,
        "IntradayVol": intraday_vol,
        "WinMinutes": win,
        "FinalEquity": eq.iloc[-1],
    }


def leaderboard(results: list[IntradayResult], initial: float) -> list[dict]:
    rows = []
    for r in results:
        m = metrics(r.equity, initial)
        if not m:
            continue
        rows.append({
            "name": r.name, "tagline": r.tagline, "leverage": r.leverage,
            "bankrupt": bool(getattr(r.portfolio, "bankrupt", False)),
            "n_trades": len(r.portfolio.trades),
            **{k: _clean(v) for k, v in m.items()},
        })
    rows.sort(key=lambda d: (d["DailyReturn"] is None, -(d["DailyReturn"] or -9e9)))
    for i, row in enumerate(rows):
        row["rank"] = i + 1
    return rows


def to_payload(results: list[IntradayResult], closes: pd.DataFrame,
               session_date, mode: str, initial: float) -> dict:
    times = [ts.strftime("%H:%M") for ts in closes.index]
    board = leaderboard(results, initial)
    by_name = {r.name: r for r in results}

    equity, holdings, taglines = {}, {}, {}
    last = closes.iloc[-1]
    for r in results:
        eq = r.equity.reindex(closes.index)
        equity[r.name] = [_clean(v) for v in eq.values]
        taglines[r.name] = r.tagline
        pf = r.portfolio
        total = pf.total_value(last)
        pos = []
        for tkr, sh in pf.positions.items():
            px = last.get(tkr)
            if px is None or pd.isna(px):
                continue
            val = sh * float(px)
            pos.append({"ticker": tkr, "shares": _clean(sh), "price": _clean(px),
                        "value": _clean(val), "weight": _clean(val / total) if total else None})
        pos.sort(key=lambda d: -(d["value"] or 0))
        holdings[r.name] = {"total": _clean(total), "cash": _clean(pf.cash),
                            "leverage": _clean(r.leverage),
                            "bankrupt": bool(getattr(pf, "bankrupt", False)),
                            "positions": pos, "n_trades": len(pf.trades)}

    return {
        "meta": {
            "mode": mode,
            "session_date": str(session_date) if session_date else None,
            "n_bars": len(times),
            "initial_capital": initial,
            "n_tickers": closes.shape[1],
        },
        "times": times,
        "leaderboard": board,
        "equity": equity,
        "holdings": holdings,
        "taglines": taglines,
    }
