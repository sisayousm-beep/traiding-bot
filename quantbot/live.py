"""실시간 클립 / 리플레이 제어.

today 모드에서:
  - 장중(open)이고 세션이 오늘이면 → 현재 시각까지의 분봉만 노출(진짜 실시간).
  - 장 마감/주말 등으로 라이브가 불가하면 → 최근 세션을 분 단위로 '리플레이'.
    리플레이 커서는 실제 경과 시간에 따라 증가하므로, 새로고침할수록 장이 펼쳐진다.
prev 모드: 완료된 직전 세션 전체(백테스트).

view()는 보여줄 분봉 수 k, 종가청산 여부 flatten, 표시 메타를 돌려준다.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from . import config
from .intraday_data import market_status, now_market

# (market, mode, session) -> {"start": datetime, "base": int}
_replay: dict = {}


def view(market: str, mode: str, closes_full: pd.DataFrame,
         session_date, is_today: bool) -> dict:
    total = len(closes_full)
    status = market_status(market)

    if mode == "prev":
        return {"k": total, "flatten": True, "kind": "backtest",
                "label": "전날 장 — 완료 세션 백테스트",
                "market_status": status, "total": total}

    # --- today ---
    if is_today and status == "open":
        now = now_market(market)
        k = int((closes_full.index <= now).sum()) or 1
        return {"k": min(k, total), "flatten": False, "kind": "live",
                "label": "🔴 LIVE — 장중 실시간",
                "market_status": status, "total": total}

    # --- 장 마감/프리마켓 → 최근 세션 리플레이 ---
    key = (market, mode, str(session_date))
    st = _replay.get(key)
    now_wall = dt.datetime.now()
    if st is None:
        st = {"start": now_wall, "base": config.REPLAY_START_BARS}
        _replay[key] = st
    elapsed = (now_wall - st["start"]).total_seconds()
    k = int(st["base"] + elapsed * config.REPLAY_BARS_PER_SEC)
    k = max(config.REPLAY_START_BARS, min(k, total))
    return {"k": k, "flatten": k >= total, "kind": "replay",
            "label": "📼 리플레이 — 최근 세션 재생 (장 마감 시간대)",
            "market_status": status, "total": total}


def reset(market: str | None = None) -> None:
    """리플레이 커서 초기화(처음부터 다시 재생)."""
    if market is None:
        _replay.clear()
    else:
        for kk in [k for k in _replay if k[0] == market]:
            _replay.pop(kk, None)
