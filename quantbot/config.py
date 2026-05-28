"""전역 설정: 종목 유니버스(기술주 중심), 자본금, 기간, 거래비용."""
from __future__ import annotations

import os

# --- 가상 자산 ---
INITIAL_CAPITAL = 10_000.0           # 각 봇의 시작 가상 자본 (USD, 하루 단타 한도)

# --- 거래 비용 (실제 환경 근사) ---
COMMISSION_BPS = 5.0                 # 체결 명목금액 대비 수수료 (basis point, 5 = 0.05%)
SLIPPAGE_BPS = 5.0                   # 슬리피지 (체결가 불리하게 적용)
ALLOW_FRACTIONAL = True              # 소수점 주식 허용 (False면 정수 주식만)
BORROW_RATE = 0.08                   # 레버리지 차입 연이자율 (마진 봇에 적용)

# --- 시뮬레이션 기간 ---
# 실제 시장 데이터(yfinance)를 사용. 기본은 최근 약 3년.
START_DATE = "2022-01-01"
END_DATE = None                      # None이면 오늘까지

# --- 기술주 중심 유니버스 ---
# 대형 기술주 + 반도체 + 성장 기술주를 섞어 종목 선정 전략이 의미를 갖도록 구성.
TECH_UNIVERSE = [
    # 빅테크
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # 반도체
    "AMD", "AVGO", "QCOM", "INTC", "MU", "TXN", "ASML",
    # 소프트웨어 / 클라우드
    "CRM", "ORCL", "ADBE", "NOW", "SNOW", "PLTR",
    # 네트워크 / 기타 기술
    "CSCO", "NFLX", "SHOP", "UBER", "AMAT",
]

# --- 경로 ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data_cache")
RESULTS_DIR = os.path.join(ROOT, "results")

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.04                # 연 무위험 수익률 (Sharpe 계산용)
