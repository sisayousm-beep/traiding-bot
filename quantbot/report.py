"""봇별 퀀트 분석 보고서 — 당일 장 결과를 봇마다 자세히 분해한다.

퀀트 트레이딩 개선에 쓰는 자료: FIFO 라운드트립(매수→매도 1쌍) 기준
승률·손익비·기대값·평균 보유시간·최고/최악 매매·종목별 실현손익·회전율·수수료 등을 뽑는다.

market_report() → {meta, bots:[bot_report ...]}
report_to_csv()  → 봇 요약 CSV 문자열
"""
from __future__ import annotations

import csv
import io

import pandas as pd

from . import config
from .intraday_engine import IntradayResult
from .intraday_metrics import _clean, metrics

NAME = config.display_name


def _round_trips(trades) -> list[dict]:
    """FIFO 매칭으로 매수→매도 라운드트립 손익을 만든다.

    매수원가에 매수수수료를, 매도대금에서 매도수수료를(수량 비례) 반영.
    반환: [{ticker, qty, buy_price, sell_price, buy_time, sell_time, hold_min,
            pnl, ret, commission}]
    """
    lots: dict[str, list] = {}     # ticker -> [[남은수량, 주당원가(매수수수료포함), 매수시각], ...]
    trips: list[dict] = []
    for t in trades:
        tk = t.ticker
        if t.side == "BUY":
            cps = (t.price * t.shares + t.commission) / t.shares if t.shares else t.price
            lots.setdefault(tk, []).append([t.shares, cps, t.date])
        else:  # SELL
            remaining = t.shares
            sell_comm_ps = (t.commission / t.shares) if t.shares else 0.0
            q = lots.get(tk, [])
            while remaining > 1e-9 and q:
                lot = q[0]
                take = min(lot[0], remaining)
                buy_cost = lot[1] * take
                proceeds = t.price * take - sell_comm_ps * take
                pnl = proceeds - buy_cost
                hold = None
                try:
                    hold = (t.date - lot[2]).total_seconds() / 60.0
                except Exception:
                    hold = None
                trips.append({
                    "ticker": tk, "name": NAME(tk), "qty": take,
                    "buy_price": lot[1], "sell_price": t.price,
                    "buy_time": lot[2].strftime("%H:%M") if hasattr(lot[2], "strftime") else str(lot[2]),
                    "sell_time": t.date.strftime("%H:%M") if hasattr(t.date, "strftime") else str(t.date),
                    "hold_min": hold,
                    "pnl": pnl, "ret": (pnl / buy_cost) if buy_cost > 1e-12 else None,
                    "commission": sell_comm_ps * take,
                })
                lot[0] -= take
                remaining -= take
                if lot[0] <= 1e-9:
                    q.pop(0)
    return trips


def bot_report(r: IntradayResult, capital: float) -> dict:
    pf = r.portfolio
    eq = r.equity.dropna()
    m = metrics(eq, capital)
    trips = _round_trips(pf.trades)

    wins = [t for t in trips if t["pnl"] > 0]
    losses = [t for t in trips if t["pnl"] <= 0]
    sum_win = sum(t["pnl"] for t in wins)
    sum_loss = sum(t["pnl"] for t in losses)
    realized = sum(t["pnl"] for t in trips)
    n_rt = len(trips)
    holds = [t["hold_min"] for t in trips if t["hold_min"] is not None]

    n_buys = sum(1 for t in pf.trades if t.side == "BUY")
    n_sells = sum(1 for t in pf.trades if t.side == "SELL")
    total_comm = sum(t.commission for t in pf.trades)
    gross_buy = sum(t.price * t.shares for t in pf.trades if t.side == "BUY")

    # 종목별 실현손익
    per_tkr: dict[str, dict] = {}
    for t in trips:
        d = per_tkr.setdefault(t["ticker"], {"ticker": t["ticker"], "name": t["name"],
                                             "pnl": 0.0, "round_trips": 0, "qty": 0.0})
        d["pnl"] += t["pnl"]
        d["round_trips"] += 1
        d["qty"] += t["qty"]
    per_ticker = sorted(per_tkr.values(), key=lambda d: d["pnl"])
    for d in per_ticker:
        d["pnl"] = _clean(d["pnl"])
        d["return"] = None  # 종목별 % 는 자본 대비로는 의미가 옅어 생략, pnl로 비교
        d["qty"] = _clean(d["qty"])

    best = max(trips, key=lambda t: t["pnl"], default=None)
    worst = min(trips, key=lambda t: t["pnl"], default=None)

    def trip_brief(t):
        if not t:
            return None
        return {"name": t["name"], "pnl": _clean(t["pnl"]), "ret": _clean(t["ret"]),
                "buy_time": t["buy_time"], "sell_time": t["sell_time"]}

    return {
        "name": r.name, "tagline": r.tagline, "leverage": _clean(r.leverage),
        "bankrupt": bool(getattr(pf, "bankrupt", False)),
        # 성과
        "daily_return": _clean(m.get("DailyReturn")),
        "final_equity": _clean(m.get("FinalEquity")),
        "peak_gain": _clean(m.get("PeakGain")),
        "max_drawdown": _clean(m.get("MaxDrawdown")),
        "intraday_vol": _clean(m.get("IntradayVol")),
        "win_minutes": _clean(m.get("WinMinutes")),
        # 거래 수
        "n_trades": len(pf.trades), "n_buys": n_buys, "n_sells": n_sells,
        "n_round_trips": n_rt,
        # 실현손익/품질
        "realized_pnl": _clean(realized),
        "realized_return": _clean(realized / capital) if capital else None,
        "win_rate": _clean(len(wins) / n_rt) if n_rt else None,
        "avg_win": _clean(sum_win / len(wins)) if wins else None,
        "avg_loss": _clean(sum_loss / len(losses)) if losses else None,
        "profit_factor": _clean(sum_win / abs(sum_loss)) if sum_loss < 0 else None,
        "expectancy": _clean(realized / n_rt) if n_rt else None,
        "avg_hold_min": _clean(sum(holds) / len(holds)) if holds else None,
        "max_hold_min": _clean(max(holds)) if holds else None,
        # 비용/회전
        "total_commission": _clean(total_comm),
        "turnover": _clean(gross_buy / capital) if capital else None,
        # 분해
        "best_trade": trip_brief(best),
        "worst_trade": trip_brief(worst),
        "per_ticker": per_ticker,
    }


def market_report(results: list[IntradayResult], market: str, mode: str,
                  session_date, capital: float, view: dict | None = None) -> dict:
    m = config.MARKETS[market]
    bots = [bot_report(r, capital) for r in results]
    bots.sort(key=lambda d: (d["daily_return"] is None, -(d["daily_return"] or -9e9)))
    for i, b in enumerate(bots):
        b["rank"] = i + 1
    return {
        "meta": {
            "market": market, "market_label": m["label"], "market_short": m["short"],
            "currency": m["currency"], "capital": capital, "mode": mode,
            "session_date": str(session_date) if session_date else None,
            "view_label": (view or {}).get("label"),
            "n_bars": (view or {}).get("k"), "total_bars": (view or {}).get("total"),
        },
        "bots": bots,
    }


_CSV_COLS = [
    ("rank", "순위"), ("name", "봇"), ("tagline", "전략"), ("leverage", "레버리지"),
    ("daily_return", "하루수익률"), ("realized_return", "매도실현수익률"),
    ("realized_pnl", "매도실현손익"), ("peak_gain", "고점"), ("max_drawdown", "최대낙폭"),
    ("intraday_vol", "분변동성"), ("win_minutes", "상승분비율"),
    ("n_trades", "총매매"), ("n_round_trips", "라운드트립"),
    ("win_rate", "승률"), ("profit_factor", "손익비"), ("expectancy", "기대값"),
    ("avg_win", "평균이익"), ("avg_loss", "평균손실"),
    ("avg_hold_min", "평균보유(분)"), ("max_hold_min", "최대보유(분)"),
    ("total_commission", "총수수료"), ("turnover", "회전율"),
    ("final_equity", "최종자산"), ("bankrupt", "청산여부"),
]


def report_to_csv(report: dict) -> str:
    """봇 요약을 CSV 문자열로. Excel 한글 인식을 위해 BOM 포함."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    meta = report.get("meta", {})
    w.writerow([f"# {meta.get('market_label','')} / {meta.get('mode','')} / 세션 {meta.get('session_date','')}"])
    w.writerow([h for _, h in _CSV_COLS])
    for b in report.get("bots", []):
        w.writerow([b.get(k) for k, _ in _CSV_COLS])
    return buf.getvalue()
