"""인트라데이(당일 단타) 전략 봇들. 각 봇은 'AI 어시스턴트' 느낌의 이름을 가진다.

모든 봇은 장중 1분봉으로 종목을 직접 선정해 매매하고, 종가에 청산한다.
입력:
  closes  : 현재 분까지의 종가 패널 (DataFrame, index=분, columns=티커)
  volumes : 동일 구간 거래량 패널
  open_px : 당일 시초 기준가 (Series, 세션 첫 봉)
반환: {티커: 비중} (합 <= leverage, 나머지 현금)
"""
from __future__ import annotations

import pandas as pd


class IntradayStrategy:
    name = "base"
    tagline = ""
    warmup_min = 5          # 워밍업(분): 이 시간 지난 뒤 매매 시작
    rebalance_min = 5       # 의사결정 주기(분)
    leverage = 1.0

    def weights(self, closes: pd.DataFrame, volumes: pd.DataFrame, open_px: pd.Series) -> dict:
        raise NotImplementedError

    @staticmethod
    def _avail(closes: pd.DataFrame) -> list[str]:
        last = closes.iloc[-1]
        return [t for t in closes.columns if pd.notna(last[t])]

    def _equal(self, picks: list[str]) -> dict:
        if not picks:
            return {}
        w = self.leverage / len(picks)
        return {t: w for t in picks}


class Atlas(IntradayStrategy):
    """시초 대비 강하게 오르는 종목을 추격하는 모멘텀 봇."""
    name = "Atlas"
    tagline = "시초가 대비 모멘텀 상위 종목 추격 (Intraday Momentum)"
    warmup_min = 5
    rebalance_min = 5

    def __init__(self, top_n: int = 3):
        self.top_n = top_n

    def weights(self, closes, volumes, open_px):
        avail = self._avail(closes)
        if not avail:
            return {}
        ret = (closes.iloc[-1][avail] / open_px[avail] - 1.0).dropna()
        ret = ret[ret > 0].sort_values(ascending=False)
        return self._equal(list(ret.head(self.top_n).index))


class Nova(IntradayStrategy):
    """VWAP 아래로 과하게 밀린 종목의 반등을 노리는 평균회귀 봇."""
    name = "Nova"
    tagline = "VWAP 이탈 종목 반등 매수 (VWAP Reversion)"
    warmup_min = 10
    rebalance_min = 3

    def __init__(self, dev: float = 0.003, top_n: int = 3):
        self.dev = dev
        self.top_n = top_n

    def weights(self, closes, volumes, open_px):
        avail = self._avail(closes)
        pv = (closes[avail] * volumes[avail]).cumsum()
        vv = volumes[avail].cumsum().replace(0, pd.NA)
        vwap = (pv / vv).iloc[-1]
        last = closes.iloc[-1][avail]
        deviation = (last / vwap - 1.0).dropna()
        cand = deviation[deviation < -self.dev].sort_values()  # 가장 많이 밀린 순
        return self._equal(list(cand.head(self.top_n).index))


class Orion(IntradayStrategy):
    """개장 후 첫 15분 고점을 상향 돌파하는 종목을 잡는 ORB 봇."""
    name = "Orion"
    tagline = "오프닝 레인지 돌파 (Opening Range Breakout)"
    warmup_min = 15
    rebalance_min = 5

    def __init__(self, or_min: int = 15, top_n: int = 3):
        self.or_min = or_min
        self.top_n = top_n

    def weights(self, closes, volumes, open_px):
        avail = self._avail(closes)
        or_high = closes[avail].iloc[: self.or_min].max()
        last = closes.iloc[-1][avail]
        breakout = (last / or_high - 1.0)
        cand = breakout[breakout > 0].sort_values(ascending=False)
        return self._equal(list(cand.head(self.top_n).index))


class Vega(IntradayStrategy):
    """최근 15분 단기 추세가 가장 강한 종목으로 갈아타는 봇."""
    name = "Vega"
    tagline = "최근 15분 상대 모멘텀 (Short-window Momentum)"
    warmup_min = 16
    rebalance_min = 5

    def __init__(self, win: int = 15, top_n: int = 3):
        self.win = win
        self.top_n = top_n

    def weights(self, closes, volumes, open_px):
        avail = self._avail(closes)
        if closes.shape[0] <= self.win:
            return {}
        ret = (closes.iloc[-1][avail] / closes.iloc[-(self.win + 1)][avail] - 1.0).dropna()
        ret = ret[ret > 0].sort_values(ascending=False)
        return self._equal(list(ret.head(self.top_n).index))


class Titan(IntradayStrategy):
    """3배 레버리지로 시초 모멘텀 상위 2종목에 몰빵하는 초공격 스캘퍼."""
    name = "Titan-3X"
    tagline = "3배 레버리지 초단타 — 시초 모멘텀 집중 (고위험)"
    warmup_min = 3
    rebalance_min = 2
    leverage = 3.0

    def __init__(self, top_n: int = 2):
        self.top_n = top_n

    def weights(self, closes, volumes, open_px):
        avail = self._avail(closes)
        if not avail:
            return {}
        ret = (closes.iloc[-1][avail] / open_px[avail] - 1.0).dropna()
        ret = ret[ret > 0].sort_values(ascending=False)
        return self._equal(list(ret.head(self.top_n).index))


class Sol(IntradayStrategy):
    """개장 직후 유니버스를 동일비중으로 담아 종가까지 들고 가는 벤치마크 봇."""
    name = "Sol"
    tagline = "기술주 동일비중 보유 (벤치마크)"
    warmup_min = 1
    rebalance_min = 10 ** 9   # 사실상 개장 직후 1회만

    def weights(self, closes, volumes, open_px):
        return self._equal(self._avail(closes))


class Claude(IntradayStrategy):
    """Claude가 직접 고안한 적응형 리스크관리 모멘텀 봇.

    기존 봇들이 낮은 수익률을 낸 원인 분석에서 출발한다:
      (1) 손절이 없어 지는 매매가 이기는 매매를 압도(손익비<1).
      (2) 과매매(높은 회전율)로 수수료·슬리피지가 수익을 잠식.
      (3) 롱 온리라 하락장에서 현금 회피 수단이 없음.
      (4) 단순 모멘텀이 장중 노이즈에 휩쏘(고가 매수→되돌림).

    이를 고치는 규칙:
      · 시장 폭(breadth=VWAP 위 종목 비율)로 레짐 판단 → 약세장이면 전량 현금(자본 방어).
        레짐은 데드밴드(진입 0.55 / 이탈 0.35)로 잦은 전체청산↔재매수 '휩쏘'를 막는다.
      · 신규 진입은 'VWAP 위 + 시초가 대비 상승 + 최근 단기 기울기 양수' 3중 확인(추세 진짜일 때만).
      · 보유는 '승자는 내버려 두고 패자만 자른다': 진입 신호가 잠깐 흔들려도 팔지 않고,
        오직 장중 고점 대비 stop%(3%) 추격손절에 걸릴 때만 매도(→ 손실 차단·이익 보존, 회전율↓).
      · 손절된 종목은 cooldown(10분) 동안 재진입 금지 → 같은 자리 휩쏘 반복 방지.
    """
    name = "Claude"
    tagline = "적응형 리스크관리 모멘텀 — 약세장 현금/VWAP 추세확인/추격손절 (개발: Claude)"
    warmup_min = 15
    rebalance_min = 5          # 회전율(거래비용) 억제: 5분 주기
    leverage = 1.0

    def __init__(self, top_n: int = 3, stop: float = 0.03, slope_win: int = 5,
                 enter_breadth: float = 0.55, exit_breadth: float = 0.35, cooldown: int = 10):
        self.top_n = top_n
        self.stop = stop                  # 장중 고점 대비 추격손절 폭
        self.slope_win = slope_win        # 단기 기울기 측정 창(분)
        self.enter_breadth = enter_breadth  # 현금→투자 전환 임계(상단)
        self.exit_breadth = exit_breadth    # 투자→현금 전환 임계(하단). 사이는 상태 유지(히스테리시스)
        self.cooldown = cooldown          # 손절 후 같은 종목 재진입 금지 분(분=봉)
        self._peak: dict[str, float] = {}  # 보유 종목 장중 최고가(추격손절 기준)
        self._defensive = True            # 시장 레짐(처음엔 방어=현금)
        self._cool: dict[str, int] = {}   # 종목별 재진입 쿨다운(봉 수)

    def weights(self, closes, volumes, open_px):
        avail = self._avail(closes)
        if not avail or closes.shape[0] < self.slope_win + 1:
            return {}
        last = closes.iloc[-1][avail]
        pv = (closes[avail] * volumes[avail]).cumsum()
        vv = volumes[avail].cumsum().replace(0, pd.NA)
        vwap = (pv / vv).iloc[-1]
        ret_open = last / open_px[avail] - 1.0
        prev = closes.iloc[-(self.slope_win + 1)][avail]
        slope = last / prev - 1.0
        above = last > vwap
        breadth = float(above.mean())     # 시장 폭(VWAP 위 비율)

        # --- 레짐 히스테리시스(데드밴드): 잦은 전체 청산↔재매수 '휩쏘' 방지 ---
        if self._defensive:
            if breadth >= self.enter_breadth:
                self._defensive = False
        elif breadth < self.exit_breadth:
            self._defensive = True

        # 쿨다운 1봉 감소
        self._cool = {t: c - 1 for t, c in self._cool.items() if c - 1 > 0}

        if self._defensive:               # 약세 레짐 → 전량 현금(자본 방어)
            self._peak = {}
            return {}

        # 보유 추적 종목 장중 최고가 갱신
        for t in list(self._peak.keys()):
            if t in last.index and pd.notna(last[t]):
                self._peak[t] = max(self._peak[t], float(last[t]))

        # 보유 처리: '승자는 내버려 두고 패자만 자른다'.
        #   진입 신호가 잠깐 흔들려도 유지하고, 장중 고점 대비 stop% 추격손절에 걸릴 때만 매도.
        keep = []
        for t in list(self._peak.keys()):
            px = float(last.get(t, float("nan")))
            if px != px:                            # NaN 보호
                continue
            pk = self._peak.get(t, px)
            if px < pk * (1 - self.stop):           # 추격손절 → 매도 + 쿨다운 등록
                self._cool[t] = self.cooldown
            else:
                keep.append(t)

        # 신규 진입 후보: VWAP 위 + 시초 대비 상승 + 단기 기울기 양수 + 쿨다운/보유 아님
        qual = [t for t in avail
                if bool(above.get(t)) and float(ret_open.get(t, 0.0)) > 0
                and float(slope.get(t, 0.0)) > 0 and pd.notna(vwap.get(t))
                and t not in self._cool and t not in keep]
        score = {t: float(ret_open[t]) + float(last[t] / vwap[t] - 1.0) for t in qual}
        ranked = sorted(qual, key=lambda t: -score[t])

        picks = list(keep)
        for t in ranked:                            # 빈 슬롯만 새 종목으로 채움
            if len(picks) >= self.top_n:
                break
            picks.append(t)
        picks = picks[: self.top_n]

        if not picks:
            self._peak = {}
            return {}
        self._peak = {t: max(self._peak.get(t, float(last[t])), float(last[t])) for t in picks}
        w = self.leverage / len(picks)     # 리스크온이면 고정 풀노출(연속 스케일링 미세 회전 방지)
        return {t: w for t in picks}


def default_bots() -> list[IntradayStrategy]:
    return [Atlas(), Nova(), Orion(), Vega(), Titan(), Claude(), Sol()]
