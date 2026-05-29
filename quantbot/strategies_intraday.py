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
    """3배 레버리지로 시초 모멘텀 상위 종목에 몰빵하는 초공격 스캘퍼.

    [v3 — '오전에 벌고 오후에 토해내는' 중반 급락 교정]
    Titan의 정체성은 '매일·공격적으로 매매하는 초단타'다. v2는 중반 급락을 막으려고
    '시장 전반 강세 게이트 + 당일 관망 래치'를 달았는데, 그 게이트가 너무 빡빡해
    최근 35세션 중 절반 이상을 통째로 무거래로 흘려보냈다(거래 14/35, 평균 −0.14%).
    즉 '급락을 막으려다 거래 자체를 죽인' 과교정이었다.

    데이터(국장·미장 35세션) 진단: 단순 공격형(2분마다 모멘텀 상위 재추격, 손절 없음)은
    매일 거래하지만 −1.4%/일로 자멸했고, 손실의 핵심은 ①오후 재추격(오전에 번 이익을
    오후 되돌림장에서 새로 들어갔다가 토해냄) ②3배 레버리지의 꼬리위험이었다.

    그래서 '매일 공격적으로 매매한다'는 정체성은 지키되, 게이트/래치 대신 '딴 이익을
    지키는' 장치 3개로 중반 급락만 도려낸다:
      · 오전 집중 진입(entry_cutoff) — Titan의 알파는 오전 모멘텀에 있다. cutoff 분(봉)이
        지나면 '신규 진입'을 끊는다(기존 보유는 추격손절로 계속 관리). 오후 재추격을 차단해
        '벌어둔 걸 오후에 새 종목으로 까먹는' 패턴을 원천 제거.
      · 동적 손절 — 진입가 −hard% 고정 손절, +trail_trigger 이익을 넘기면 고점 대비
        −trail% 추격손절로 전환(딴 이익을 3배 레버리지째 지킨다).
      · 고점반납 가드(giveback_guard) — 등가중 지수가 당일 플러스로 올랐다가 그 고점 대비
        guard%만큼 반락하면 전량 청산 후 그날 관망. 단 '플러스를 찍은 뒤'에만 작동하므로
        진입을 막지 않고, '벌었다가 급반락'하는 중반 붕괴의 꼬리만 자른다.

    백테스트(35세션): 거래 35/35(매일), 평균 +0.85%/일, 누적 +29.7%, 최악 −15%,
    고점반납 −5%로 v2(−0.14%·14/35)와 단순공격형(−1.4%) 양쪽을 크게 앞선다.
    """
    name = "Titan-3X"
    tagline = "3배 레버리지 초단타 — 오전 집중 진입·동적 손절·고점반납 가드 (고위험·v3)"
    warmup_min = 5
    rebalance_min = 2          # 손절 감시는 촘촘히(보유 유지면 {} 반환 → 회전 0)
    leverage = 3.0
    _CASH = {"__CASH__": 0.0}  # truthy지만 유효비중 없음 → 엔진이 전량 매도(현금화)

    def __init__(self, top_n: int = 2, scan: int = 5,
                 hard_stop: float = 0.012, trail_trigger: float = 0.02,
                 trail_stop: float = 0.015, cooldown: int = 15,
                 entry_cutoff: int = 120, giveback_guard: float = 0.010):
        self.top_n = top_n
        self.scan = scan
        self.hard_stop = hard_stop           # 진입가 대비 고정 손절(×3 레버리지)
        self.trail_trigger = trail_trigger   # 이 이익 넘기면 추격손절 전환
        self.trail_stop = trail_stop         # 고점 대비 추격손절 폭
        self.cooldown = cooldown
        self.entry_cutoff = entry_cutoff     # 이 분(봉) 이후 신규 진입 금지(오후 재추격 차단)
        self.giveback_guard = giveback_guard  # 지수가 당일 고점 대비 이만큼 반락하면 그날 관망
        self._held: set[str] = set()
        self._entry: dict[str, float] = {}
        self._peak: dict[str, float] = {}
        self._cool: dict[str, int] = {}
        self._last_scan = -10 ** 9
        self._idx_peak = -10.0               # 등가중 지수 당일 고점(반납 가드 기준)
        self._halt = False                   # 고점반납 가드 발동 시 그날 관망 래치

    def weights(self, closes, volumes, open_px):
        n = closes.shape[0]
        avail = self._avail(closes)
        if not avail:
            return {}
        last = closes.iloc[-1][avail]
        ret_open = (last / open_px[avail] - 1.0).dropna()
        index_ret = float(ret_open.mean()) if len(ret_open) else 0.0
        self._idx_peak = max(self._idx_peak, index_ret)

        self._cool = {t: c - 1 for t, c in self._cool.items() if c - 1 > 0}
        for t in list(self._held):                    # 보유 종목 장중 고점 갱신
            if t in last.index and pd.notna(last[t]):
                self._peak[t] = max(self._peak.get(t, float(last[t])), float(last[t]))

        # 고점반납 가드 — 지수가 플러스를 찍은 뒤 고점 대비 guard%만큼 반락하면 그날 관망.
        # (진입을 막지 않고, 벌었다가 급반락하는 '중반 붕괴'의 꼬리만 차단한다.)
        if self._idx_peak > 0 and (self._idx_peak - index_ret) >= self.giveback_guard:
            self._halt = True
        if self._halt:
            return self._flatten() if self._held else {}

        # 동적 손절/익절 — 매 호출(2분)마다 감시해야 손절이 실제로 작동(3배라 필수)
        survivors = []
        for t in list(self._held):
            px = float(last.get(t, float("nan")))
            if px != px:
                survivors.append(t); continue
            entry = self._entry.get(t, px)
            peak = self._peak.get(t, px)
            if peak >= entry * (1 + self.trail_trigger):
                out = px < peak * (1 - self.trail_stop)
            else:
                out = px < entry * (1 - self.hard_stop)
            if out:
                self._cool[t] = self.cooldown
            else:
                survivors.append(t)

        # 신규 진입은 scan 주기에만, 그리고 '오전 집중' — entry_cutoff 전에만 새 종목을 담는다.
        # (오후엔 기존 보유를 추격손절로만 관리해 재추격으로 이익을 토해내지 않게 한다.)
        desired = list(survivors)
        if (n - self._last_scan) >= self.scan:
            self._last_scan = n
            if n <= self.entry_cutoff:
                free = self.top_n - len(desired)
                if free > 0:
                    mom = ret_open[ret_open > 0].sort_values(ascending=False)
                    for t in mom.index:
                        if len(desired) >= self.top_n:
                            break
                        if t in desired or t in self._cool:
                            continue
                        desired.append(t)

        desired = desired[: self.top_n]
        new_set = set(desired)
        if new_set == self._held:                     # 구성 동일 → 보유(회전 0)
            return {}
        for t in new_set:
            if t not in self._entry:
                self._entry[t] = float(last[t]); self._peak[t] = float(last[t])
        for t in list(self._entry):
            if t not in new_set:
                self._entry.pop(t, None); self._peak.pop(t, None)
        self._held = new_set
        if not new_set:
            return dict(self._CASH)
        w = self.leverage / self.top_n                # 슬롯 고정(3배 풀노출)
        return {t: w for t in new_set}

    def _flatten(self):
        self._held = set(); self._entry = {}; self._peak = {}
        return dict(self._CASH)


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

    수치 튜닝(최근 한 달 국장·미장·급등주 64세션 백테스트 기준):
      보유 3→2종목(상위 리더 집중). v2 재튜닝 — 기울기창 5→10분(장중 노이즈를 더 걸러
      '굳은 추세'에만 진입), 추격손절 0.025→0.03(상승장 정상 되돌림에 조기 손절당해
      재매수하며 흘리던 손실 차단), 진입 임계 0.60→0.55(완만한 상승장 참여 확대).
      결합 알파 +0.10%→+0.32%로 개선(특히 강세장 −0.5%→+1.0%로 반전).
    """
    name = "Claude"
    tagline = "적응형 리스크관리 모멘텀 — 약세장 현금/VWAP 추세확인/추격손절 (개발: Claude)"
    warmup_min = 15
    rebalance_min = 5          # 회전율(거래비용) 억제: 5분 주기
    leverage = 1.0

    def __init__(self, top_n: int = 2, stop: float = 0.03, slope_win: int = 10,
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

    수치 튜닝(국장·미장·급등주 64세션 백테스트): 과매수 한도 0.04→0.08, 진입 시장폭
      0.45→0.40. 기존 봇은 완만한 상승장(bull)에서 리더가 VWAP 위로 살짝 벌어졌다는
      이유로 진입을 막아 추세를 놓쳤다(bull 알파 −0.7%). 문턱을 현실화하니 bull −0.7%→−0.1%,
      결합 알파 +0.36%→+0.38%로 개선(하락장 방어는 거의 그대로).
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
                 ext_cap: float = 0.08, vol_win: int = 15, slope_win: int = 5,
                 breadth_gate: float = 0.40, rs_min: float = 0.0, cooldown: int = 15):
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
       동시에 본다. breadth≥0.60 AND 지수↑ 일 때만 '공격 모드'. breadth<0.45 이거나
       지수가 무너지면 전량 현금으로 그날은 관망(halt 래치 — 재진입 안 함).
       (※ 엔진에 코스피200/나스닥 선물 피드가 없어 '지수'는 유니버스 등가중 지수의
        당일 방향으로 대용한다.)

    핵심 원칙은 '최대한 잃지 않는다'. 손실 최소화로 수치 튜닝(국장·미장 16세션씩 백테스트):
      진입 폭 0.55→0.60, 관망 전환 폭 0.40→0.45(약해지면 더 빨리 현금). 손실 난 날
      5→2일, 누적손실 -3.1%→-0.7%, 최악의 날 -1.17%→-0.59%로 하방을 크게 줄였다.
      (고정 손절은 더 조이면 휩쏘로 손실이 오히려 커져 -1.5% 유지. 4중 필터는 그대로.)

    v2 — '거래 마비' 해소: 위 손실최소화 튜닝이 너무 빡빡해 64세션 중 57일을 무거래로
      흘려보내 상승장 참여를 통째로 놓쳤다(강세장 알파 −2.4%). 하방 방어(약세장 +2.9%)는
      그대로 두고 '확실한 자리'의 문턱만 현실화한다: 안전 밴드 0.5~2.0%→0.2~3.5%(되돌림이
      얕아도 진입), 수급 폭발 200%→130%. 거래일 7→11일·결합 알파 +0.27%→+0.30%로,
      하방을 지키면서도 더 자주 참여한다. (폭등장 추격은 sniper 구조상 늦은 고점 매수가 돼
      손절로 더 잃으므로 도입하지 않음 — 상승장 미참여는 이 봇의 의도된 비용.)
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
                 band_lo: float = 0.002, band_hi: float = 0.035,
                 vol_mult: float = 1.3, vol_recent: int = 5,
                 hard_stop: float = 0.015, trail_trigger: float = 0.03,
                 trail_stop: float = 0.02, cooldown: int = 30,
                 enter_breadth: float = 0.60, exit_breadth: float = 0.45,
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


class Bita(Titan):
    """Titan과 '동일한 매매 로직'을 쓰되, 하루 목표수익(기본 +1%)을 달성하면 전량 청산하고
    그날은 더 이상 투자하지 않는 목표지향형 봇 (실험).

    근거: Titan은 오전 모멘텀에서 초반 이익을 자주 낸다. 그 이익이 +1%에 닿는 순간 확정·청산해
    이후의 되돌림·꼬리위험에 노출되지 않게 한다('번 날은 지키고 끝낸다').

    구현: 엔진은 전략에 자기 평가액을 알려주지 않으므로, Bita가 슬롯 고정비중(leverage/top_n)과
    진입가로 당일 수익률을 자체 추정한다. 포지션을 청산할 때마다 실현손익을 누적하고, 보유분은
    현재가로 평가한 미실현손익을 더해 '추정 당일 수익률'을 만든다. 이 값이 target을 넘으면
    전량 청산 후 _done 래치를 걸어 종가까지 현금을 유지한다. (수수료·슬리피지는 추정에서 제외
    되므로 실제 실현 수익률은 target보다 약간 낮게 찍힐 수 있다.)
    """
    name = "Bita"
    tagline = "Titan 로직 + 하루 +1% 달성 시 청산·관망 (목표지향·실험·고위험)"

    def __init__(self, target: float = 0.01, **kw):
        super().__init__(**kw)
        self.target = target          # 달성 시 청산하는 당일 목표수익률
        self._realized = 0.0          # 청산으로 확정된 누적 수익(슬롯비중 가중)
        self._done = False            # 목표 달성 래치 → 그날 관망

    def weights(self, closes, volumes, open_px):
        if self._done:
            return self._flatten() if self._held else {}
        avail = self._avail(closes)
        if not avail:
            return {}
        last = closes.iloc[-1][avail]
        slot_w = self.leverage / self.top_n
        # 진입 전 '추정 당일 수익률' = 누적 실현 + 현 보유 미실현
        unreal = sum(slot_w * (float(last[t]) / self._entry[t] - 1.0)
                     for t in self._held
                     if t in last.index and pd.notna(last[t]) and t in self._entry)
        if self._realized + unreal >= self.target:
            self._done = True
            return self._flatten() if self._held else {}
        # 목표 미달 → Titan 로직 그대로. 단 이번 호출에서 청산된 종목의 손익을 실현분에 누적.
        old_held = set(self._held)
        old_entry = dict(self._entry)
        w = super().weights(closes, volumes, open_px)
        for t in old_held - self._held:
            if t in old_entry and t in last.index and pd.notna(last[t]):
                self._realized += slot_w * (float(last[t]) / old_entry[t] - 1.0)
        return w


class Mythos(IntradayStrategy):
    """Opus(상대강도 리더·저회전·변동성 추격손절)와 Claude(레짐 히스테리시스·다중확인 진입·
    패자절단)의 장점만 융합하고, 'RS 지속성' 레이어를 더한 신규 로직.

    설계 철학(두 봇의 강점 결합):
      · [Claude] 레짐 히스테리시스 — 시장 폭(breadth) 데드밴드(진입 enter / 이탈 exit)로
        약세장이면 전량 현금(자본 방어), 휩쏘 방지.
      · [Opus]  상대강도(RS=종목수익−시장수익) 리더만 선정 — '시장을 이기는' 종목만 담아야
        알파가 난다. 절대 모멘텀(그냥 오른 종목)이 아니라 초과수익 상위를 고른다.
      · [Opus]  변동성비례 추격손절 + 리더자격 상실(VWAP 아래로 빠지며 RS<0) 매도, 그 외 보유.
      · [Claude+Opus] 다중확인 진입(VWAP 위 + RS>0 + 단기 기울기 양수 + 과매수 아님) + 쿨다운.
      · [둘 다] 사건기반 저회전 — 구성이 같으면 빈 비중({}) 반환(회전 0).

    [신규·무거운 레이어] RS 지속성(persistence):
      최근 persist_win분 동안 '매 분의 RS가 양수였던 비율'을 종목마다 계산한다(분×종목 RS 패널
      전체를 매 호출마다 다시 만든다 — 다른 봇보다 연산이 2배+ 무겁다). 한 틱 반짝 리더가 아니라
      '꾸준히 시장을 이겨온' 종목에만 진입(persist_min 이상)하고, 랭킹 점수도 RS×지속성으로 매겨
      가짜 신호·되돌림 진입을 줄인다.
    """
    name = "Mythos"
    tagline = "Opus×Claude 융합 — 상대강도 리더·RS 지속성·레짐 방어·변동성 손절 (개발: Claude)"
    warmup_min = 20
    rebalance_min = 3
    leverage = 1.0
    _CASH = {"__CASH__": 0.0}

    def __init__(self, top_n: int = 2, scan: int = 10,
                 enter_breadth: float = 0.55, exit_breadth: float = 0.35,
                 breadth_gate: float = 0.45, slope_win: int = 10, persist_win: int = 15,
                 vol_win: int = 15, persist_min: float = 0.55, rs_min: float = 0.0,
                 ext_cap: float = 0.08, stop_k: float = 3.0, stop_floor: float = 0.02,
                 stop_cap: float = 0.06, stop_hz: int = 30, cooldown: int = 10):
        self.top_n = top_n
        self.scan = scan                  # 신규 진입 스캔 주기(저회전)
        self.enter_breadth = enter_breadth  # 현금→투자 전환(레짐 데드밴드 상단)
        self.exit_breadth = exit_breadth    # 투자→현금 전환(하단). 사이는 상태 유지
        self.breadth_gate = breadth_gate    # 신규 진입 허용 시장 폭 하한
        self.slope_win = slope_win
        self.persist_win = persist_win      # RS 지속성 측정 창(분)
        self.vol_win = vol_win
        self.persist_min = persist_min      # 이 비율 이상 '시장 이긴' 종목만 진입
        self.rs_min = rs_min                # 상대강도 진입 하한
        self.ext_cap = ext_cap              # VWAP 대비 과매수 한도
        self.stop_k = stop_k; self.stop_floor = stop_floor
        self.stop_cap = stop_cap; self.stop_hz = stop_hz
        self.cooldown = cooldown
        self._held: set[str] = set()
        self._peak: dict[str, float] = {}
        self._cool: dict[str, int] = {}
        self._defensive = True            # 시작은 방어(현금)
        self._last_scan = -10 ** 9

    def weights(self, closes, volumes, open_px):
        n = closes.shape[0]
        avail = self._avail(closes)
        if not avail or n < max(self.slope_win, self.persist_win) + 2:
            return {}
        last = closes.iloc[-1][avail]
        pv = (closes[avail] * volumes[avail]).cumsum()
        vv = volumes[avail].cumsum().replace(0, pd.NA)
        vwap = (pv / vv).iloc[-1]
        ret_open = last / open_px[avail] - 1.0
        market_ret = float(ret_open.mean())
        rs = ret_open - market_ret                    # 상대강도(시장 대비 초과)
        above = last > vwap
        breadth = float(above.mean())
        ext = last / vwap - 1.0
        prev = closes.iloc[-(self.slope_win + 1)][avail]
        slope = last / prev - 1.0
        vol = closes[avail].pct_change().iloc[-self.vol_win:].std()

        # [무거운 레이어] 최근 persist_win분의 RS 패널 → '시장을 이긴 분의 비율'
        win = closes[avail].iloc[-self.persist_win:]
        rel = win.div(open_px[avail], axis=1) - 1.0   # 분×종목: 각 분의 시초 대비 수익
        mkt = rel.mean(axis=1)                         # 분별 등가중 시장
        rsp = rel.sub(mkt, axis=0)                     # 분×종목 RS 패널
        persist = (rsp > 0).mean()                     # 종목별 '리더였던 분' 비율

        self._cool = {t: c - 1 for t, c in self._cool.items() if c - 1 > 0}

        # 레짐 히스테리시스(데드밴드)
        if self._defensive:
            if breadth >= self.enter_breadth:
                self._defensive = False
        elif breadth < self.exit_breadth:
            self._defensive = True

        for t in list(self._held):                     # 보유 장중 고점 갱신
            if t in last.index and pd.notna(last[t]):
                self._peak[t] = max(self._peak.get(t, float(last[t])), float(last[t]))

        # 방어 레짐 → 전량 현금
        if self._defensive:
            if self._held:
                self._held = set(); self._peak = {}
                return dict(self._CASH)
            return {}

        # 보유 관리: 변동성비례 추격손절 OR 리더자격 상실(VWAP 아래 & RS<0)만 매도
        survivors = []
        for t in list(self._held):
            px = float(last.get(t, float("nan")))
            if px != px:
                survivors.append(t); continue
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

        # 신규 진입: 시장 폭 양호 + 스캔 주기 + 빈 슬롯일 때 다중확인 통과 리더로 채움
        desired = list(survivors)
        free = self.top_n - len(desired)
        if breadth >= self.breadth_gate and free > 0 and (n - self._last_scan) >= self.scan:
            self._last_scan = n
            cand = [t for t in avail
                    if t not in desired and t not in self._cool
                    and bool(above.get(t)) and float(rs.get(t, -9.0)) > self.rs_min
                    and float(slope.get(t, 0.0)) > 0
                    and float(ext.get(t, 9.0)) <= self.ext_cap
                    and float(persist.get(t, 0.0)) >= self.persist_min
                    and pd.notna(vwap.get(t))]
            # 점수 = 상대강도 × (0.5 + 지속성) + 0.25·기울기 (꾸준한 리더 우대)
            score = {t: float(rs[t]) * (0.5 + float(persist[t])) + 0.25 * float(slope.get(t, 0.0))
                     for t in cand}
            cand.sort(key=lambda t: -score[t])
            desired.extend(cand[:free])

        desired = desired[: self.top_n]
        desired_set = set(desired)
        if desired_set == self._held:                  # 구성 동일 → 보유(회전 0)
            return {}
        self._held = desired_set
        self._peak = {t: self._peak.get(t, float(last[t]))
                      for t in desired_set if t in last.index and pd.notna(last[t])}
        if not desired_set:
            return dict(self._CASH)
        w = self.leverage / len(desired_set)
        return {t: w for t in desired_set}

    def _flatten(self):
        self._held = set(); self._peak = {}
        return dict(self._CASH)


def default_bots() -> list[IntradayStrategy]:
    return [Atlas(), Orion(), Titan(), Claude(), Opus(), Gemini(),
            Bita(), Mythos(), Sol()]
