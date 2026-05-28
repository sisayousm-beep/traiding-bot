"""인트라데이 성과 지표 + 웹 페이로드 — 하루 단위 비교.

핵심은 '하루 수익률'. 보유 종목 시초대비 등락, 종목 주가 흐름, 전 매매 기록 포함.
"""
from __future__ import annotations

import math

import pandas as pd

from . import config
from .intraday_engine import IntradayResult

NAME = config.display_name


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
    return {
        "DailyReturn": eq.iloc[-1] / initial - 1.0,
        "PeakGain": eq.max() / initial - 1.0,
        "MaxDrawdown": (eq / eq.cummax() - 1.0).min(),
        "IntradayVol": rets.std(),
        "WinMinutes": (rets > 0).mean(),
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


def _trades_payload(pf, open_px: pd.Series) -> list[dict]:
    out = []
    for t in pf.trades:
        ts = t.date
        tstr = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)
        amount = t.shares * t.price
        out.append({
            "time": tstr, "ticker": t.ticker, "name": NAME(t.ticker),
            "side": t.side, "shares": _clean(t.shares), "price": _clean(t.price),
            "amount": _clean(amount), "commission": _clean(t.commission),
        })
    return out


def to_payload(results, closes: pd.DataFrame, session_date, market: str,
               mode: str, capital: float, view: dict) -> dict:
    m = config.MARKETS[market]
    times = [ts.strftime("%H:%M") for ts in closes.index]
    open_px = closes.iloc[0]
    last = closes.iloc[-1]
    board = leaderboard(results, capital)

    equity, holdings, taglines, trades = {}, {}, {}, {}
    held = set()
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
            held.add(tkr)
            op = open_px.get(tkr)
            val = sh * float(px)
            pos.append({
                "ticker": tkr, "name": NAME(tkr), "shares": _clean(sh),
                "price": _clean(px), "value": _clean(val),
                "weight": _clean(val / total) if total else None,
                "chg_open": _clean(float(px) / float(op) - 1.0) if op and pd.notna(op) else None,
            })
        pos.sort(key=lambda d: -(d["value"] or 0))
        holdings[r.name] = {"total": _clean(total), "cash": _clean(pf.cash),
                            "leverage": _clean(r.leverage),
                            "bankrupt": bool(getattr(pf, "bankrupt", False)),
                            "positions": pos, "n_trades": len(pf.trades)}
        trades[r.name] = _trades_payload(pf, open_px)

    # 보유 종목 주가 흐름(시초가 대비 %) — 현재 어느 봇이든 들고 있는 종목들
    held_prices = {}
    for tkr in list(held)[:14]:
        op = open_px.get(tkr)
        if op is None or pd.isna(op) or op == 0:
            continue
        series = ((closes[tkr] / float(op) - 1.0) * 100).tolist()
        holders = [r.name for r in results if tkr in r.portfolio.positions]
        held_prices[tkr] = {
            "name": NAME(tkr),
            "pct": [_clean(x) for x in series],
            "last_pct": _clean((float(last[tkr]) / float(op) - 1.0) * 100) if pd.notna(last.get(tkr)) else None,
            "last_price": _clean(last.get(tkr)),
            "holders": holders,
        }

    return {
        "meta": {
            "market": market, "market_label": m["label"], "market_short": m["short"],
            "currency": m["currency"], "capital": capital,
            "open_kst": m["open_kst"], "close_kst": m["close_kst"],
            "mode": mode, "session_date": str(session_date) if session_date else None,
            "n_bars": len(times), "total_bars": view.get("total"),
            "view_kind": view.get("kind"), "view_label": view.get("label"),
            "market_status": view.get("market_status"),
            "n_tickers": closes.shape[1],
            "current_time": times[-1] if times else None,
        },
        "times": times,
        "leaderboard": board,
        "equity": equity,
        "holdings": holdings,
        "taglines": taglines,
        "held_prices": held_prices,
        "trades": trades,
    }
