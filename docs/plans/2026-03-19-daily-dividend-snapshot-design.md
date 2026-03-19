# 일별 배당금 스냅샷 기록 설계

## 배경

`save_daily_summary`는 매일 포트폴리오 상태를 스냅샷으로 저장한다.
현재 백테스트에서는 `_calculate_dividend_income()`으로 배당을 계산해 현금에 반영하지만,
일별 스냅샷(`summary.json`)에는 기록되지 않는다.
실거래에는 배당 조회 로직 자체가 없다.

## 목표

- `summary.json` 레코드에 `"daily_dividend"` 필드 추가
- 티커별 내역은 불필요, 그날 수령한 총 배당금만 기록
- 백테스트 + 실거래 모두 적용

## 선택한 접근법: Option A — `run_one_cycle()`에 파라미터 전달

배당 계산은 호출자(runner.py, main.py)가 담당하고,
엔진은 받은 값을 저장만 한다. 관심사 분리가 명확하고 변경 범위가 최소화된다.

## 데이터 흐름

```
[백테스트]
runner.py
  ├─ _calculate_dividend_income(today, full_dividends, broker) → div_income
  └─ engine.run_one_cycle(loader, sim_date, daily_dividend=div_income)
       └─ persist(..., daily_dividend)
            └─ repo.save_daily_summary(..., daily_dividend)
                 └─ record["daily_dividend"] = daily_dividend

[실거래]
main.py
  ├─ data_loader.fetch_daily_dividends(tickers) → {ticker: div_per_share}
  ├─ portfolio = broker.get_portfolio()
  ├─ daily_dividend = sum(holdings[t] * div[t] for t in tickers)
  └─ engine.run_one_cycle(data_loader, daily_dividend=daily_dividend)
```

## 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `src/core/models.py` | `DayResult`에 `daily_dividend: float = 0.0` 추가 |
| `src/core/interfaces.py` | `IRepository.save_daily_summary()` 시그니처에 `daily_dividend: float = 0.0` 추가 |
| `src/core/engine.py` | `run_one_cycle()`, `persist()` 파라미터 추가 및 전달 |
| `src/infra/repo.py` | `save_daily_summary()`에서 `"daily_dividend"` 필드 JSON 저장 |
| `src/infra/data.py` | `YFinanceLoader.fetch_daily_dividends(tickers)` 추가 |
| `src/main.py` | 배당 계산 후 `run_one_cycle(daily_dividend=...)` 전달 |
| `src/backtest/runner.py` | `run_one_cycle(daily_dividend=div_income)` 전달 |

## `fetch_daily_dividends()` 구현

`yf.download(tickers, period="5d", actions=True)`로 최근 5일 배당 데이터 조회.
오늘 날짜 행에서 각 티커 배당금(주당) 반환. 없으면 `{}`. 실패 시 `{}` (배당 0으로 처리).

## summary.json 레코드 변화

```json
{
  "date": "2026-03-19",
  "total_value": 123456.78,
  "daily_dividend": 45.20,
  ...
}
```

## 테스트 계획

- `tests/test_infra_repo.py`: `save_daily_summary`에 `daily_dividend` 전달 시 JSON에 기록되는지 확인
- `tests/test_infra_data.py` (신규 또는 기존): `fetch_daily_dividends()` mock 테스트
- `tests/test_core_engine.py`: `run_one_cycle(daily_dividend=...)` 전달 시 `DayResult.daily_dividend` 반영 확인
