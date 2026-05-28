"""당일 단타 봇 경쟁 — 시각화 웹 서버 (Flask).

두 모드를 따로 시뮬레이션:
  - prev  : 전날 장(직전 세션)으로 백테스트
  - today : 오늘(최근) 세션, 장중 실시간 정보 반영

엔드포인트:
  GET  /                       대시보드
  GET  /api/results?mode=...   해당 모드의 캐시된 결과(없으면 계산)
  POST /api/refresh?mode=...   최신 1분봉 재수신 후 재시뮬레이션
"""
from __future__ import annotations

import datetime as dt
import threading

from flask import Flask, jsonify, render_template, request

from quantbot import config
from quantbot.intraday_data import load_intraday
from quantbot.intraday_engine import run_intraday
from quantbot.intraday_metrics import to_payload
from quantbot.strategies_intraday import default_bots

app = Flask(__name__)

_lock = threading.Lock()
_cache: dict = {"prev": None, "today": None}


def _compute(mode: str) -> dict:
    with _lock:
        c, v, sess, status = load_intraday(mode)
        if status != "ok":
            msg = {"no_session": "직전 세션 데이터가 아직 없습니다(주말/장 시작 전).",
                   "no_data": "해당 세션의 1분봉 데이터를 받지 못했습니다."}.get(status, status)
            payload = {"error": msg, "status": status,
                       "meta": {"mode": mode, "session_date": str(sess) if sess else None}}
        else:
            res = run_intraday(default_bots(), c, v, config.INITIAL_CAPITAL)
            payload = to_payload(res, c, sess, mode, config.INITIAL_CAPITAL)
        payload["meta"]["computed_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _cache[mode] = payload
        return payload


def _mode() -> str:
    m = request.args.get("mode", "today")
    return m if m in ("prev", "today") else "today"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/results")
def api_results():
    m = _mode()
    return jsonify(_cache[m] if _cache[m] is not None else _compute(m))


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    return jsonify(_compute(_mode()))


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
