"""개발용 백테스트 하네스 — yfinance 세션을 디스크에 캐시하고, 봇 로스터를
여러 시장×여러 날에 돌려 봇별 핵심 지표(알파/수익/고점/낙폭/회전)를 집계한다.

사용:
  python bt_harness.py fetch          # 세션 다운로드 → data_cache/sessions_*.pkl
  python bt_harness.py eval           # 현재 default_bots() 평가
"""
from __future__ import annotations

import pickle
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

CACHE = Path("data_cache")
MARKETS = ["kr", "us", "kr_hot", "us_hot"]


def _pkl(market: str) -> Path:
    return CACHE / f"sessions_{market}_30d.pkl"


def fetch(markets=MARKETS, days: int = 30) -> None:
    from quantbot.intraday_data import load_sessions, now_market
    CACHE.mkdir(exist_ok=True)
    for market in markets:
        today = now_market(market).date()
        sess = [(d, c, v) for d, c, v in load_sessions(market, days=days) if d < today]
        with open(_pkl(market), "wb") as f:
            pickle.dump(sess, f)
        print(f"{market:8} cached {len(sess)} sessions -> {_pkl(market)}")


def load(market: str):
    with open(_pkl(market), "rb") as f:
        return pickle.load(f)


def evaluate(bots_factory, markets=MARKETS) -> dict:
    """bots_factory(): 매 세션 새 봇 리스트 반환. 봇별 세션 레코드 집계 반환."""
    from quantbot.intraday_engine import run_intraday
    from quantbot.market_eval import evaluate_market
    from quantbot.report import bot_report
    from quantbot import config

    recs = defaultdict(list)  # bot -> list of dict
    for market in markets:
        base = market.replace("_hot", "")  # kr_hot/us_hot 의 capital 은 base 시장 설정 사용
        cap = config.MARKETS.get(market, config.MARKETS[base])["capital"]
        for d, c, v in load(market):
            mev = evaluate_market(c, v, base, d)
            mret = mev["market_return"]
            res = run_intraday(bots_factory(), c, v, cap, flatten_eod=True)
            for r in res:
                br = bot_report(r, cap)
                dr = br["daily_return"] or 0.0
                recs[r.name].append({
                    "market": market, "date": str(d), "regime": mev["regime"],
                    "ret": dr, "alpha": dr - (mret or 0.0),
                    "peak": br["peak_gain"] or 0.0, "mdd": br["max_drawdown"] or 0.0,
                    "turnover": br["turnover"] or 0.0, "n_trades": br["n_trades"],
                    "win_rate": br["win_rate"], "pf": br["profit_factor"],
                })
    return recs


def summarize(recs: dict, regimes=("strong_bull", "bull", "flat", "bear", "strong_bear")):
    print(f"{'bot':10} {'n':>3} {'ret%':>7} {'alpha%':>7} {'win':>6} {'peak%':>6} {'mdd%':>7} {'turn':>6} {'trd':>5}")
    for bot in sorted(recs):
        rs = recs[bot]
        ret = [x["ret"] for x in rs]
        win = sum(1 for x in ret if x > 0)
        print(f"{bot:10} {len(rs):>3} {st.mean(ret)*100:>7.3f} "
              f"{st.mean([x['alpha'] for x in rs])*100:>7.3f} {win:>3}/{len(rs):<2} "
              f"{st.mean([x['peak'] for x in rs])*100:>6.2f} {st.mean([x['mdd'] for x in rs])*100:>7.2f} "
              f"{st.mean([x['turnover'] for x in rs]):>6.2f} {st.mean([x['n_trades'] for x in rs]):>5.0f}")
    print("\nalpha% by regime:")
    print(f"{'bot':10}" + "".join(f"{rg:>13}" for rg in regimes))
    for bot in sorted(recs):
        byr = defaultdict(list)
        for x in recs[bot]:
            byr[x["regime"]].append(x["alpha"])
        print(f"{bot:10}" + "".join(
            f"{(st.mean(byr[rg])*100 if byr[rg] else 0):>13.3f}" for rg in regimes))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if cmd == "fetch":
        fetch()
    else:
        from quantbot.strategies_intraday import default_bots
        mk = sys.argv[2:] or MARKETS
        summarize(evaluate(default_bots, mk), )
