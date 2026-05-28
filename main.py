"""기술주 당일 단타 봇 경쟁 (CLI).

실제 1분봉 데이터로 여러 전략 봇이 $10,000 가상자본으로 당일 단타를 벌여
'하루 수익률'을 겨룬다. 두 모드를 따로 돌릴 수 있다:
  prev  : 전날 장(직전 세션) 백테스트
  today : 오늘(최근) 세션 — 장중 실시간 정보

사용법:
  python main.py                      # today 모드 1회
  python main.py --mode prev          # 전날 장
  python main.py --mode today --live  # 오늘 세션 실시간 반복 갱신
"""
from __future__ import annotations

import argparse
import datetime as dt
import time

from quantbot import config
from quantbot.intraday_data import load_intraday
from quantbot.intraday_engine import run_intraday
from quantbot.intraday_metrics import leaderboard
from quantbot.strategies_intraday import default_bots


def run_once(mode: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {mode} 모드 — 1분봉 로딩…")
    c, v, sess, status = load_intraday(mode)
    if status != "ok":
        print(f"  데이터 없음({status}). 미국 장 시간(한국 22:30~05:00)에 다시 시도하세요.")
        return
    print(f"  세션 {sess} · {c.shape[0]}분봉 · {c.shape[1]}종목 · 시작자본 ${config.INITIAL_CAPITAL:,.0f}")
    res = run_intraday(default_bots(), c, v, config.INITIAL_CAPITAL)
    print(f"\n  {'순위':<4}{'봇':<10}{'하루수익':>9}{'고점':>8}{'최대낙폭':>9}{'매매':>6}  설명")
    for r in leaderboard(res, config.INITIAL_CAPITAL):
        lev = f" {int(r['leverage'])}x" if r["leverage"] > 1 else ""
        bust = " [청산]" if r["bankrupt"] else ""
        print(f"  #{r['rank']:<3}{r['name']+lev:<10}{r['DailyReturn']*100:>+8.2f}%"
              f"{r['PeakGain']*100:>+7.2f}%{r['MaxDrawdown']*100:>+8.2f}%{r['n_trades']:>6}  "
              f"{r['tagline']}{bust}")


def main() -> None:
    ap = argparse.ArgumentParser(description="당일 단타 봇 경쟁")
    ap.add_argument("--mode", choices=["prev", "today"], default="today")
    ap.add_argument("--live", action="store_true", help="반복 갱신(실시간)")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    if args.live:
        print(f"실시간 모드({args.mode}). Ctrl+C로 종료.")
        try:
            while True:
                run_once(args.mode)
                print("=" * 70)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n종료.")
    else:
        run_once(args.mode)


if __name__ == "__main__":
    main()
