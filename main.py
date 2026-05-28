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
import os
import sys
import time

try:                                  # Windows 한글 콘솔(cp949)에서 이모지/em대시 출력 보장
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from quantbot import config, live
from quantbot.intraday_data import load_session, market_status
from quantbot.intraday_engine import run_intraday
from quantbot.intraday_metrics import leaderboard
from quantbot.report import market_report, report_to_csv
from quantbot.strategies_intraday import default_bots


def _money(v, cur):
    return (("₩" if cur == "₩" else "$") + f"{round(v):,}")


def _view(market, mode, date, c, sess, is_today):
    if date:
        vw = live.view(market, "today" if is_today else "prev", c, sess, is_today)
        return vw if is_today else {**vw, "label": f"📅 {sess} 지난 장(날짜 선택)"}
    return live.view(market, mode, c, sess, is_today)


def run_once(market: str, mode: str, date: str | None = None) -> None:
    m = config.MARKETS[market]
    print(f"[{dt.datetime.now():%H:%M:%S}] {m['short']}/{mode}{' '+date if date else ''} — 1분봉 로딩…")
    c, v, sess, status, is_today = load_session(market, mode, date=date)
    if status != "ok":
        print(f"  데이터 없음({status}). {m['label']} 개장(한국시간) {m['open_kst']}~{m['close_kst']}.")
        return
    vw = _view(market, mode, date, c, sess, is_today)
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


def run_report(market: str, mode: str, date: str | None = None) -> None:
    m = config.MARKETS[market]
    print(f"[{dt.datetime.now():%H:%M:%S}] {m['short']}/{mode}{' '+date if date else ''} — 결과 보고서 생성…")
    c, v, sess, status, is_today = load_session(market, mode, date=date)
    if status != "ok":
        print(f"  데이터 없음({status}).")
        return
    vw = _view(market, mode, date, c, sess, is_today)
    c = c.iloc[:vw["k"]]; v = v.iloc[:vw["k"]]
    res = run_intraday(default_bots(), c, v, m["capital"], flatten_eod=vw["flatten"])
    rep = market_report(res, market, mode, sess, m["capital"], vw, closes=c, volumes=v)
    cur = m["currency"]
    me = rep.get("market", {})
    if me.get("available"):
        print(f"\n  🌐 당일 장 평가: {me['regime_label']} ({me['regime_desc']})")
        print(f"     시장(등가중 매수보유) 하루수익 {_p(me['market_return'])}  "
              f"고점 {_p(me['peak_gain'])}  저점 {_p(me['trough'])}  "
              f"상승 {me['n_up']}/{me['n_tickers']}종목  흐름 {me['trend_shape']}")
    print(f"\n  ===== {m['label']} / {mode} / 세션 {sess} — 봇별 결과 보고서 =====")
    for b in rep["bots"]:
        print(f"\n  #{b['rank']} {b['name']}  ({b['tagline']})")
        print(f"    하루수익 {(_p(b['daily_return']))}  시장대비(알파) {_p(b.get('alpha'))} "
              f"[{b.get('vs_market','')}]")
        print(f"    매도실현 {(_p(b['realized_return']))} "
              f"({_money(b['realized_pnl'] or 0, cur)})  최종 {_money(b['final_equity'] or 0, cur)}")
        print(f"    고점 {_p(b['peak_gain'])}  최대낙폭 {_p(b['max_drawdown'])}  분변동성 {_p(b['intraday_vol'])}")
        print(f"    매매 {b['n_trades']}회(라운드트립 {b['n_round_trips']})  승률 {_p(b['win_rate'])}  "
              f"손익비 {_n(b['profit_factor'])}  기대값 {_money(b['expectancy'] or 0, cur)}")
        print(f"    평균보유 {_n(b['avg_hold_min'],0)}분  회전율 {_n(b['turnover'])}  총수수료 {_money(b['total_commission'] or 0, cur)}")
        if b["best_trade"]:
            bt = b["best_trade"]; wt = b["worst_trade"]
            print(f"    최고매매 {bt['name']} {_money(bt['pnl'] or 0, cur)} ({_p(bt['ret'])})  "
                  f"최악매매 {wt['name']} {_money(wt['pnl'] or 0, cur)} ({_p(wt['ret'])})")
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    path = os.path.join(config.RESULTS_DIR, f"report_{market}_{mode}_{sess}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(report_to_csv(rep))
    print(f"\n  CSV 저장: {path}")


def _p(v) -> str:
    return "–" if v is None else f"{v*100:+.2f}%"


def _n(v, d: int = 2) -> str:
    return "–" if v is None else f"{v:.{d}f}"


def main() -> None:
    ap = argparse.ArgumentParser(description="당일 단타 봇 경쟁 (국장/미장)")
    ap.add_argument("--market", choices=["us", "kr", "us_hot", "kr_hot"], default="kr")
    ap.add_argument("--mode", choices=["prev", "today"], default="today")
    ap.add_argument("--live", action="store_true", help="반복 갱신(실시간/리플레이)")
    ap.add_argument("--report", action="store_true", help="봇별 결과 보고서 출력 + CSV 저장")
    ap.add_argument("--date", default=None, help="지난 날짜 선택(YYYY-MM-DD, 최근 30일 내)")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    if args.report:
        run_report(args.market, args.mode, args.date)
    elif args.live:
        print(f"실시간 모드({args.market}/{args.mode}). Ctrl+C로 종료.")
        try:
            while True:
                run_once(args.market, args.mode, args.date)
                print("=" * 72)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n종료.")
    else:
        run_once(args.market, args.mode, args.date)


if __name__ == "__main__":
    main()
