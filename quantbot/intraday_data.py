"""인트라데이(1분봉) 데이터 계층.

당일 단타 시뮬레이션용. 두 가지 세션 모드:
  - "prev"  : 직전 거래일 세션(전날 장)으로 시뮬레이션
  - "today" : 오늘(가장 최근) 세션 — 장중 실시간 정보 반영

반환: (closes, volumes, session_date, status)
  closes/volumes : DataFrame(index=분 타임스탬프, columns=티커)
  status         : "ok" | "no_session" | "no_data"
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from . import config


def _split_panels(raw: pd.DataFrame, tickers: list[str]):
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"].copy()
        volumes = raw["Volume"].copy() if "Volume" in raw.columns.get_level_values(0) else closes * 0
    else:
        closes = raw[["Close"]].copy(); closes.columns = tickers[:1]
        volumes = raw[["Volume"]].copy(); volumes.columns = tickers[:1]
    closes = closes.reindex(columns=tickers)
    volumes = volumes.reindex(columns=tickers)
    return closes, volumes


def load_intraday(mode: str = "today", tickers: list[str] | None = None):
    """1분봉 세션 데이터 로드."""
    import yfinance as yf

    tickers = tickers or config.TECH_UNIVERSE

    # 최근 여러 날의 1분봉을 받아 세션별로 분리(1분봉은 최근 ~7일만 제공)
    raw = yf.download(tickers, period="5d", interval="1m",
                      auto_adjust=True, progress=False, group_by="column")
    if raw is None or raw.empty:
        return None, None, None, "no_data"

    closes, volumes = _split_panels(raw, tickers)
    closes.index = pd.to_datetime(closes.index)
    volumes.index = pd.to_datetime(volumes.index)

    # 세션(거래일)별 그룹
    session_dates = sorted({ts.date() for ts in closes.index})
    if not session_dates:
        return None, None, None, "no_session"

    if mode == "prev":
        # 가장 최근 세션의 직전 세션
        if len(session_dates) < 2:
            return None, None, None, "no_session"
        target = session_dates[-2]
    else:  # today / live → 가장 최근 세션
        target = session_dates[-1]

    mask = [ts.date() == target for ts in closes.index]
    c = closes.loc[mask].dropna(how="all")
    v = volumes.loc[mask].reindex(c.index)

    # 분 단위 결측은 직전가로 보정(거래 없는 분), 시작 전 NaN은 유지
    c = c.ffill()
    v = v.fillna(0)
    # 모든 값이 NaN인 종목 열 제거
    c = c.dropna(axis=1, how="all")
    v = v.reindex(columns=c.columns)

    if c.empty or c.shape[0] < 5:
        return None, None, target, "no_data"

    return c, v, target, "ok"
