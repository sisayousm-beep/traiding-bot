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
from quantbot.intraday_data import load_session
from quantbot.intraday_engine import run_intraday
from quantbot.intraday_metrics import to_payload
from quantbot.report import market_report, report_to_csv
from quantbot.strategies_intraday import default_bots

app = Flask(__name__)
_lock = threading.Lock()

# 전날 장(prev)은 완료된 정적 세션이라 매 타임랩스 프레임마다 재다운로드할 필요가 없다.
# (market, mode) -> (fetched_at, load_session 결과)로 캐시해 타임랩스를 매끄럽게 한다.
_session_cache: dict = {}
_SESSION_TTL = 1800.0          # prev 세션 캐시 유효시간(초)


def _load_session_cached(market: str, mode: str):
    """today는 항상 새로 받고(실시간), prev는 캐시(타임랩스 재생용)."""
    if mode != "prev":
        return load_session(market, mode)
    key = (market, mode)
    ent = _session_cache.get(key)
    if ent and (time.time() - ent[0]) < _SESSION_TTL:
        return ent[1]
    data = load_session(market, mode)
    if data[3] == "ok":        # status == ok 일 때만 캐시
        _session_cache[key] = (time.time(), data)
    return data


def _compute(market: str, mode: str, upto: int | None = None) -> dict:
    """시세 재수신 + 재계산. 어떤 오류가 나도 절대 예외를 밖으로 던지지 않고
    항상 JSON 페이로드를 돌려준다(자동 갱신 루프가 멈추지 않도록).

    upto: prev 모드 타임랩스용. '세션 첫 upto분까지'만 노출해 그 시점 상태를 재현한다.
    """
    ts = dt.datetime.now().strftime("%H:%M:%S")
    with _lock:
        m = config.MARKETS[market]
        meta_base = {"market": market, "market_label": m["label"],
                     "market_short": m["short"], "mode": mode,
                     "open_kst": m["open_kst"], "close_kst": m["close_kst"]}
        try:
            c_full, v_full, sess, status, is_today = _load_session_cached(market, mode)
            if status != "ok":
                msg = {"no_session": "직전 세션 데이터가 아직 없습니다(주말/연휴/장 시작 전).",
                       "no_data": "해당 세션 1분봉을 받지 못했습니다."}.get(status, status)
                print(f"[{ts}] 갱신 {market}/{mode} → status={status} (데이터 없음)", flush=True)
                payload = {"error": msg, "status": status,
                           "meta": {**meta_base, "session_date": str(sess) if sess else None}}
            else:
                vw = live.view(market, mode, c_full, sess, is_today)
                # 타임랩스: prev 모드에서 upto가 오면 '첫 upto분'으로 클리핑
                if mode == "prev" and upto is not None:
                    total = vw["total"]
                    k = max(2, min(int(upto), total))
                    vw = {**vw, "k": k, "flatten": k >= total,
                          "kind": "timelapse",
                          "label": ("📼 타임랩스 — 전날 장 재생"
                                    if k < total else "✅ 전날 장 — 종료(종가 청산)")}
                k = vw["k"]
                c = c_full.iloc[:k]
                v = v_full.iloc[:k]
                res = run_intraday(default_bots(), c, v, m["capital"], flatten_eod=vw["flatten"])
                payload = to_payload(res, c, sess, market, mode, m["capital"], vw)
                print(f"[{ts}] 갱신 {market}/{mode} → {vw['kind']} {k}/{vw['total']}분 (정상)",
                      flush=True)
        except Exception as e:                       # noqa: BLE001 — 루프 보호용 광범위 캐치
            traceback.print_exc()
            print(f"[{ts}] 갱신 {market}/{mode} → 예외 발생: {e} (다음 주기에 재시도)", flush=True)
            payload = {"error": f"데이터 수신/계산 중 오류가 발생했습니다: {e}",
                       "status": "exception",
                       "meta": {**meta_base, "session_date": None}}
        payload["meta"]["computed_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return payload


def _report(market: str, mode: str) -> dict:
    """현재 보이는 세션(실시간 클립 또는 전날 전체)에 대한 봇별 분석 보고서."""
    with _lock:
        m = config.MARKETS[market]
        try:
            c_full, v_full, sess, status, is_today = _load_session_cached(market, mode)
            if status != "ok":
                return {"error": "세션 데이터가 없어 보고서를 만들 수 없습니다.", "status": status,
                        "meta": {"market": market, "mode": mode}}
            vw = live.view(market, mode, c_full, sess, is_today)
            k = vw["k"]
            c = c_full.iloc[:k]
            v = v_full.iloc[:k]
            res = run_intraday(default_bots(), c, v, m["capital"], flatten_eod=vw["flatten"])
            return market_report(res, market, mode, sess, m["capital"], vw)
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
    upto_raw = request.args.get("upto")
    upto = None
    if upto_raw is not None:
        try:
            upto = int(upto_raw)
        except (TypeError, ValueError):
            upto = None
    return market, mode, upto


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/results")
def api_results():
    market, mode, upto = _params()
    return jsonify(_compute(market, mode, upto))


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    market, mode, upto = _params()
    return jsonify(_compute(market, mode, upto))


@app.route("/api/report")
def api_report():
    market, mode, _ = _params()
    rep = _report(market, mode)
    if request.args.get("format") == "csv" and "error" not in rep:
        meta = rep.get("meta", {})
        fname = f"report_{meta.get('market','')}_{meta.get('mode','')}_{meta.get('session_date','')}.csv"
        return Response(report_to_csv(rep), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})
    return jsonify(rep)


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
