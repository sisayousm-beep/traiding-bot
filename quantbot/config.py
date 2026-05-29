"""전역 설정: 시장(미장/국장)별 기술주 유니버스·거래시간·자본·거래비용."""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

# 화면 표시는 사용자(한국) 기준 시간으로 통일. 미장도 한국시간(22:30~05:00)으로 보인다.
DISPLAY_TZ = ZoneInfo("Asia/Seoul")


def to_kst_hm(ts) -> str:
    """타임존이 붙은 타임스탬프를 한국시간 'HH:MM' 문자열로. (국장은 그대로)"""
    try:
        if ts.tzinfo is not None:
            ts = ts.astimezone(DISPLAY_TZ)
        return ts.strftime("%H:%M")
    except AttributeError:
        return str(ts)

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

# --- 미국 전섹터 대형주(us_all) 유니버스 — '기술주 한정' 해제, 11개 GICS 섹터 망라 ---
# 궁극의 퀀텀 봇(Mythos)이 '그 많은 종목 중 최적 상황'을 횡단면으로 고르는 넓은 풀.
# 섹터를 고루 담아야 종목선정 로직이 진짜 분산·저상관 기회를 찾을 수 있다(방어 우선).
US_ALL_UNIVERSE = [
    # 정보기술
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "CRM", "ORCL", "ADBE", "CSCO", "TXN", "QCOM", "ACN",
    # 커뮤니케이션
    "GOOGL", "META", "NFLX", "DIS", "CMCSA", "VZ",
    # 임의소비재
    "AMZN", "TSLA", "HD", "NKE", "MCD", "LOW", "SBUX",
    # 필수소비재
    "PG", "KO", "PEP", "COST", "WMT", "PM",
    # 금융
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "V", "MA", "AXP",
    # 헬스케어
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT",
    # 산업재
    "CAT", "BA", "HON", "GE", "UPS", "RTX", "DE",
    # 에너지·소재·유틸리티
    "XOM", "CVX", "COP", "LIN", "NEE",
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

# --- 미국 '급등주' 기술주(미장 급등주) 유니버스 ---
# 변동성·베타가 높은 모멘텀/테마 기술주(반도체 신성장·AI·전기차·핀테크·암호화폐 연동 등).
# 우량주 대비 장중 진폭이 크므로 같은 단타 전략이라도 손익이 훨씬 격렬하게 움직인다.
US_HOT_UNIVERSE = [
    "TSLA", "NVDA", "PLTR", "SMCI", "ARM", "COIN", "MSTR", "MARA", "RIOT",
    "AFRM", "SOFI", "RIVN", "LCID", "UPST", "IONQ", "RGTI", "SOUN", "BBAI",
    "CVNA", "HOOD", "DKNG", "RBLX", "NIO", "ROKU",
]

# --- 국내 '급등주' 기술주(국장 급등주) 유니버스 (주로 KOSDAQ 모멘텀/테마주) ---
KR_HOT_UNIVERSE = [
    "247540.KQ",  # 에코프로비엠 (2차전지)
    "086520.KQ",  # 에코프로 (2차전지)
    "277810.KQ",  # 레인보우로보틱스 (로봇)
    "112040.KQ",  # 위메이드 (게임/코인)
    "095660.KQ",  # 네오위즈 (게임)
    "078340.KQ",  # 컴투스 (게임)
    "067160.KQ",  # SOOP(아프리카TV) (플랫폼)
    "041510.KQ",  # 에스엠 (엔터)
    "035900.KQ",  # JYP Ent. (엔터)
    "122870.KQ",  # YG엔터테인먼트 (엔터)
    "196170.KQ",  # 알테오젠 (바이오)
    "328130.KQ",  # 루닛 (AI 의료)
    "240810.KQ",  # 원익IPS (반도체 장비)
    "357780.KQ",  # 솔브레인 (반도체 소재)
    "058470.KQ",  # 리노공업 (반도체 부품)
    "263750.KQ",  # 펄어비스 (게임)
    "293490.KQ",  # 카카오게임즈 (게임)
    "042700.KS",  # 한미반도체 (반도체 장비)
]

# 종목 표시 이름 (국내 종목은 한글명, 미국은 티커 그대로 사용)
NAMES = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "035420.KS": "NAVER",
    "035720.KS": "카카오", "066570.KS": "LG전자", "006400.KS": "삼성SDI",
    "373220.KS": "LG에너지솔루션", "034220.KS": "LG디스플레이", "009150.KS": "삼성전기",
    "042700.KS": "한미반도체", "402340.KS": "SK스퀘어", "036570.KS": "엔씨소프트",
    "259960.KS": "크래프톤", "251270.KS": "넷마블", "263750.KQ": "펄어비스",
    "293490.KQ": "카카오게임즈", "058470.KQ": "리노공업", "240810.KQ": "원익IPS",
    # 국장 급등주
    "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로", "277810.KQ": "레인보우로보틱스",
    "112040.KQ": "위메이드", "095660.KQ": "네오위즈", "078340.KQ": "컴투스",
    "067160.KQ": "SOOP", "041510.KQ": "에스엠", "035900.KQ": "JYP Ent.",
    "122870.KQ": "YG엔터", "196170.KQ": "알테오젠", "328130.KQ": "루닛",
    "357780.KQ": "솔브레인",
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
    "us_hot": {
        "label": "미국 급등주 (미장 🔥)", "short": "미장🔥",
        "tz": "America/New_York", "open": (9, 30), "close": (16, 0),
        "universe": US_HOT_UNIVERSE, "capital": 10_000.0, "currency": "$",
        "open_kst": "22:30", "close_kst": "05:00",
    },
    "us_all": {
        "label": "미국 전섹터 대형주 (미장 ALL)", "short": "미장ALL",
        "tz": "America/New_York", "open": (9, 30), "close": (16, 0),
        "universe": US_ALL_UNIVERSE, "capital": 10_000.0, "currency": "$",
        "open_kst": "22:30", "close_kst": "05:00",
    },
    "kr_hot": {
        "label": "국내 급등주 (국장 🔥)", "short": "국장🔥",
        "tz": "Asia/Seoul", "open": (9, 0), "close": (15, 30),
        "universe": KR_HOT_UNIVERSE, "capital": 10_000_000.0, "currency": "₩",
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
