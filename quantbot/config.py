"""전역 설정: 시장(미장/국장)별 기술주 유니버스·거래시간·자본·거래비용."""
from __future__ import annotations

import os

# --- 거래 비용 (실제 환경 근사) ---
COMMISSION_BPS = 5.0                 # 체결 명목금액 대비 수수료 (basis point, 5 = 0.05%)
SLIPPAGE_BPS = 5.0                   # 슬리피지 (체결가 불리하게 적용)
ALLOW_FRACTIONAL = True              # 소수점 주식 허용 (False면 정수 주식만)
BORROW_RATE = 0.08                   # 레버리지 차입 연이자율 (마진 봇에 적용)

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.04

# --- 리플레이(장 마감 시간대) ---
REPLAY_START_BARS = 20               # 리플레이 시작 시 보여줄 분봉 수(워밍업 확보)
REPLAY_BARS_PER_SEC = 1.0            # 실시간 1초당 진행할 세션 분봉 수(체감 속도)

# --- 미국 기술주(미장) 유니버스 ---
US_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "AVGO", "QCOM", "INTC", "MU", "TXN", "ASML",
    "CRM", "ORCL", "ADBE", "NOW", "SNOW", "PLTR",
    "CSCO", "NFLX", "SHOP", "UBER", "AMAT",
]

# --- 국내 기술주(국장) 유니버스 (KOSPI .KS / KOSDAQ .KQ) ---
KR_UNIVERSE = [
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "035420.KS",  # NAVER
    "035720.KS",  # 카카오
    "066570.KS",  # LG전자
    "006400.KS",  # 삼성SDI
    "373220.KS",  # LG에너지솔루션
    "034220.KS",  # LG디스플레이
    "009150.KS",  # 삼성전기
    "042700.KS",  # 한미반도체
    "402340.KS",  # SK스퀘어
    "036570.KS",  # 엔씨소프트
    "259960.KS",  # 크래프톤
    "251270.KS",  # 넷마블
    "263750.KQ",  # 펄어비스
    "293490.KQ",  # 카카오게임즈
    "058470.KQ",  # 리노공업
    "240810.KQ",  # 원익IPS
]

# 종목 표시 이름 (국내 종목은 한글명, 미국은 티커 그대로 사용)
NAMES = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "035420.KS": "NAVER",
    "035720.KS": "카카오", "066570.KS": "LG전자", "006400.KS": "삼성SDI",
    "373220.KS": "LG에너지솔루션", "034220.KS": "LG디스플레이", "009150.KS": "삼성전기",
    "042700.KS": "한미반도체", "402340.KS": "SK스퀘어", "036570.KS": "엔씨소프트",
    "259960.KS": "크래프톤", "251270.KS": "넷마블", "263750.KQ": "펄어비스",
    "293490.KQ": "카카오게임즈", "058470.KQ": "리노공업", "240810.KQ": "원익IPS",
}

# --- 시장 정의 ---
# open/close: (시, 분) 현지 거래시간. capital: 시장별 시작 가상자본. currency: 표시 통화.
MARKETS = {
    "us": {
        "label": "미국 기술주 (미장)", "short": "미장",
        "tz": "America/New_York", "open": (9, 30), "close": (16, 0),
        "universe": US_UNIVERSE, "capital": 10_000.0, "currency": "$",
        "open_kst": "22:30", "close_kst": "05:00",
    },
    "kr": {
        "label": "국내 기술주 (국장)", "short": "국장",
        "tz": "Asia/Seoul", "open": (9, 0), "close": (15, 30),
        "universe": KR_UNIVERSE, "capital": 10_000_000.0, "currency": "₩",
        "open_kst": "09:00", "close_kst": "15:30",
    },
}
DEFAULT_MARKET = "us"


def display_name(ticker: str) -> str:
    return NAMES.get(ticker, ticker)


# --- 경로 ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data_cache")
RESULTS_DIR = os.path.join(ROOT, "results")
