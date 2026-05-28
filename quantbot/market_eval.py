"""당일 '장(場) 평가' — 그날 시장 전체가 상승장이었는지 하락장이었는지 객관 측정.

핵심 아이디어: 상승장이면 형편없는 봇도 벌고, 하락장이면 고수 봇도 잃는다.
그래서 봇 성과를 '시장 그 자체' 대비(=알파)로 봐야 진짜 실력이 보인다.

시장 기준선은 유니버스 전 종목을 '시초가에 등가중 매수해 종가까지 보유'한
벤치마크다(아무 판단 없는 무지성 보유 = 시장 평균). 이 지수의 시초→종가 수익률,
장중 고점/저점, 변동성, 상승/하락 종목 수(breadth), 장 흐름(전반/후반)을 뽑아
다섯 단계 국면(강세/상승/보합/하락/약세)으로 분류한다.

evaluate_market() → {regime, market_return, breadth, index 곡선, best/worst 종목 ...}
"""
from __future__ import annotations

import math

import pandas as pd

from . import config

NAME = config.display_name


def _clean(x):
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(xf) or math.isinf(xf)) else xf


# (하한 임계치, 코드, 라벨, 한 줄 설명). open→close 등가중 수익률 기준, 내림차순.
_REGIMES = [
    (0.015,  "strong_bull", "강세장", "시장 전체가 크게 올라 대부분의 봇이 쉽게 수익을 낼 환경"),
    (0.004,  "bull",        "상승장", "시장이 완만히 상승 — 매수 편향 전략에 유리"),
    (-0.004, "flat",        "보합장", "방향성 없는 횡보 — 실력(알파)이 그대로 드러나는 환경"),
    (-0.015, "bear",        "하락장", "시장이 완만히 하락 — 손실을 줄이는 것이 곧 실력"),
    (-9e9,   "strong_bear", "약세장", "시장 전체가 크게 빠져 고수 봇도 수익 내기 어려운 환경"),
]


def _regime(market_return: float) -> tuple[str, str, str]:
    for lo, code, label, desc in _REGIMES:
        if market_return >= lo:
            return code, label, desc
    return "strong_bear", "약세장", _REGIMES[-1][3]


def _trend_shape(morning: float | None, afternoon: float | None) -> str:
    if morning is None or afternoon is None:
        return "알수없음"
    eps = 0.001
    up_m, up_a = morning > eps, afternoon > eps
    dn_m, dn_a = morning < -eps, afternoon < -eps
    if up_m and up_a:
        return "꾸준한 상승"
    if dn_m and dn_a:
        return "꾸준한 하락"
    if dn_m and up_a:
        return "후반 반등(V자)"
    if up_m and dn_a:
        return "후반 하락(차익실현)"
    return "방향성 없는 횡보"


def market_index(closes: pd.DataFrame) -> pd.Series:
    """유니버스 등가중 매수보유 지수(시초가=1.0 기준 배수). 종목별로 첫 유효값에
    정규화한 뒤 분마다 종목 평균을 취한다 → '시장 평균'의 분단위 곡선."""
    closes = closes.sort_index()
    norm = closes.apply(lambda col: col / col.dropna().iloc[0]
                        if col.dropna().shape[0] else col, axis=0)
    return norm.mean(axis=1, skipna=True)


def evaluate_market(closes: pd.DataFrame, volumes: pd.DataFrame | None,
                    market: str, session_date, capital: float = 0.0) -> dict:
    """그날 장 전체를 평가한 구조화 결과. closes: 행=분, 열=종목 종가 패널."""
    closes = closes.sort_index()
    idx = market_index(closes).dropna()
    if idx.shape[0] < 2:
        return {"available": False}

    series = (idx / idx.iloc[0] - 1.0)             # 시초 대비 % (분단위)
    market_return = float(series.iloc[-1])
    peak = float(series.max())
    trough = float(series.min())
    rets = idx.pct_change().dropna()
    vol = float(rets.std()) if rets.shape[0] else 0.0
    mdd = float((idx / idx.cummax() - 1.0).min())
    up_minutes = float((rets > 0).mean()) if rets.shape[0] else 0.0

    # 전반/후반 흐름
    n = series.shape[0]
    mid = n // 2
    morning = float(series.iloc[mid]) if mid > 0 else None
    afternoon = (float(series.iloc[-1]) - float(series.iloc[mid])) if mid > 0 else None

    # 종목별 시초→종가 등락 (breadth + 최고/최악 종목)
    per = []
    for tkr in closes.columns:
        col = closes[tkr].dropna()
        if col.shape[0] < 2 or col.iloc[0] == 0:
            continue
        ret = float(col.iloc[-1] / col.iloc[0] - 1.0)
        per.append({"ticker": tkr, "name": NAME(tkr), "return": _clean(ret)})
    n_total = len(per)
    n_up = sum(1 for p in per if p["return"] is not None and p["return"] > 0)
    n_down = sum(1 for p in per if p["return"] is not None and p["return"] < 0)
    n_flat = n_total - n_up - n_down
    per.sort(key=lambda p: (p["return"] is None, -(p["return"] or -9e9)))
    best = per[0] if per else None
    worst = per[-1] if per else None

    code, label, desc = _regime(market_return)
    times = [ts.strftime("%H:%M") for ts in idx.index]

    return {
        "available": True,
        "regime": code, "regime_label": label, "regime_desc": desc,
        "market_return": _clean(market_return),     # 등가중 매수보유(=시장) 하루 수익률
        "peak_gain": _clean(peak), "trough": _clean(trough),
        "max_drawdown": _clean(mdd),
        "index_vol": _clean(vol), "up_minutes": _clean(up_minutes),
        "breadth_up": _clean(n_up / n_total) if n_total else None,
        "n_up": n_up, "n_down": n_down, "n_flat": n_flat, "n_tickers": n_total,
        "morning_return": _clean(morning), "afternoon_return": _clean(afternoon),
        "trend_shape": _trend_shape(morning, afternoon),
        "best_ticker": best, "worst_ticker": worst,
        # 차트/검증용 분단위 시장 곡선(시초 대비 %)
        "index_times": times,
        "index_pct": [_clean(x * 100) for x in series.tolist()],
    }
