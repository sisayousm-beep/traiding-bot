# ⚡ 당일 단타 봇 경쟁 (Intraday Quant Trading Bots)

실제 1분봉 시장 데이터로 여러 트레이딩 봇이 **$10,000 가상 자본**으로 **당일 단타**를
벌여 "**하루 수익률**"을 겨루는 모의 투자 시뮬레이터. 매매는 전부 모의(가상자산)지만,
가격·수수료·슬리피지·레버리지는 실제처럼 반영한다. 종목 범위는 기술주 25종.

각 봇은 **장중에 직접 종목을 선정**해 매매하고 **종가에 전량 청산**한다.

---

## 빠른 시작

```bash
pip install -r requirements.txt
```

### 1) 웹 대시보드 (권장)
- **가장 쉬운 방법: 「대시보드 실행.bat」 더블클릭** → 서버 시작 + 브라우저 자동 열림
- 또는 터미널에서:
```bash
python -m webapp.server --open      # http://127.0.0.1:5000
```

### 2) 터미널(CLI)
```bash
python main.py                      # 오늘 세션 1회
python main.py --mode prev          # 전날 장(직전 세션)
python main.py --mode today --live  # 오늘 세션 실시간 반복 갱신
```

---

## 두 가지 시뮬레이션 모드 (따로 실행)

| 모드 | 설명 | 용도 |
|------|------|------|
| **오늘(실시간) `today`** | 가장 최근(오늘) 세션의 1분봉, 장중 정보 반영 | 실시간으로 봇 성과 관찰 |
| **전날 장 `prev`** | 직전 거래일 세션으로 백테스트 | 어제 장에서 어느 봇이 좋았나 검증 |

웹에서는 상단 **[오늘(실시간)] / [전날 장]** 토글로 전환, CLI에서는 `--mode`로 선택.
두 모드는 서로 독립적으로 계산·캐시된다.

### 실시간 사용
웹의 **자동 갱신**(30·60·120초)을 켜면 매 주기 `POST /api/refresh`로 최신 1분봉을
다시 받아 시뮬레이션을 재실행한다. 미국 장중(한국시간 22:30~05:00)에 켜두면 봇들의
하루 수익률 순위가 실시간으로 갱신된다. **API 키 불필요**(yfinance/Yahoo Finance 무료).

> 장이 안 열린 시간/주말에는 해당 세션 데이터가 없을 수 있으며, 이때는 안내 메시지가 표시된다.

---

## 경쟁 봇 (AI식 이름)

| 봇 | 전략 | 레버리지 | 비고 |
|----|------|:---:|------|
| **Atlas** | 시초가 대비 모멘텀 상위 종목 추격 | 1x | Intraday Momentum |
| **Nova** | VWAP 이탈 종목 반등 매수 | 1x | VWAP Reversion |
| **Orion** | 오프닝 레인지(첫 15분) 돌파 | 1x | Opening Range Breakout |
| **Vega** | 최근 15분 단기 상대 모멘텀 | 1x | Short-window Momentum |
| **Titan-3X** | 시초 모멘텀 상위 2종목 몰빵 | **3x** | 초공격 스캘퍼(고위험) |
| **Sol** | 기술주 동일비중 보유 | 1x | 벤치마크 |

모두 검증된 정통 인트라데이 기법 기반이며, 각 봇이 종목 선정까지 담당한다.
3배 레버리지 봇(Titan-3X)은 손익이 3배로 증폭되고, 자본 소진 시 강제청산된다.

---

## 성과 지표

리더보드는 **하루 수익률(DailyReturn)** 기준 정렬. 그 외:
- **PeakGain** 장중 최고 평가익 · **MaxDrawdown** 장중 최대 낙폭
- **IntradayVol** 분단위 변동성 · **WinMinutes** 상승 분 비율
- **n_trades** 매매 횟수 · **FinalEquity** 종가 청산 후 최종 자산

---

## 구조

```
투자/
├─ 대시보드 실행.bat        더블클릭 실행기(서버+브라우저)
├─ main.py                  CLI 진입점 (--mode prev|today, --live)
├─ requirements.txt
├─ quantbot/
│   ├─ config.py            자본($10k)·수수료·레버리지·기술주 유니버스
│   ├─ intraday_data.py     yfinance 1분봉 로더 (prev/today 세션)
│   ├─ portfolio.py         가상 현금/주식, 리밸런싱, 마진(레버리지)·청산
│   ├─ strategies_intraday.py  봇 전략(종목선정+매매)
│   ├─ intraday_engine.py   분단위 시뮬, EOD 청산
│   └─ intraday_metrics.py  하루수익률 등 지표 + JSON 페이로드
└─ webapp/
    ├─ server.py            Flask API (/api/results, /api/refresh)
    └─ templates/index.html 대시보드(Plotly)
```

---

## 주의
교육·연구용 **모의 투자**다. 실제 주문은 발생하지 않으며, 과거/장중 성과가 미래를
보장하지 않는다. 레버리지 봇은 특히 손실 위험이 크다.
