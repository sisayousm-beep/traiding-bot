"""인트라데이(1분봉) 데이터 계층 — 시장(미장/국장)별.

시장:
  - "us" : 미국 기술주, America/New_York, 09:30~16:00
  - "kr" : 국내 기술주, Asia/Seoul, 09:00~15:30

모드:
  - "prev"  : 직전 거래일 세션(전날 장)
  - "today" : 오늘(또는 가장 최근) 세션 — 실시간 정보

load_session()은 '전체 세션' 패널을 반환하고, 실시간 클립/리플레이는 live.py가 담당.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

from . import config


def market_tz(market: str) -> ZoneInfo:
    return ZoneInfo(config.MARKETS[market]["tz"])


def now_market(market: str) -> dt.datetime:
    return dt.datetime.now(market_tz(market))


def market_status(market: str, now: dt.datetime | None = None) -> str:
    """현지 기준 장 상태: 'open' | 'premarket' | 'closed'."""
    m = config.MARKETS[market]
    now = now or now_market(market)
    if now.weekday() >= 5:                      # 주말
        return "closed"
    o = dt.time(*m["open"]); c = dt.time(*m["close"])
    t = now.time()
    if t < o:
        return "premarket"
    if t > c:
        return "closed"
    return "open"


def _split_panels(raw: pd.DataFrame, tickers: list[str]):
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"].copy()
        has_vol = "Volume" in raw.columns.get_level_values(0)
        volumes = raw["Volume"].copy() if has_vol else closes * 0
    else:
        closes = raw[["Close"]].copy(); closes.columns = tickers[:1]
        volumes = raw[["Volume"]].copy(); volumes.columns = tickers[:1]
    return closes.reindex(columns=tickers), volumes.reindex(columns=tickers)


def load_session(market: str, mode: str, tickers: list[str] | None = None,
                 date: str | dt.date | None = None):
    """시장/모드에 해당하는 '전체' 세션 1분봉 패널 로드.

    date 가 주어지면 그 날짜의 세션을 로드(지난 날 직접 선택). yfinance 1분봉은
    대략 최근 30일까지만 제공되므로 그 범위 내에서만 가능하다.

    반환: (closes, volumes, session_date, status, is_today)
      status  : "ok" | "no_session" | "no_data"
      is_today: 해당 세션이 현지 기준 오늘인지 (실시간 가능 여부 판단용)
    """
    import yfinance as yf

    m = config.MARKETS[market]
    tickers = tickers or m["universe"]
    tz = market_tz(market)

    target_date = None
    if date is not None:
        target_date = pd.Timestamp(date).date() if not isinstance(date, dt.date) else date
        start = (target_date - dt.timedelta(days=1)).isoformat()
        end = (target_date + dt.timedelta(days=2)).isoformat()
        raw = yf.download(tickers, start=start, end=end, interval="1m",
                          auto_adjust=True, progress=False, group_by="column")
    else:
        raw = yf.download(tickers, period="5d", interval="1m",
                          auto_adjust=True, progress=False, group_by="column")
    if raw is None or raw.empty:
        return None, None, target_date, "no_data", False

    closes, volumes = _split_panels(raw, tickers)
    idx = pd.to_datetime(closes.index)
    # 현지 시장 시간대로 정규화
    idx = idx.tz_localize(tz) if idx.tz is None else idx.tz_convert(tz)
    closes.index = idx; volumes.index = idx

    session_dates = sorted({ts.date() for ts in idx})
    if not session_dates:
        return None, None, target_date, "no_session", False

    if target_date is not None:
        if target_date not in session_dates:
            return None, None, target_date, "no_session", False
        target = target_date
    elif mode == "prev":
        if len(session_dates) < 2:
            return None, None, None, "no_session", False
        target = session_dates[-2]
    else:
        target = session_dates[-1]

    mask = idx.date == target if hasattr(idx, "date") else [ts.date() == target for ts in idx]
    c = closes.loc[mask].dropna(how="all").ffill()
    v = volumes.loc[c.index].fillna(0)
    c = c.dropna(axis=1, how="all")
    v = v.reindex(columns=c.columns)

    if c.empty or c.shape[0] < 5:
        return None, None, target, "no_data", False

    is_today = (target == now_market(market).date())
    return c, v, target, "ok", is_today
