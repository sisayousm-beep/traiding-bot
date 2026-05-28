"""기술주 당일 단타 봇 경쟁 (CLI).

시장(미장 us / 국장 kr) × 모드(전날 prev / 오늘 today)를 각각 시뮬레이션.
각 봇은 $10,000(미장)/₩10,000,000(국장) 가상자본으로 당일 단타를 벌여 하루 수익률을 겨룬다.

사용법:
  python main.py --market kr               # 국장, 오늘(실시간/리플레이)
  python main.py --market us --mode prev   # 미장, 전날 장
  python main.py --market kr --live        # 국장 실시간 반복 갱신
"""
from __future__ import annotations

import argparse
import datetime as dt
import time

from quantbot import config, live
from quantbot.intraday_data import load_session, market_status
from quantbot.intraday_engine import run_intraday
from quantbot.intraday_metrics import leaderboard
from quantbot.strategies_intraday import default_bots


def _money(v, cur):
    return (("₩" if cur == "₩" else "$") + f"{round(v):,}")


def run_once(market: str, mode: str) -> None:
    m = config.MARKETS[market]
    print(f"[{dt.datetime.now():%H:%M:%S}] {m['short']}/{mode} — 1분봉 로딩…")
    c, v, sess, status, is_today = load_session(market, mode)
    if status != "ok":
        print(f"  데이터 없음({status}). {m['label']} 개장(한국시간) {m['open_kst']}~{m['close_kst']}.")
        return
    vw = live.view(market, mode, c, sess, is_today)
    c = c.iloc[:vw["k"]]; v = v.iloc[:vw["k"]]
    res = run_intraday(default_bots(), c, v, m["capital"], flatten_eod=vw["flatten"])
    cur = m["currency"]
    print(f"  {vw['label']} · 세션 {sess} · {c.shape[0]}/{vw['total']}분 · 현재 {c.index[-1]:%H:%M} "
          f"· 장상태 {market_status(market)} · 시작자본 {_money(m['capital'], cur)}")
    print(f"\n  {'순위':<4}{'봇':<10}{'하루수익':>9}{'고점':>8}{'최대낙폭':>9}{'매매':>6}  설명")
    for r in leaderboard(res, m["capital"]):
        lev = f" {int(r['leverage'])}x" if r["leverage"] > 1 else ""
        bust = " [청산]" if r["bankrupt"] else ""
        print(f"  #{r['rank']:<3}{r['name']+lev:<10}{r['DailyReturn']*100:>+8.2f}%"
              f"{r['PeakGain']*100:>+7.2f}%{r['MaxDrawdown']*100:>+8.2f}%{r['n_trades']:>6}  "
              f"{r['tagline']}{bust}")


def main() -> None:
    ap = argparse.ArgumentParser(description="당일 단타 봇 경쟁 (국장/미장)")
    ap.add_argument("--market", choices=["us", "kr"], default="kr")
    ap.add_argument("--mode", choices=["prev", "today"], default="today")
    ap.add_argument("--live", action="store_true", help="반복 갱신(실시간/리플레이)")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    if args.live:
        print(f"실시간 모드({args.market}/{args.mode}). Ctrl+C로 종료.")
        try:
            while True:
                run_once(args.market, args.mode)
                print("=" * 72)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n종료.")
    else:
        run_once(args.market, args.mode)


if __name__ == "__main__":
    main()
