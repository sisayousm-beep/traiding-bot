"""가상 자산 브로커/포트폴리오: 가상 현금·보유주식 회계와 목표비중 리밸런싱.

매수·매도는 전부 모의(가상자산). 수수료/슬리피지를 실제처럼 반영한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import config


@dataclass
class Trade:
    date: pd.Timestamp
    ticker: str
    side: str          # "BUY" / "SELL"
    shares: float
    price: float       # 슬리피지 반영 체결가
    commission: float


@dataclass
class Portfolio:
    cash: float
    commission_bps: float = config.COMMISSION_BPS
    slippage_bps: float = config.SLIPPAGE_BPS
    allow_fractional: bool = config.ALLOW_FRACTIONAL
    max_leverage: float = 1.0        # 1.0=현금만, 2.0=2배 마진(현금 음수 허용)
    positions: dict[str, float] = field(default_factory=dict)   # ticker -> shares
    trades: list[Trade] = field(default_factory=list)
    bankrupt: bool = False           # 마진 청산(자본 소진) 여부

    def market_value(self, prices: pd.Series) -> float:
        """보유 주식의 시가 평가액(현금 제외)."""
        total = 0.0
        for tkr, sh in self.positions.items():
            px = prices.get(tkr)
            if px is not None and pd.notna(px):
                total += sh * px
        return total

    def total_value(self, prices: pd.Series) -> float:
        return self.cash + self.market_value(prices)

    def daily_settle(self, prices: pd.Series, borrow_rate: float) -> None:
        """매일 마감 처리: 차입금 이자 부과 + 자본 소진 시 강제청산(마진콜)."""
        if self.bankrupt:
            return
        if self.cash < 0:
            self.cash -= (-self.cash) * borrow_rate / config.TRADING_DAYS_PER_YEAR
        # 자본(현금+평가액)이 0 이하 → 청산, 거래 중단
        if self.total_value(prices) <= 0:
            self.positions.clear()
            self.cash = 0.0
            self.bankrupt = True

    def check_solvency(self, prices: pd.Series) -> None:
        """자본 소진 시 강제청산(마진콜). 인트라데이에서 분마다 호출."""
        if self.bankrupt:
            return
        if self.total_value(prices) <= 0:
            self.positions.clear()
            self.cash = 0.0
            self.bankrupt = True

    def _fill_price(self, price: float, side: str) -> float:
        """슬리피지 적용: 매수는 비싸게, 매도는 싸게 체결."""
        slip = self.slippage_bps / 10_000.0
        return price * (1 + slip) if side == "BUY" else price * (1 - slip)

    def rebalance(self, target_weights: dict[str, float], prices: pd.Series, date) -> None:
        """현재 평가총액 기준 목표비중으로 리밸런싱.

        target_weights 합이 1 미만이면 나머지는 현금 보유.
        가격이 없는(NaN) 종목은 거래하지 않는다.
        """
        if self.bankrupt:
            return
        total = self.total_value(prices)
        valid = {t: w for t, w in target_weights.items()
                 if t in prices.index and pd.notna(prices.get(t)) and w > 0}

        # 총노출이 레버리지 한도를 넘으면 비례 축소
        gross = sum(valid.values())
        if gross > self.max_leverage and gross > 0:
            scale = self.max_leverage / gross
            valid = {t: w * scale for t, w in valid.items()}

        # 목표 보유주식 수 계산
        target_shares: dict[str, float] = {}
        for tkr, w in valid.items():
            px = float(prices[tkr])
            dollars = total * w
            sh = dollars / px
            if not self.allow_fractional:
                sh = float(int(sh))
            target_shares[tkr] = sh

        # 1) 목표에서 빠지거나 줄어드는 종목 먼저 매도(현금 확보)
        for tkr in list(self.positions.keys()):
            cur = self.positions.get(tkr, 0.0)
            tgt = target_shares.get(tkr, 0.0)
            if tgt < cur:
                self._execute(tkr, cur - tgt, "SELL", prices, date)

        # 2) 신규/증액 매수
        for tkr, tgt in target_shares.items():
            cur = self.positions.get(tkr, 0.0)
            if tgt > cur:
                self._execute(tkr, tgt - cur, "BUY", prices, date)

    def _buying_power(self, prices: pd.Series) -> float:
        """매수 가능 명목금액. 레버리지 없으면 보유 현금, 마진이면 자본*배수에서 현 보유분 차감."""
        if self.max_leverage <= 1.0:
            return max(self.cash, 0.0)
        return max(self.max_leverage * self.total_value(prices) - self.market_value(prices), 0.0)

    def _execute(self, ticker: str, shares: float, side: str, prices: pd.Series, date) -> None:
        if shares <= 0:
            return
        raw_px = float(prices[ticker])
        fill = self._fill_price(raw_px, side)
        notional = fill * shares
        commission = notional * self.commission_bps / 10_000.0

        if side == "BUY":
            cost = notional + commission
            power = self._buying_power(prices)
            if cost > power + 1e-6:
                # 매수여력 내에서만 체결 (마진 모드면 power가 현금보다 큼)
                affordable = power / (fill * (1 + self.commission_bps / 10_000.0))
                if not self.allow_fractional:
                    affordable = float(int(affordable))
                shares = max(affordable, 0.0)
                if shares <= 0:
                    return
                notional = fill * shares
                commission = notional * self.commission_bps / 10_000.0
                cost = notional + commission
            self.cash -= cost   # 마진 모드에선 음수(차입) 가능
            self.positions[ticker] = self.positions.get(ticker, 0.0) + shares
        else:  # SELL
            proceeds = notional - commission
            self.cash += proceeds
            self.positions[ticker] = self.positions.get(ticker, 0.0) - shares
            if abs(self.positions[ticker]) < 1e-9:
                del self.positions[ticker]

        self.trades.append(Trade(date, ticker, side, shares, fill, commission))
