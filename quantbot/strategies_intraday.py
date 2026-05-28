"""인트라데이(당일 단타) 전략 봇들. 각 봇은 'AI 어시스턴트' 느낌의 이름을 가진다.

모든 봇은 장중 1분봉으로 종목을 직접 선정해 매매하고, 종가에 청산한다.
입력:
  closes  : 현재 분까지의 종가 패널 (DataFrame, index=분, columns=티커)
  volumes : 동일 구간 거래량 패널
  open_px : 당일 시초 기준가 (Series, 세션 첫 봉)
반환: {티커: 비중} (합 <= leverage, 나머지 현금)
"""
from __future__ import annotations

import math

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

    수치 튜닝(최근 한 달 국장·미장 16세션씩 백테스트 기준):
      진입 임계 0.55→0.60(더 확실할 때만 투자), 추격손절 0.03→0.025(패자 빨리 절단),
      보유 3→2종목(상위 리더 집중). 결합 알파 -0.23%→+0.26%로 개선(두 시장 모두 향상).
    """
    name = "Claude"
    tagline = "적응형 리스크관리 모멘텀 — 약세장 현금/VWAP 추세확인/추격손절 (개발: Claude)"
    warmup_min = 15
    rebalance_min = 5          # 회전율(거래비용) 억제: 5분 주기
    leverage = 1.0

    def __init__(self, top_n: int = 2, stop: float = 0.025, slope_win: int = 5,
                 enter_breadth: float = 0.60, exit_breadth: float = 0.35, cooldown: int = 10):
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


class Opus(IntradayStrategy):
    """Opus가 직접 설계한 '상대강도 리더·저회전·변동성 추격손절' 봇.

    한 달치(국장·미장) 봇별 보고서를 분석한 세 가지 사실에서 출발한다:
      (A) 성과의 최대 적은 '회전율'이다. 데이터상 회전율↑ = 알파↓가 거의 단조였다
          (Sol 회전 1.0 → Nova/Vega/Titan 20~36 → 수수료·슬리피지로 자멸).
      (B) 절대수익은 '그날 장이 좋았는지'에 휘둘린다. 상승장에선 아무 종목이나 오른다.
          시장을 '이기는'(=알파) 종목은 시장 대비 초과수익(상대강도)이 큰 종목이다.
      (C) Orion(ORB)·Claude의 높은 손익비는 '패자 절단·승자 보유'에서 나왔다.

    그래서 Opus의 근본 로직은 기존 봇들과 다르다:
      · 종목 선정: 절대 모멘텀(시초 대비 상승)이 아니라 '상대강도'(종목수익 − 시장수익)
        상위 리더를 고른다. 시장을 이기는 종목만 담아야 알파가 난다. 추가로 VWAP 위
        (기관 평균단가 위=수급 우위) + 단기 기울기 양수 + 과매수(extension) 아님을 요구.
      · 회전율 억제(사건기반 매매): 구성이 바뀔 때만 주문을 낸다. 보유를 유지할 때는
        빈 비중({})을 반환해 엔진이 '아무것도 하지 않게' 한다(분단위 미세 리밸런싱=비용 차단).
        승자는 비중이 커지든 말든 내버려 둔다(let winners run).
      · 위험관리: 종목별 최근 변동성에 비례한 추격손절(변동성 큰 종목은 넓게, 잔잔하면
        좁게)로 패자만 자른다. 시장 폭(breadth)이 무너지면 신규 진입만 중단(보유는 손절로 관리).
      · 진입 전 충분한 워밍업(30분): 개장 직후 노이즈·되돌림을 피하고 '굳은 추세'만 잡는다.

    매매 신호 요약:
      매수 — 워밍업 후, 시장 폭이 양호하고 빈 슬롯이 있을 때, 상대강도 상위 + VWAP 위 +
             상승추세 + 과매수 아님 + 쿨다운 아님인 리더를 동일비중으로 채운다.
      매도 — 장중 고점 대비 변동성비례 추격손절에 걸리거나, VWAP 아래로 빠지며 상대강도가
             음(−)이 된 '리더 자격 상실' 종목. 그 외에는 종가까지 보유.
    """
    name = "Opus"
    tagline = "상대강도 리더·저회전·변동성 추격손절 — 시장 이기는 종목만 보유 (개발: Opus)"
    warmup_min = 30           # 개장 노이즈 회피: 30분 굳은 뒤 진입
    rebalance_min = 3         # 자주 호출되지만 '보유'는 {} 반환이라 회전 0(손절만 빠르게 점검)
    leverage = 1.0

    # truthy지만 유효(양수) 비중이 없는 딕셔너리 → 엔진 rebalance가 전량 매도(현금화)한다.
    # (엔진은 빈 dict {}는 '보유'로 건너뛰므로, 전량청산 신호는 이렇게 표현)
    _CASH = {"__CASH__": 0.0}

    def __init__(self, top_n: int = 3, scan: int = 15, stop_k: float = 3.0,
                 stop_floor: float = 0.02, stop_cap: float = 0.06, stop_hz: int = 30,
                 ext_cap: float = 0.04, vol_win: int = 15, slope_win: int = 5,
                 breadth_gate: float = 0.45, rs_min: float = 0.0, cooldown: int = 15):
        self.top_n = top_n
        self.scan = scan                  # 신규 진입 스캔 주기(분): 잦은 종목 교체 억제
        self.stop_k = stop_k              # 추격손절 폭 = stop_k × 변동성 × √stop_hz
        self.stop_floor = stop_floor
        self.stop_cap = stop_cap
        self.stop_hz = stop_hz            # 손절 허용 노이즈 시계(분): √시간 스케일
        self.ext_cap = ext_cap            # VWAP 대비 과매수 한도(이보다 벌어지면 추격 금지)
        self.vol_win = vol_win            # 변동성 측정 창(분)
        self.slope_win = slope_win        # 단기 기울기 창(분)
        self.breadth_gate = breadth_gate  # 신규 진입을 허용할 시장 폭 하한
        self.rs_min = rs_min              # 상대강도 진입 하한(시장 대비 초과수익)
        self.cooldown = cooldown          # 손절 후 같은 종목 재진입 금지(분)
        self._held: set[str] = set()
        self._peak: dict[str, float] = {}
        self._cool: dict[str, int] = {}
        self._last_scan = -10 ** 9

    def weights(self, closes, volumes, open_px):
        n = closes.shape[0]
        avail = self._avail(closes)
        if not avail or n < self.slope_win + 2:
            return {}

        last = closes.iloc[-1][avail]
        pv = (closes[avail] * volumes[avail]).cumsum()
        vv = volumes[avail].cumsum().replace(0, pd.NA)
        vwap = (pv / vv).iloc[-1]
        ret_open = last / open_px[avail] - 1.0
        market_ret = float(ret_open.mean())          # 등가중 시장(=평가 기준선) 당일 수익
        rs = ret_open - market_ret                    # 상대강도(시장 대비 초과) = 알파의 원천
        above = last > vwap
        breadth = float(above.mean())
        ext = last / vwap - 1.0
        prev = closes.iloc[-(self.slope_win + 1)][avail]
        slope = last / prev - 1.0
        vol = closes[avail].pct_change().iloc[-self.vol_win:].std()

        self._cool = {t: c - 1 for t, c in self._cool.items() if c - 1 > 0}

        # 보유 종목 장중 고점 갱신 + 손절/리더자격 상실 판정
        for t in list(self._held):
            if t in last.index and pd.notna(last[t]):
                self._peak[t] = max(self._peak.get(t, float(last[t])), float(last[t]))
        survivors = []
        for t in list(self._held):
            px = float(last.get(t, float("nan")))
            if px != px:                              # NaN → 판단 보류, 유지
                survivors.append(t)
                continue
            pk = self._peak.get(t, px)
            vt = float(vol.get(t, 0.0) or 0.0)
            stop_pct = min(self.stop_cap,
                           max(self.stop_floor, self.stop_k * vt * math.sqrt(self.stop_hz)))
            stopped = px < pk * (1 - stop_pct)
            lost_lead = (px < float(vwap.get(t, px))) and (float(rs.get(t, 0.0)) < 0)
            if stopped or lost_lead:
                self._cool[t] = self.cooldown
            else:
                survivors.append(t)

        # 신규 진입: 시장 폭 양호 + 스캔 주기 + 빈 슬롯일 때 상대강도 상위 리더로 채움
        desired = list(survivors)
        free = self.top_n - len(desired)
        if breadth >= self.breadth_gate and free > 0 and (n - self._last_scan) >= self.scan:
            self._last_scan = n
            cand = [t for t in avail
                    if t not in desired and t not in self._cool
                    and bool(above.get(t)) and float(ret_open.get(t, 0.0)) > 0
                    and float(rs.get(t, -9.0)) > self.rs_min
                    and float(slope.get(t, 0.0)) > 0
                    and float(ext.get(t, 9.0)) <= self.ext_cap
                    and pd.notna(vwap.get(t))]
            cand.sort(key=lambda t: -float(rs[t]))
            desired.extend(cand[:free])

        desired = desired[: self.top_n]
        desired_set = set(desired)

        # 사건기반: 구성이 같으면 보유(회전 0), 다르면 교체. 비면 전량 현금.
        if desired_set == self._held:
            return {}
        self._held = desired_set
        self._peak = {t: self._peak.get(t, float(last[t]))
                      for t in desired_set if t in last.index and pd.notna(last[t])}
        if not desired_set:
            return dict(self._CASH)
        w = self.leverage / len(desired_set)
        return {t: w for t in desired_set}


class Gemini(IntradayStrategy):
    """4대 매매 알고리즘으로 '확실한 자리만 저격'하는 저회전 정밀 봇.

    ① 동적 시장 레짐 필터 2.0 — 워밍업 15분 뒤, 시장 폭(VWAP 상회 비율)과 '지수 방향'을
       동시에 본다. breadth≥0.55 AND 지수↑ 일 때만 '공격 모드'. breadth<0.40 이거나
       지수가 무너지면 전량 현금으로 그날은 관망(halt 래치 — 재진입 안 함).
       (※ 엔진에 코스피200/나스닥 선물 피드가 없어 '지수'는 유니버스 등가중 지수의
        당일 방향으로 대용한다.)
    ② 4중 확인 진입 — 네 조건을 모두 충족하는 종목만 저격 매수:
       (Orion) 개장 첫 15분 고가 상향 돌파 · (Atlas) 시초 대비 수익률 양수 상위 ·
       (안전 바닥) 현재가가 VWAP +0.5%~+2% 밴드 안(과열 추격 금지) ·
       (수급) 최근 5분 분당 거래량이 당일 평균의 200% 이상 폭발.
    ③ 타이트한 동적 손절/익절 — 진입 즉시 매수가 대비 -1.5% 고정 손절. 이익이 +3%를
       넘는 순간부터 고점 대비 -2% 추격손절로 전환(딴 이익 보존). 손절난 종목은 30분 쿨다운.
    ④ 최소 재밸런싱 — 신규 진입 의사결정은 15분 주기. 추세가 살아있으면 종가까지 보유하고,
       구성이 바뀔 때만 주문(회전율 ≤ 1.5배 목표). 손절을 실제로 작동시키려면 감시는
       촘촘해야 하므로 엔진 호출은 3분마다 받되, 보유 유지면 빈 비중을 반환해 회전을 0으로 둔다.
    """
    name = "Gemini"
    tagline = "4중 확인 저격 진입·-1.5%/+3%→-2% 동적 손절·저회전 (개발: Gemini)"
    warmup_min = 15
    rebalance_min = 3          # 손절 감시 주기(보유 유지는 {} 반환 → 회전 0)
    leverage = 1.0
    _CASH = {"__CASH__": 0.0}  # truthy지만 유효비중 없음 → 엔진이 전량 매도(현금화)

    def __init__(self, top_n: int = 2, scan: int = 15, or_min: int = 15,
                 band_lo: float = 0.005, band_hi: float = 0.02,
                 vol_mult: float = 2.0, vol_recent: int = 5,
                 hard_stop: float = 0.015, trail_trigger: float = 0.03,
                 trail_stop: float = 0.02, cooldown: int = 30,
                 enter_breadth: float = 0.55, exit_breadth: float = 0.40,
                 index_collapse: float = -0.005):
        self.top_n = top_n
        self.scan = scan                  # 신규 진입 의사결정 주기(분)
        self.or_min = or_min              # 오프닝 레인지(분)
        self.band_lo = band_lo; self.band_hi = band_hi   # VWAP 대비 안전 매수 밴드
        self.vol_mult = vol_mult; self.vol_recent = vol_recent
        self.hard_stop = hard_stop        # 매수가 대비 고정 손절
        self.trail_trigger = trail_trigger  # 이 이익을 넘으면 추격손절 전환
        self.trail_stop = trail_stop      # 고점 대비 추격손절 폭
        self.cooldown = cooldown
        self.enter_breadth = enter_breadth
        self.exit_breadth = exit_breadth
        self.index_collapse = index_collapse  # 지수 붕괴 임계(이하면 그날 관망)
        self._held: set[str] = set()
        self._entry: dict[str, float] = {}
        self._peak: dict[str, float] = {}
        self._cool: dict[str, int] = {}
        self._last_scan = -10 ** 9
        self._halt = False                # 그날 관망 래치(자본 방어)

    def weights(self, closes, volumes, open_px):
        n = closes.shape[0]
        avail = self._avail(closes)
        if not avail or n < self.or_min + 1:
            return {}

        last = closes.iloc[-1][avail]
        pv = (closes[avail] * volumes[avail]).cumsum()
        vv = volumes[avail].cumsum().replace(0, pd.NA)
        vwap = (pv / vv).iloc[-1]
        ret_open = last / open_px[avail] - 1.0
        index_ret = float(ret_open.mean())            # 등가중 지수(=시장) 방향 대용
        above = last > vwap
        breadth = float(above.mean())

        self._cool = {t: c - 1 for t, c in self._cool.items() if c - 1 > 0}
        for t in list(self._held):                    # 보유 종목 장중 고점 갱신
            if t in last.index and pd.notna(last[t]):
                self._peak[t] = max(self._peak.get(t, float(last[t])), float(last[t]))

        # 이미 그날 관망(halt) 래치가 걸렸으면 전량 현금 유지
        if self._halt:
            return self._flatten() if self._held else {}

        # ③ 보유 손절/익절 판정 — 매 호출(3분)마다 감시해야 -1.5%/-2% 손절이 실제로 작동
        survivors = []
        for t in list(self._held):
            px = float(last.get(t, float("nan")))
            if px != px:
                survivors.append(t); continue
            entry = self._entry.get(t, px)
            peak = self._peak.get(t, px)
            if peak >= entry * (1 + self.trail_trigger):          # +3% 도달 → 추격손절
                out = px < peak * (1 - self.trail_stop)
            else:                                                  # 그 전 → 고정 손절
                out = px < entry * (1 - self.hard_stop)
            if out:
                self._cool[t] = self.cooldown
            else:
                survivors.append(t)

        # ①+② 레짐 판단·신규 진입은 '의사결정 주기(15분)'에만. 1분 노이즈로 그날을
        #     통째로 관망시키지 않으려고 매 틱이 아니라 결정 시점에 레짐을 평가한다.
        #     (틱 사이의 위험은 ③ 손절이 막는다.)
        desired = list(survivors)
        if (n - self._last_scan) >= self.scan:
            self._last_scan = n
            if breadth < self.exit_breadth or index_ret < self.index_collapse:
                self._halt = True                                 # 붕괴 → 그날 관망 래치
                desired = []
            elif breadth >= self.enter_breadth and index_ret > 0:  # 공격 모드
                free = self.top_n - len(desired)
                if free > 0:
                    or_high = closes[avail].iloc[: self.or_min].max()
                    day_avg_vol = volumes[avail].mean()
                    recent_vol = volumes[avail].iloc[-self.vol_recent:].mean()
                    band = last / vwap - 1.0
                    cand = []
                    for t in avail:
                        if t in desired or t in self._cool:
                            continue
                        if not (float(ret_open.get(t, 0.0)) > 0):                 # Atlas 기세
                            continue
                        if not (last[t] > float(or_high.get(t, float("inf")))):   # Orion 돌파
                            continue
                        b = float(band.get(t, 9.0))
                        if not (self.band_lo <= b <= self.band_hi):               # 안전 밴드
                            continue
                        da = float(day_avg_vol.get(t, 0.0) or 0.0)
                        rc = float(recent_vol.get(t, 0.0) or 0.0)
                        if not (da > 0 and rc >= self.vol_mult * da):             # 수급 폭발
                            continue
                        cand.append(t)
                    cand.sort(key=lambda t: -float(ret_open[t]))                  # 기세 강한 순
                    desired.extend(cand[:free])

        desired = desired[: self.top_n]
        new_set = set(desired)

        # ④ 사건기반: 구성 같으면 보유(회전 0), 다르면 교체. 빈 슬롯은 고정 비중(저격 사이즈)
        if new_set == self._held:
            return {}
        for t in new_set:                                  # 신규 진입만 매수가/고점 등록
            if t not in self._entry:
                self._entry[t] = float(last[t])
                self._peak[t] = float(last[t])
        for t in list(self._entry):                        # 빠진 종목 추적 정리
            if t not in new_set:
                self._entry.pop(t, None); self._peak.pop(t, None)
        self._held = new_set
        if not new_set:
            return dict(self._CASH)
        w = self.leverage / self.top_n                     # 슬롯 고정(승자 자동 증액 안 함)
        return {t: w for t in new_set}

    def _flatten(self):
        self._held = set(); self._entry = {}; self._peak = {}
        return dict(self._CASH)


def default_bots() -> list[IntradayStrategy]:
    return [Atlas(), Orion(), Titan(), Claude(), Opus(), Gemini(), Sol()]
