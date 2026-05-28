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
import time
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


def _clean_session(closes: pd.DataFrame, volumes: pd.DataFrame, target: dt.date):
    """전체 패널에서 target 날짜 하루치만 잘라 정리한다.
    반환: (closes, volumes) 또는 데이터가 빈약하면 None."""
    idx = closes.index
    mask = idx.date == target if hasattr(idx, "date") else [ts.date() == target for ts in idx]
    c = closes.loc[mask].dropna(how="all").ffill()
    v = volumes.loc[c.index].fillna(0)
    c = c.dropna(axis=1, how="all")
    v = v.reindex(columns=c.columns)
    if c.empty or c.shape[0] < 5:
        return None
    return c, v


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

    cv = _clean_session(closes, volumes, target)
    if cv is None:
        return None, None, target, "no_data", False
    c, v = cv
    is_today = (target == now_market(market).date())
    return c, v, target, "ok", is_today


# 여러 날 세션을 한 번에 받아 캐시(랭킹/대량추출용). (market, days) -> (fetched_at, sessions)
_sessions_cache: dict = {}
_SESSIONS_TTL = 1800.0


def _download_1m_chunked(tickers, start_date: dt.date, end_date: dt.date):
    """yfinance 1분봉은 요청당 최대 ~8일이라, 7일씩 끊어 받아 이어붙인다.
    start_date(포함)~end_date(미포함) 범위. 반환: 정렬·중복제거된 raw DataFrame 또는 None."""
    import yfinance as yf

    frames = []
    cur = start_date
    while cur < end_date:
        chunk_end = min(cur + dt.timedelta(days=7), end_date)
        raw = yf.download(tickers, start=cur.isoformat(), end=chunk_end.isoformat(),
                          interval="1m", auto_adjust=True, progress=False, group_by="column")
        if raw is not None and not raw.empty:
            frames.append(raw)
        cur = chunk_end
    if not frames:
        return None
    raw = pd.concat(frames)
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    return raw


def load_sessions(market: str, days: int = 30, tickers: list[str] | None = None,
                  use_cache: bool = True):
    """최근 days 일치(달력 기준) 1분봉을 한 번에 받아 '날짜별 완료 세션'으로 분해한다.

    yfinance 1분봉 한계(약 30일) 안에서 받을 수 있는 모든 거래일을 돌려준다.
    반환: [(session_date, closes, volumes), ...] 오래된 날 → 최신 날 순.
          (오늘 진행 중 세션도 포함될 수 있으니 호출 측에서 필요 시 제외)
    """
    key = (market, days)
    if use_cache:
        ent = _sessions_cache.get(key)
        if ent and (time.time() - ent[0]) < _SESSIONS_TTL:
            return ent[1]

    m = config.MARKETS[market]
    tickers = tickers or m["universe"]
    tz = market_tz(market)
    today = now_market(market).date()
    start = today - dt.timedelta(days=days)
    end = today + dt.timedelta(days=1)

    raw = _download_1m_chunked(tickers, start, end)
    if raw is None or raw.empty:
        return []

    closes, volumes = _split_panels(raw, tickers)
    idx = pd.to_datetime(closes.index)
    idx = idx.tz_localize(tz) if idx.tz is None else idx.tz_convert(tz)
    closes.index = idx
    volumes.index = idx

    out = []
    for d in sorted({ts.date() for ts in idx}):
        cv = _clean_session(closes, volumes, d)
        if cv is not None:
            out.append((d, cv[0], cv[1]))

    if use_cache:
        _sessions_cache[key] = (time.time(), out)
    return out
