"""봇별 퀀트 분석 보고서 — 당일 장 결과를 봇마다 자세히 분해한다.

퀀트 트레이딩 개선에 쓰는 자료: FIFO 라운드트립(매수→매도 1쌍) 기준
승률·손익비·기대값·평균 보유시간·최고/최악 매매·종목별 실현손익·회전율·수수료 등을 뽑는다.

추가로 '당일 장 평가'(market_eval)를 함께 실어, 봇 성과를 시장 그 자체(등가중
매수보유) 대비 초과수익(알파)으로 맥락화한다 → 상승장에서 번 건지, 진짜 실력인지 구분.

market_report()    → {meta, market, bots:[bot_report ...]}
report_to_csv()    → 봇 요약 CSV 문자열(시장 평가 헤더 포함)
report_to_jsonl()  → AI 학습용 JSONL(세션당 봇별 1줄, 시장 국면 + 알파 라벨)
"""
from __future__ import annotations

import csv
import io
import json
import math

import pandas as pd

from . import config
from .intraday_engine import IntradayResult
from .intraday_metrics import _clean, metrics
from .market_eval import evaluate_market

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
                    "buy_time": config.to_kst_hm(lot[2]),
                    "sell_time": config.to_kst_hm(t.date),
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


def _vs_market(daily_return, market_return) -> tuple[float | None, str]:
    """봇 수익률을 시장(등가중 매수보유) 대비로 평가 → (알파, 한 줄 라벨).

    핵심: 절대 수익보다 '시장 대비'가 실력에 가깝다.
      - 하락장에서 플러스 = 진짜 실력
      - 상승장에서 플러스지만 시장보다 낮음 = 시장 덕(언더퍼폼)
    """
    if daily_return is None or market_return is None:
        return None, "평가불가"
    alpha = daily_return - market_return
    beat = alpha > 0
    if market_return <= -0.001:                       # 하락장
        if daily_return > 0:
            return alpha, "하락장 방어 후 플러스 — 진짜 실력"
        return alpha, ("하락장에서 시장보다 선방(손실 축소)" if beat
                       else "하락장에서 시장보다 더 큰 손실")
    if market_return >= 0.001:                         # 상승장
        if daily_return <= 0:
            return alpha, "상승장인데 손실 — 전략 결함 의심"
        return alpha, ("상승장에서 시장 초과수익(알파)" if beat
                       else "상승장 덕에 벌었으나 시장에 못 미침")
    return alpha, ("보합장에서 초과수익(알파)" if beat else "보합장에서 시장 하회")


def market_report(results: list[IntradayResult], market: str, mode: str,
                  session_date, capital: float, view: dict | None = None,
                  closes: pd.DataFrame | None = None,
                  volumes: pd.DataFrame | None = None) -> dict:
    m = config.MARKETS[market]
    bots = [bot_report(r, capital) for r in results]
    bots.sort(key=lambda d: (d["daily_return"] is None, -(d["daily_return"] or -9e9)))
    for i, b in enumerate(bots):
        b["rank"] = i + 1

    market_eval = {"available": False}
    if closes is not None and not closes.empty:
        market_eval = evaluate_market(closes, volumes, market, session_date, capital)

    mret = market_eval.get("market_return") if market_eval.get("available") else None
    for b in bots:                                    # 봇별 시장 대비(알파) 부여
        alpha, label = _vs_market(b.get("daily_return"), mret)
        b["alpha"] = _clean(alpha)
        b["beat_market"] = (alpha > 0) if alpha is not None else None
        b["vs_market"] = label

    return {
        "meta": {
            "market": market, "market_label": m["label"], "market_short": m["short"],
            "currency": m["currency"], "capital": capital, "mode": mode,
            "session_date": str(session_date) if session_date else None,
            "view_label": (view or {}).get("label"),
            "n_bars": (view or {}).get("k"), "total_bars": (view or {}).get("total"),
        },
        "market": market_eval,
        "bots": bots,
    }


_CSV_COLS = [
    ("rank", "순위"), ("name", "봇"), ("tagline", "전략"), ("leverage", "레버리지"),
    ("daily_return", "하루수익률"), ("alpha", "시장대비(알파)"), ("vs_market", "시장대비평가"),
    ("realized_return", "매도실현수익률"),
    ("realized_pnl", "매도실현손익"), ("peak_gain", "고점"), ("max_drawdown", "최대낙폭"),
    ("intraday_vol", "분변동성"), ("win_minutes", "상승분비율"),
    ("n_trades", "총매매"), ("n_round_trips", "라운드트립"),
    ("win_rate", "승률"), ("profit_factor", "손익비"), ("expectancy", "기대값"),
    ("avg_win", "평균이익"), ("avg_loss", "평균손실"),
    ("avg_hold_min", "평균보유(분)"), ("max_hold_min", "최대보유(분)"),
    ("total_commission", "총수수료"), ("turnover", "회전율"),
    ("final_equity", "최종자산"), ("bankrupt", "청산여부"),
]


def _market_summary_rows(report: dict) -> list[list]:
    """CSV 상단에 당일 장 평가를 요약 행으로 깔아둔다."""
    me = report.get("market", {})
    if not me.get("available"):
        return [["# 당일 장 평가: 데이터 없음"]]
    bt, wt = me.get("best_ticker") or {}, me.get("worst_ticker") or {}
    return [
        [f"# 당일 장 평가: {me.get('regime_label','')} ({me.get('regime_desc','')})"],
        [f"# 시장(등가중 매수보유) 하루수익률={me.get('market_return')}",
         f"고점={me.get('peak_gain')}", f"저점={me.get('trough')}",
         f"최대낙폭={me.get('max_drawdown')}"],
        [f"# 상승종목={me.get('n_up')}/{me.get('n_tickers')}",
         f"하락종목={me.get('n_down')}", f"상승폭비율(breadth)={me.get('breadth_up')}",
         f"장흐름={me.get('trend_shape')}"],
        [f"# 최고종목={bt.get('name','')}({bt.get('return')})",
         f"최악종목={wt.get('name','')}({wt.get('return')})"],
    ]


def report_to_csv(report: dict) -> str:
    """봇 요약을 CSV 문자열로. Excel 한글 인식을 위해 BOM 포함."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    meta = report.get("meta", {})
    w.writerow([f"# {meta.get('market_label','')} / {meta.get('mode','')} / 세션 {meta.get('session_date','')}"])
    for row in _market_summary_rows(report):
        w.writerow(row)
    w.writerow([])
    w.writerow([h for _, h in _CSV_COLS])
    for b in report.get("bots", []):
        w.writerow([b.get(k) for k, _ in _CSV_COLS])
    return buf.getvalue()


# AI 학습용으로 내보낼 봇 특성(피처) — 모두 수치/범주형 평탄화.
_FEATURE_KEYS = [
    "daily_return", "realized_return", "peak_gain", "max_drawdown",
    "intraday_vol", "win_minutes", "n_trades", "n_round_trips",
    "win_rate", "profit_factor", "expectancy", "avg_win", "avg_loss",
    "avg_hold_min", "max_hold_min", "turnover", "total_commission",
    "leverage", "alpha",
]


def report_to_jsonl(report: dict) -> str:
    """AI 학습용 JSONL — 세션당 봇별 1줄.

    각 줄은 {시장 국면(맥락) + 봇 피처 + 라벨}로 구성된다. 라벨은 '시장 대비
    초과수익을 냈는가(beat_market)'와 '시장 대비 평가 문구(vs_market)'로,
    상승장 덕에 번 봇과 진짜 실력 봇을 모델이 구분 학습할 수 있게 한다.
    """
    meta = report.get("meta", {})
    me = report.get("market", {})
    market_ctx = {
        "regime": me.get("regime"),
        "regime_label": me.get("regime_label"),
        "market_return": me.get("market_return"),
        "market_peak_gain": me.get("peak_gain"),
        "market_max_drawdown": me.get("max_drawdown"),
        "market_index_vol": me.get("index_vol"),
        "breadth_up": me.get("breadth_up"),
        "n_up": me.get("n_up"), "n_down": me.get("n_down"),
        "n_tickers": me.get("n_tickers"),
        "trend_shape": me.get("trend_shape"),
        "morning_return": me.get("morning_return"),
        "afternoon_return": me.get("afternoon_return"),
    } if me.get("available") else {"regime": None}

    lines = []
    for b in report.get("bots", []):
        rec = {
            "session_date": meta.get("session_date"),
            "market": meta.get("market"),
            "mode": meta.get("mode"),
            "bot": b.get("name"),
            "strategy": b.get("tagline"),
            "bankrupt": b.get("bankrupt"),
            "rank": b.get("rank"),
            "market_context": market_ctx,
            "features": {k: b.get(k) for k in _FEATURE_KEYS},
            "label": {
                "beat_market": b.get("beat_market"),
                "alpha": b.get("alpha"),
                "vs_market": b.get("vs_market"),
                "daily_return": b.get("daily_return"),
            },
        }
        lines.append(json.dumps(rec, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


# ===== 여러 날 × 여러 시장: 대량 추출 + 봇 종합 랭킹 =====

def session_reports(market: str, days: int = 30, include_today: bool = False,
                    capital: float | None = None) -> list[dict]:
    """최근 days 일간(달력) 완료 세션마다 market_report를 만들어 리스트로 돌려준다.

    '전일 기준'이 기본이라 오늘(진행 중) 세션은 include_today=False로 제외한다.
    yfinance 1분봉 한계 안에서 받을 수 있는 모든 거래일이 대상이다(보통 20~22거래일).
    """
    from .intraday_data import load_sessions, now_market
    from .intraday_engine import run_intraday
    from .strategies_intraday import default_bots

    m = config.MARKETS[market]
    cap = m["capital"] if capital is None else capital
    today = now_market(market).date()

    reports = []
    for d, c, v in load_sessions(market, days=days):
        if not include_today and d >= today:
            continue
        res = run_intraday(default_bots(), c, v, cap, flatten_eod=True)
        view = {"k": len(c), "total": len(c), "kind": "backtest",
                "label": f"{d} — 완료 세션"}
        rep = market_report(res, market, "prev", d, cap, view, closes=c, volumes=v)
        reports.append(rep)
    return reports


def bulk_reports(markets, days: int = 30, include_today: bool = False) -> list[dict]:
    """여러 시장 × 여러 날의 세션 리포트를 한 리스트로 모은다(대량 추출용)."""
    if isinstance(markets, str):
        markets = [markets]
    out = []
    for market in markets:
        if market not in config.MARKETS:
            continue
        out.extend(session_reports(market, days=days, include_today=include_today))
    return out


def reports_to_jsonl(reports: list[dict]) -> str:
    """여러 세션 리포트를 하나의 JSONL로 이어붙인다(AI 학습용 대량 파일)."""
    return "".join(report_to_jsonl(r) for r in reports)


# 대량 CSV(평탄): 세션·시장 맥락 + 봇 핵심 지표를 한 행씩.
_BULK_COLS = [
    ("session_date", "세션날짜"), ("market", "시장"), ("regime", "장국면"),
    ("market_return", "시장수익률"),
    ("rank", "순위"), ("name", "봇"), ("tagline", "전략"),
    ("daily_return", "하루수익률"), ("alpha", "시장대비알파"), ("beat_market", "시장초과"),
    ("realized_return", "매도실현수익률"), ("realized_pnl", "매도실현손익"),
    ("win_rate", "승률"), ("profit_factor", "손익비"), ("expectancy", "기대값"),
    ("n_trades", "총매매"), ("n_round_trips", "라운드트립"),
    ("peak_gain", "고점"), ("max_drawdown", "최대낙폭"),
    ("final_equity", "최종자산"), ("bankrupt", "청산여부"),
]


def reports_to_flat_csv(reports: list[dict]) -> str:
    """여러 세션 리포트를 (세션×봇) 한 행씩의 평탄 CSV로. Excel용 BOM 포함."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow([h for _, h in _BULK_COLS])
    for rep in reports:
        meta = rep.get("meta", {})
        me = rep.get("market", {})
        for b in rep.get("bots", []):
            row = []
            for k, _ in _BULK_COLS:
                if k == "session_date":
                    row.append(meta.get("session_date"))
                elif k == "market":
                    row.append(meta.get("market"))
                elif k == "regime":
                    row.append(me.get("regime_label"))
                elif k == "market_return":
                    row.append(me.get("market_return"))
                else:
                    row.append(b.get(k))
            w.writerow(row)
    return buf.getvalue()


def rank_bots(reports: list[dict]) -> list[dict]:
    """여러 세션 리포트에서 봇별 평균 순위·수익률을 집계해 '종합 등수'를 매긴다.

    종합 등수 기준: 평균 순위가 낮을수록(=좋을수록) 우선, 동률이면 평균 수익률이
    높은 순. 순위는 세션 안에서 봇끼리 비교(1..N)라 시장이 달라도 비교 가능하고,
    수익률·알파는 % 라 통화가 달라도 평균낼 수 있다.
    """
    agg: dict[str, dict] = {}
    for rep in reports:
        for b in rep.get("bots", []):
            name = b.get("name")
            d = agg.setdefault(name, {
                "name": name, "tagline": b.get("tagline"), "leverage": b.get("leverage"),
                "ranks": [], "returns": [], "alphas": [],
                "beats": 0, "beat_n": 0, "bankrupts": 0, "n": 0,
            })
            d["n"] += 1
            if b.get("rank") is not None:
                d["ranks"].append(b["rank"])
            if b.get("daily_return") is not None:
                d["returns"].append(b["daily_return"])
            if b.get("alpha") is not None:
                d["alphas"].append(b["alpha"])
            if b.get("beat_market") is not None:
                d["beat_n"] += 1
                d["beats"] += 1 if b["beat_market"] else 0
            if b.get("bankrupt"):
                d["bankrupts"] += 1

    def avg(xs):
        return (sum(xs) / len(xs)) if xs else None

    out = []
    for d in agg.values():
        out.append({
            "name": d["name"], "tagline": d["tagline"], "leverage": _clean(d["leverage"]),
            "n_sessions": d["n"],
            "avg_rank": _clean(avg(d["ranks"])),
            "avg_return": _clean(avg(d["returns"])),
            "avg_alpha": _clean(avg(d["alphas"])),
            "best_return": _clean(max(d["returns"])) if d["returns"] else None,
            "worst_return": _clean(min(d["returns"])) if d["returns"] else None,
            "win_rate_vs_market": _clean(d["beats"] / d["beat_n"]) if d["beat_n"] else None,
            "bankrupt_count": d["bankrupts"],
        })
    out.sort(key=lambda d: (d["avg_rank"] is None,
                            d["avg_rank"] if d["avg_rank"] is not None else 9e9,
                            -(d["avg_return"] if d["avg_return"] is not None else -9e9)))
    for i, d in enumerate(out):
        d["overall_rank"] = i + 1
    return out


def ranking_report(markets, days: int = 30) -> dict:
    """전일 기준 days일간 완료 세션들로 봇 종합 랭킹을 만든다.

    markets가 여러 개면 그 시장들의 모든 세션을 합쳐 평균낸다(어느 봇이
    시장을 가리지 않고 평균적으로 잘하는지). 단일 시장이면 그 시장만.
    """
    if isinstance(markets, str):
        markets = [markets]
    markets = [m for m in markets if m in config.MARKETS]
    reports = bulk_reports(markets, days=days)
    bots = rank_bots(reports)

    sessions = [{
        "session_date": r["meta"].get("session_date"),
        "market": r["meta"].get("market"),
        "regime": r.get("market", {}).get("regime_label"),
        "market_return": r.get("market", {}).get("market_return"),
    } for r in reports]
    sessions.sort(key=lambda s: (str(s["session_date"]), str(s["market"])))

    labels = [config.MARKETS[m]["short"] for m in markets]
    return {
        "meta": {
            "markets": markets, "market_labels": labels,
            "days": days, "n_sessions": len(reports),
            "date_from": sessions[0]["session_date"] if sessions else None,
            "date_to": sessions[-1]["session_date"] if sessions else None,
        },
        "bots": bots,
        "sessions": sessions,
    }


# ===== 시장 보정 성능점수(=실력 점수) =====
# 성격이 다른 두 그룹을 따로 평가: 우량주(일반) vs 급등주(🔥).
SCORE_GROUPS = {
    "normal": ["kr", "us"],          # 국장 + 미장 (우량 기술주)
    "hot": ["kr_hot", "us_hot"],     # 급등 국장 + 급등 미장 (모멘텀/테마주)
}
# 신뢰가중 평균알파가 이 값(2%/일)이면 tanh가 거의 포화 → 점수 만점에 근접.
_SCORE_SCALE = 0.02
# 청산(파산)한 적이 있으면 점수 상한(시장 매치=50 아래로) — 큰 한 방의 위험을 벌점.
_BANKRUPT_CAP = 30.0


def _std(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mu = sum(xs) / n
    return (sum((x - mu) ** 2 for x in xs) / n) ** 0.5


def score_bots(reports: list[dict]) -> list[dict]:
    """그날 장 상황(시장 수익률)을 빼낸 알파를 모아 봇별 '성능점수'를 만든다.

    핵심: 절대 수익은 그날 장이 좋았는지에 크게 좌우된다. 그래서 봇 성과를
    '그날 시장(등가중 매수보유) 대비 초과수익(알파)'으로 환산하면, 상승장 덕에
    번 봇과 진짜 실력 봇이 구분된다. 알파를 한 주간 모아:
      - 평균 알파(avg_alpha): 시장 보정 후 평균적으로 얼마나 더 벌었나(실력의 크기)
      - 시장승률(beat_rate): 며칠이나 시장을 이겼나(꾸준함)
      - 정보비율(info_ratio = 평균알파/알파표준편차): 운이 아닌 실력의 신뢰도

    성능점수(0~100): 50 = 시장과 동일(실력 0). 위로 갈수록 시장 보정 실력↑.
      score = 50 + 50·tanh( 평균알파 · (0.5+시장승률) / SCALE )
      (시장승률을 신뢰가중치로 곱해, 하루 운으로 번 봇은 점수를 깎는다.)
      청산 이력이 있으면 상한 30으로 벌점(큰 손실 위험 반영).
    """
    agg: dict[str, dict] = {}
    for rep in reports:
        mret = rep.get("market", {}).get("market_return")
        for b in rep.get("bots", []):
            name = b.get("name")
            d = agg.setdefault(name, {
                "name": name, "tagline": b.get("tagline"), "leverage": b.get("leverage"),
                "alphas": [], "returns": [], "mkts": [],
                "beats": 0, "beat_n": 0, "bust": 0, "n": 0,
            })
            d["n"] += 1
            if b.get("alpha") is not None:
                d["alphas"].append(b["alpha"])
            if b.get("daily_return") is not None:
                d["returns"].append(b["daily_return"])
            if mret is not None:
                d["mkts"].append(mret)
            if b.get("beat_market") is not None:
                d["beat_n"] += 1
                d["beats"] += 1 if b["beat_market"] else 0
            if b.get("bankrupt"):
                d["bust"] += 1

    out = []
    for d in agg.values():
        alphas = d["alphas"]
        avg_alpha = sum(alphas) / len(alphas) if alphas else None
        std_alpha = _std(alphas)
        avg_ret = sum(d["returns"]) / len(d["returns"]) if d["returns"] else None
        avg_mkt = sum(d["mkts"]) / len(d["mkts"]) if d["mkts"] else None
        beat_rate = d["beats"] / d["beat_n"] if d["beat_n"] else None
        info_ratio = (avg_alpha / std_alpha) if (avg_alpha is not None
                                                 and std_alpha and std_alpha > 0) else None

        if avg_alpha is None:
            score = None
        else:
            conf = 0.5 + (beat_rate if beat_rate is not None else 0.5)
            score = 50.0 + 50.0 * math.tanh(avg_alpha * conf / _SCORE_SCALE)
            if d["bust"] > 0:
                score = min(score, _BANKRUPT_CAP)
            score = round(score, 1)

        out.append({
            "name": d["name"], "tagline": d["tagline"], "leverage": _clean(d["leverage"]),
            "score": _clean(score), "n_sessions": d["n"],
            "avg_alpha": _clean(avg_alpha),
            "avg_return": _clean(avg_ret),
            "avg_market_return": _clean(avg_mkt),
            "beat_rate": _clean(beat_rate),
            "info_ratio": _clean(info_ratio),
            "alpha_vol": _clean(std_alpha),
            "bankrupt_count": d["bust"],
        })
    out.sort(key=lambda d: (d["score"] is None,
                            -(d["score"] if d["score"] is not None else -9e9)))
    for i, d in enumerate(out):
        d["rank"] = i + 1
    return out


def score_report(group: str, days: int = 7) -> dict:
    """그룹(normal=국장+미장 / hot=급등 국장+급등 미장)의 봇 성능점수 표.

    근 days일(기본 7일=일주일) 완료 세션을 두 시장에서 모아 한 점수로 합산한다.
    알파는 '각 세션의 자기 시장 대비 초과수익'이라 국장·미장을 섞어도 동질이다.
    """
    markets = SCORE_GROUPS.get(group)
    if not markets:
        return {"error": f"알 수 없는 그룹: {group}", "status": "bad_group"}
    reports = bulk_reports(markets, days=days)
    bots = score_bots(reports)

    sessions = [{
        "session_date": r["meta"].get("session_date"),
        "market": r["meta"].get("market"),
        "regime": r.get("market", {}).get("regime_label"),
        "market_return": r.get("market", {}).get("market_return"),
    } for r in reports]
    sessions.sort(key=lambda s: (str(s["session_date"]), str(s["market"])))

    labels = [config.MARKETS[m]["short"] for m in markets]
    return {
        "meta": {
            "group": group, "markets": markets, "market_labels": labels,
            "days": days, "n_sessions": len(reports),
            "date_from": sessions[0]["session_date"] if sessions else None,
            "date_to": sessions[-1]["session_date"] if sessions else None,
        },
        "bots": bots,
        "sessions": sessions,
    }
