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

from flask import Flask, jsonify, render_template, request

from quantbot import config, live
from quantbot.intraday_data import load_session
from quantbot.intraday_engine import run_intraday
from quantbot.intraday_metrics import to_payload
from quantbot.strategies_intraday import default_bots

app = Flask(__name__)
_lock = threading.Lock()


def _compute(market: str, mode: str) -> dict:
    with _lock:
        m = config.MARKETS[market]
        c_full, v_full, sess, status, is_today = load_session(market, mode)
        if status != "ok":
            msg = {"no_session": "직전 세션 데이터가 아직 없습니다(주말/연휴/장 시작 전).",
                   "no_data": "해당 세션 1분봉을 받지 못했습니다."}.get(status, status)
            payload = {"error": msg, "status": status,
                       "meta": {"market": market, "market_label": m["label"],
                                "market_short": m["short"], "mode": mode,
                                "open_kst": m["open_kst"], "close_kst": m["close_kst"],
                                "session_date": str(sess) if sess else None}}
        else:
            vw = live.view(market, mode, c_full, sess, is_today)
            k = vw["k"]
            c = c_full.iloc[:k]
            v = v_full.iloc[:k]
            res = run_intraday(default_bots(), c, v, m["capital"], flatten_eod=vw["flatten"])
            payload = to_payload(res, c, sess, market, mode, m["capital"], vw)
        payload["meta"]["computed_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return payload


def _params():
    market = request.args.get("market", config.DEFAULT_MARKET)
    if market not in config.MARKETS:
        market = config.DEFAULT_MARKET
    mode = request.args.get("mode", "today")
    return market, (mode if mode in ("prev", "today") else "today")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/results")
def api_results():
    return jsonify(_compute(*_params()))


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    return jsonify(_compute(*_params()))


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
