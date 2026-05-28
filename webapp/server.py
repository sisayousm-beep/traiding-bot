"""당일 단타 봇 경쟁 — 시각화 웹 서버 (Flask).

시장(미장 us / 국장 kr) × 모드(전날 prev / 오늘 today)를 각각 독립 시뮬레이션.
today 모드는 장중이면 실시간(현재 시각까지), 장 마감 시간대면 리플레이.

엔드포인트:
  GET  /                                  대시보드
  GET  /api/results?market=&mode=         결과(JSON)
  POST /api/refresh?market=&mode=         최신 1분봉 재수신 후 재계산
"""
from __future__ import annotations

import datetime as dt
import threading
import time
import traceback

from flask import Flask, jsonify, render_template, request

from flask import Response

from quantbot import config, live
from quantbot.intraday_data import load_session, now_market
from quantbot.intraday_engine import run_intraday
from quantbot.intraday_metrics import to_payload
from quantbot.report import (
    bulk_reports, market_report, ranking_report, score_report,
    report_to_csv, report_to_jsonl, reports_to_flat_csv, reports_to_jsonl,
)
from quantbot.strategies_intraday import default_bots

app = Flask(__name__)
_lock = threading.Lock()

# 전날 장(prev)은 완료된 정적 세션이라 매 타임랩스 프레임마다 재다운로드할 필요가 없다.
# (market, mode) -> (fetched_at, load_session 결과)로 캐시해 타임랩스를 매끄럽게 한다.
_session_cache: dict = {}
_SESSION_TTL = 1800.0          # prev 세션 캐시 유효시간(초)


def _load_session_cached(market: str, mode: str, date: str | None = None):
    """완료된 세션(전날 prev / 지난 날짜 선택)은 캐시, 오늘(실시간)은 항상 새로 받는다."""
    today = now_market(market).date()
    is_static = (date is not None and dt.date.fromisoformat(date) < today) or \
                (date is None and mode == "prev")
    key = (market, mode, str(date))
    if is_static:
        ent = _session_cache.get(key)
        if ent and (time.time() - ent[0]) < _SESSION_TTL:
            return ent[1]
    data = load_session(market, mode, date=date)
    if is_static and data[3] == "ok":
        _session_cache[key] = (time.time(), data)
    return data


def _view_for(market, mode, date, c_full, sess, is_today):
    """선택 날짜가 있으면 그 날의 완료 세션(또는 오늘이면 실시간)으로 뷰를 만든다."""
    if date is not None:
        vw = live.view(market, "today" if is_today else "prev", c_full, sess, is_today)
        if not is_today:
            vw = {**vw, "kind": "date", "label": f"📅 {sess} — 지난 장 (날짜 선택)"}
        return vw
    return live.view(market, mode, c_full, sess, is_today)


def _compute(market: str, mode: str, date: str | None = None) -> dict:
    """시세 재수신 + 재계산. 어떤 오류가 나도 절대 예외를 밖으로 던지지 않고
    항상 JSON 페이로드를 돌려준다(자동 갱신 루프가 멈추지 않도록)."""
    ts = dt.datetime.now().strftime("%H:%M:%S")
    with _lock:
        m = config.MARKETS[market]
        meta_base = {"market": market, "market_label": m["label"],
                     "market_short": m["short"], "mode": mode,
                     "open_kst": m["open_kst"], "close_kst": m["close_kst"]}
        try:
            c_full, v_full, sess, status, is_today = _load_session_cached(market, mode, date)
            if status != "ok":
                msg = {"no_session": "해당 날짜/세션 데이터가 없습니다(주말/연휴/장 시작 전, 또는 30일 초과).",
                       "no_data": "해당 세션 1분봉을 받지 못했습니다."}.get(status, status)
                print(f"[{ts}] 갱신 {market}/{mode} date={date} → status={status} (데이터 없음)", flush=True)
                payload = {"error": msg, "status": status,
                           "meta": {**meta_base, "session_date": str(sess) if sess else None}}
            else:
                vw = _view_for(market, mode, date, c_full, sess, is_today)
                k = vw["k"]
                c = c_full.iloc[:k]
                v = v_full.iloc[:k]
                res = run_intraday(default_bots(), c, v, m["capital"], flatten_eod=vw["flatten"])
                payload = to_payload(res, c, sess, market, mode, m["capital"], vw)
                print(f"[{ts}] 갱신 {market}/{mode} date={date} → {vw['kind']} {k}/{vw['total']}분 (정상)",
                      flush=True)
        except Exception as e:                       # noqa: BLE001 — 루프 보호용 광범위 캐치
            traceback.print_exc()
            print(f"[{ts}] 갱신 {market}/{mode} → 예외 발생: {e} (다음 주기에 재시도)", flush=True)
            payload = {"error": f"데이터 수신/계산 중 오류가 발생했습니다: {e}",
                       "status": "exception",
                       "meta": {**meta_base, "session_date": None}}
        payload["meta"]["computed_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return payload


def _report(market: str, mode: str, date: str | None = None) -> dict:
    """현재 보이는 세션(실시간 클립 / 전날 / 선택 날짜)에 대한 봇별 분석 보고서."""
    with _lock:
        m = config.MARKETS[market]
        try:
            c_full, v_full, sess, status, is_today = _load_session_cached(market, mode, date)
            if status != "ok":
                return {"error": "세션 데이터가 없어 보고서를 만들 수 없습니다.", "status": status,
                        "meta": {"market": market, "mode": mode}}
            vw = _view_for(market, mode, date, c_full, sess, is_today)
            k = vw["k"]
            c = c_full.iloc[:k]
            v = v_full.iloc[:k]
            res = run_intraday(default_bots(), c, v, m["capital"], flatten_eod=vw["flatten"])
            return market_report(res, market, mode, sess, m["capital"], vw,
                                 closes=c, volumes=v)
        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            return {"error": f"보고서 생성 중 오류: {e}", "status": "exception",
                    "meta": {"market": market, "mode": mode}}


def _params():
    market = request.args.get("market", config.DEFAULT_MARKET)
    if market not in config.MARKETS:
        market = config.DEFAULT_MARKET
    mode = request.args.get("mode", "today")
    mode = mode if mode in ("prev", "today") else "today"
    date = request.args.get("date")
    if date:
        try:
            dt.date.fromisoformat(date)        # YYYY-MM-DD 검증
        except (TypeError, ValueError):
            date = None
    else:
        date = None
    return market, mode, date


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/results")
def api_results():
    market, mode, date = _params()
    return jsonify(_compute(market, mode, date))


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    market, mode, date = _params()
    return jsonify(_compute(market, mode, date))


@app.route("/api/report")
def api_report():
    market, mode, date = _params()
    rep = _report(market, mode, date)
    fmt = request.args.get("format")
    if fmt in ("csv", "jsonl") and "error" not in rep:
        meta = rep.get("meta", {})
        base = f"report_{meta.get('market','')}_{meta.get('mode','')}_{meta.get('session_date','')}"
        if fmt == "jsonl":                            # AI 학습용 (세션당 봇별 1줄)
            return Response(report_to_jsonl(rep), mimetype="application/x-ndjson",
                            headers={"Content-Disposition": f"attachment; filename={base}.jsonl"})
        return Response(report_to_csv(rep), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={base}.csv"})
    return jsonify(rep)


def _markets_param() -> list[str]:
    """markets=kr,us 형태(콤마구분) 또는 단일 market= 파라미터를 리스트로."""
    raw = request.args.get("markets") or request.args.get("market") or config.DEFAULT_MARKET
    out = [m.strip() for m in raw.split(",") if m.strip() in config.MARKETS]
    return out or [config.DEFAULT_MARKET]


def _days_param(default: int = 30) -> int:
    try:
        d = int(request.args.get("days", default))
    except (TypeError, ValueError):
        d = default
    return max(2, min(d, 30))            # yfinance 1분봉 한계 ~30일


@app.route("/api/ranking")
def api_ranking():
    """전일 기준 N일간 완료 세션들로 봇 종합 랭킹(평균 순위·수익률)."""
    markets = _markets_param()
    days = _days_param()
    ts = dt.datetime.now().strftime("%H:%M:%S")
    with _lock:
        try:
            rep = ranking_report(markets, days=days)
            print(f"[{ts}] 랭킹 {markets} {days}일 → {rep['meta']['n_sessions']}세션", flush=True)
            return jsonify(rep)
        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            return jsonify({"error": f"랭킹 생성 중 오류: {e}", "status": "exception"})


@app.route("/api/score")
def api_score():
    """시장 보정 성능점수. group=normal(국장+미장) | hot(급등 국장+미장)."""
    group = request.args.get("group", "normal")
    if group not in ("normal", "hot"):
        group = "normal"
    days = _days_param(7)
    ts = dt.datetime.now().strftime("%H:%M:%S")
    with _lock:
        try:
            rep = score_report(group, days=days)
            print(f"[{ts}] 성능점수 {group} {days}일 → {rep.get('meta',{}).get('n_sessions')}세션",
                  flush=True)
            return jsonify(rep)
        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            return jsonify({"error": f"성능점수 생성 중 오류: {e}", "status": "exception"})


@app.route("/api/bulk_report")
def api_bulk_report():
    """여러 시장 × 여러 날 보고서를 한 번에. format=jsonl(기본 다운로드)|csv|json."""
    markets = _markets_param()
    days = _days_param()
    fmt = request.args.get("format", "jsonl")
    bot = request.args.get("bot")                     # 특정 봇만 추출(없으면 전체)
    ts = dt.datetime.now().strftime("%H:%M:%S")
    with _lock:
        try:
            reports = bulk_reports(markets, days=days)
            if bot:                                   # 봇 1개만 남기고 빈 세션 제거
                reports = [{**r, "bots": [b for b in r.get("bots", []) if b.get("name") == bot]}
                           for r in reports]
                reports = [r for r in reports if r["bots"]]
            n_lines = sum(len(r.get("bots", [])) for r in reports)
            print(f"[{ts}] 대량추출 {markets} {days}일 bot={bot or '전체'} → {len(reports)}세션 {n_lines}행",
                  flush=True)
            base = f"bulk_{'-'.join(markets)}_{days}d" + (f"_{bot}" if bot else "")
            if fmt == "csv":
                return Response(reports_to_flat_csv(reports), mimetype="text/csv",
                                headers={"Content-Disposition": f"attachment; filename={base}.csv"})
            if fmt == "json":
                return jsonify({"meta": {"markets": markets, "days": days,
                                         "n_sessions": len(reports), "n_rows": n_lines},
                                "reports": reports})
            return Response(reports_to_jsonl(reports), mimetype="application/x-ndjson",
                            headers={"Content-Disposition": f"attachment; filename={base}.jsonl"})
        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            return jsonify({"error": f"대량 추출 중 오류: {e}", "status": "exception"})


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()
    url = f"http://{'127.0.0.1' if args.host=='0.0.0.0' else args.host}:{args.port}"
    print(f"대시보드: {url}")
    if args.open:
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
