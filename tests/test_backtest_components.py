# tests/test_backtest_components.py
import pytest
import pandas as pd
import numpy as np
from src.backtest.components import BacktestDataLoader, BacktestBroker
from src.core.models import Order, OrderAction

@pytest.fixture
def mock_full_data():
    """10일치 가짜 데이터 생성"""
    dates = pd.date_range(start="2024-01-01", periods=10)
    # 가격: 100, 110, ... 190
    prices = np.linspace(100, 190, 10).reshape(-1, 1) 
    
    # MultiIndex 구조 흉내 (Close, SPY)
    columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
    df = pd.DataFrame(prices, index=dates, columns=columns)
    
    # VIX 데이터 (단일 인덱스)
    vix_df = pd.DataFrame({'Close': [20.0]*10}, index=dates)
    
    return df, vix_df

def test_loader_time_travel_slicing(mock_full_data):
    """
    [Loader] 특정 날짜로 설정했을 때, 그 이전 데이터만 가져오는지 확인
    """
    full_df, full_vix = mock_full_data
    loader = BacktestDataLoader(full_df, full_vix)
    
    # 1. 2024-01-05 (5번째 날)로 시점 설정
    target_date = pd.Timestamp("2024-01-05")
    loader.set_date(target_date)
    
    # 2. 과거 3일치 데이터 요청
    df = loader.fetch_ohlcv(["SPY"], days=3)
    
    # 3. 검증
    # 1월 5일 포함, 그 전 3개 행이 나와야 함 (3, 4, 5일)
    assert len(df) == 3
    assert df.index[-1] == target_date
    assert df.iloc[-1].item() == 140.0 # 5번째 값 (100, 110, 120, 130, 140)

def test_loader_fetch_ohlcv_date_not_in_index(mock_full_data):
    """
    [Loader] current_date가 인덱스에 없는 날짜(휴장일 등)일 때도
    이전 날짜까지의 데이터를 올바르게 반환하는지 확인
    """
    full_df, full_vix = mock_full_data
    loader = BacktestDataLoader(full_df, full_vix)

    # full_df 인덱스: 2024-01-01 ~ 2024-01-10 (영업일 기준)
    # 2024-01-06은 토요일로 인덱스에 없을 수 있지만, 테스트용으로 임의 날짜 사용
    # full_df의 마지막 날짜는 2024-01-10이므로 2024-01-07(존재)과 2024-01-11(미존재) 테스트
    non_existent_date = pd.Timestamp("2024-01-11")  # 인덱스에 없는 날짜
    loader.set_date(non_existent_date)

    # 인덱스에 없는 날짜임을 확인
    assert non_existent_date not in full_df.index

    # 해당 날짜 이전 데이터가 반환되어야 함 (인덱스에 없어도 에러 없이 동작)
    df = loader.fetch_ohlcv(["SPY"], days=5)

    # full_df는 2024-01-01 ~ 2024-01-10 (10개), 그 중 마지막 5개
    assert len(df) == 5
    # 마지막 날짜는 full_df의 마지막 날짜인 2024-01-10이어야 함
    assert df.index[-1] == pd.Timestamp("2024-01-10")


def test_loader_fetch_ohlcv_no_future_data_leak(mock_full_data):
    """
    [Loader] fetch_ohlcv가 current_date 이후 데이터를 포함하지 않는지 확인 (미래 데이터 누출 방지)
    """
    full_df, full_vix = mock_full_data
    loader = BacktestDataLoader(full_df, full_vix)

    # 중간 날짜로 설정 (2024-01-05, 5번째)
    target_date = pd.Timestamp("2024-01-05")
    loader.set_date(target_date)

    # 충분히 많은 days 요청 (전체 데이터보다 많음)
    df = loader.fetch_ohlcv(["SPY"], days=100)

    # target_date 이후 데이터가 포함되면 안 됨
    assert df.index[-1] <= target_date
    # 2024-01-06 ~ 2024-01-10 데이터가 없어야 함
    future_dates = [d for d in df.index if d > target_date]
    assert len(future_dates) == 0


def test_broker_price_injection():
    """
    [Broker] 외부에서 주입한 가격이 체결에 반영되는지 확인
    """
    broker = BacktestBroker(initial_cash=10000.0)
    
    # 1. 가격 주입 (SPY = 200달러)
    broker.set_prices({'SPY': 200.0})
    
    # 2. 현재가 조회 확인
    prices = broker.fetch_current_prices(['SPY'])
    assert prices['SPY'] == 200.0
    
    # 3. 매수 주문 실행
    # Order 객체의 price는 '예상가'일 뿐, Broker는 주입된 '200.0'으로 체결해야 함
    order = Order('SPY', OrderAction.BUY, 10, 150.0) # 주문서엔 150이라 적혀있어도
    executions = broker.execute_orders([order])
    
    # 4. 체결 가격 검증 (MockBroker 로직상 슬리피지 1% 적용됨 -> 202.0)
    exec_price = executions[0].price
    assert exec_price == pytest.approx(202.0) 
    
    # 잔고 차감 확인: 10000 - (202 * 10 + 수수료)
    assert broker.get_portfolio().total_cash < 8000.0


def test_fetch_vix_returns_correct_value(mock_full_data):
    """
    [Loader] fetch_vix가 current_date에 해당하는 VIX 값을 올바르게 반환하는지 확인
    """
    full_df, full_vix = mock_full_data
    loader = BacktestDataLoader(full_df, full_vix)

    target_date = pd.Timestamp("2024-01-03")
    loader.set_date(target_date)

    vix = loader.fetch_vix()
    assert vix == pytest.approx(20.0)


def test_fetch_vix_returns_default_on_empty_dataframe():
    """
    [Loader] VIX 데이터가 비어 있을 때 기본값 20.0을 반환하는지 확인
    (이슈 #53: bare except 수정 후 명시적 예외로 기본값 반환 동작 유지 검증)
    """
    dates = pd.date_range(start="2024-01-01", periods=5)
    columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
    full_df = pd.DataFrame([[100.0]] * 5, index=dates, columns=columns)

    empty_vix = pd.DataFrame({'Close': []})
    loader = BacktestDataLoader(full_df, empty_vix)
    loader.set_date(pd.Timestamp("2024-01-03"))

    vix = loader.fetch_vix()
    assert vix == pytest.approx(20.0)


def test_broker_execute_orders_does_not_mutate_original_order():
    """
    [Broker] execute_orders 호출 후 원본 Order 객체의 price가 변경되지 않는지 확인
    (이슈 #54: Order 직접 수정 부작용 방지)
    """
    broker = BacktestBroker(initial_cash=10000.0)
    broker.set_prices({'SPY': 200.0})

    original_price = 150.0
    order = Order('SPY', OrderAction.BUY, 5, original_price)

    broker.execute_orders([order])

    # 원본 객체 price가 변경되지 않아야 함
    assert order.price == original_price


def test_broker_get_portfolio_reflects_simulation_prices():
    """
    [Broker] get_portfolio()가 simulation_prices를 current_prices로 반영하여
    total_value에 보유 주식 평가액이 올바르게 포함되는지 확인
    (이슈 #64: BacktestBroker.get_portfolio()에 current_prices 미주입으로 total_value 계산 오류)
    """
    broker = BacktestBroker(initial_cash=10000.0)

    # 시뮬레이션 가격 주입: SPY = 200달러
    broker.set_prices({'SPY': 200.0})

    # SPY 10주 매수 → 현금 감소, 보유량 증가
    order = Order('SPY', OrderAction.BUY, 10, 200.0)
    broker.execute_orders([order])

    pf = broker.get_portfolio()

    # 보유 주식 평가액이 current_prices에 반영되어야 함
    assert pf.current_prices.get('SPY') == pytest.approx(200.0)

    # total_value = cash + (10주 × 200달러)
    # 슬리피지 1% 적용으로 체결가 202달러, 수수료 0.1%
    # cash = 10000 - (202 * 10 * 1.001) = 10000 - 2022.02 = 7977.98
    # stock_val = 10 * 200 = 2000 (simulation_prices 기준)
    # total_value = 7977.98 + 2000 = 9977.98
    assert pf.total_value == pytest.approx(pf.total_cash + 10 * 200.0)


def test_broker_get_portfolio_total_value_without_prices():
    """
    [Broker] simulation_prices가 설정되지 않은 경우 total_value는 현금만 반영
    """
    broker = BacktestBroker(initial_cash=5000.0)
    # 가격 주입 없이 포트폴리오 조회
    pf = broker.get_portfolio()

    assert pf.total_cash == pytest.approx(5000.0)
    assert pf.total_value == pytest.approx(5000.0)
    assert pf.current_prices == {}


def test_backtest_broker_no_sleep_on_sell_orders():
    """
    [이슈 #67] BacktestBroker는 매도 주문 실행 시 time.sleep을 호출하지 않아야 함.
    MockBroker는 _refresh_balance_from_api()에서 time.sleep(1)을 사용하지만,
    BacktestBroker는 이 메서드를 오버라이드하여 딜레이가 없어야 한다.
    """
    from unittest.mock import patch

    broker = BacktestBroker(initial_cash=5000.0)
    broker.set_prices({'SPY': 100.0})
    broker.holdings['SPY'] = 10  # 매도 가능 수량 설정

    sell_order = Order('SPY', OrderAction.SELL, 5, 100.0)

    with patch('time.sleep') as mock_sleep:
        broker.execute_orders([sell_order])
        # BacktestBroker에서는 time.sleep이 호출되지 않아야 함
        mock_sleep.assert_not_called()


def test_backtest_broker_wait_for_completion_returns_immediately():
    """
    [이슈 #67] BacktestBroker._wait_for_completion()이 즉시 True를 반환하는지 확인.
    """
    broker = BacktestBroker(initial_cash=5000.0)
    result = broker._wait_for_completion(timeout=60)
    assert result is True


def test_backtest_broker_execution_date_uses_simulation_date():
    """
    [이슈 #66] BacktestBroker.set_date()로 설정한 시뮬레이션 날짜가
    TradeExecution.date에 기록되는지 확인 (datetime.now() 사용 금지).
    """
    broker = BacktestBroker(initial_cash=10000.0)
    broker.set_prices({'SPY': 100.0})

    sim_date = pd.Timestamp("2018-03-15")
    broker.set_date(sim_date)

    order = Order('SPY', OrderAction.BUY, 5, 100.0)
    executions = broker.execute_orders([order])

    assert len(executions) == 1
    assert executions[0].date == "2018-03-15"


def test_backtest_broker_execution_date_fallback_without_set_date():
    """
    [이슈 #66] set_date()를 호출하지 않으면 current_date가 None이므로
    기본 MockBroker 동작(datetime.now() 기반 날짜)이 그대로 사용되어야 함.
    즉, date 필드는 빈 문자열이 아니어야 한다.
    """
    broker = BacktestBroker(initial_cash=10000.0)
    broker.set_prices({'SPY': 100.0})
    # set_date() 호출 없이 주문 실행

    order = Order('SPY', OrderAction.BUY, 5, 100.0)
    executions = broker.execute_orders([order])

    assert len(executions) == 1
    # current_date가 None이면 MockBroker의 datetime.now() 결과가 그대로 사용됨
    assert executions[0].date != ""


def test_backtest_broker_set_date_updates_per_day():
    """
    [이슈 #66] 날짜를 변경할 때마다 다음 체결의 date가 갱신되는지 확인.
    """
    broker = BacktestBroker(initial_cash=50000.0)
    broker.set_prices({'SPY': 100.0})

    # 첫 번째 거래일: 2020-01-02
    broker.set_date(pd.Timestamp("2020-01-02"))
    broker.holdings['SPY'] = 10
    sell_order = Order('SPY', OrderAction.SELL, 5, 100.0)
    executions_day1 = broker.execute_orders([sell_order])

    # 두 번째 거래일: 2020-01-03
    broker.set_date(pd.Timestamp("2020-01-03"))
    buy_order = Order('SPY', OrderAction.BUY, 3, 100.0)
    executions_day2 = broker.execute_orders([buy_order])

    assert executions_day1[0].date == "2020-01-02"
    assert executions_day2[0].date == "2020-01-03"


def test_fetch_ohlcv_raises_value_error_when_ticker_not_in_multiindex():
    """
    [이슈 #89] 단일 종목 요청 시 해당 티커가 MultiIndex에 없으면 ValueError를 발생시켜야 함.
    전체 MultiIndex DataFrame을 그대로 반환하면 IDataProvider 계약 위반.
    """
    dates = pd.date_range(start="2024-01-01", periods=5)
    # AAPL 데이터만 있는 MultiIndex DataFrame
    columns = pd.MultiIndex.from_product([['Close'], ['AAPL']])
    df = pd.DataFrame([[100.0]] * 5, index=dates, columns=columns)
    vix_df = pd.DataFrame({'Close': [20.0] * 5}, index=dates)

    loader = BacktestDataLoader(df, vix_df)
    loader.set_date(pd.Timestamp("2024-01-05"))

    # SPY는 데이터에 없으므로 ValueError가 발생해야 함
    with pytest.raises(ValueError, match="SPY"):
        loader.fetch_ohlcv(["SPY"], days=5)


def test_fetch_ohlcv_error_message_contains_available_tickers():
    """
    [이슈 #89] ValueError 메시지에 사용 가능한 티커 목록이 포함되어야 함.
    """
    dates = pd.date_range(start="2024-01-01", periods=5)
    columns = pd.MultiIndex.from_product([['Close'], ['QLD']])
    df = pd.DataFrame([[50.0]] * 5, index=dates, columns=columns)
    vix_df = pd.DataFrame({'Close': [20.0] * 5}, index=dates)

    loader = BacktestDataLoader(df, vix_df)
    loader.set_date(pd.Timestamp("2024-01-05"))

    with pytest.raises(ValueError) as exc_info:
        loader.fetch_ohlcv(["SSO"], days=5)

    assert "QLD" in str(exc_info.value)  # 사용 가능한 티커가 메시지에 포함


def test_fetch_ohlcv_single_ticker_returns_single_index_when_found():
    """
    [이슈 #89] 단일 종목 요청 시 해당 티커가 존재하면 SingleIndex DataFrame을 반환해야 함.
    KeyError 수정이 정상 케이스에 영향을 주지 않는지 확인.
    """
    dates = pd.date_range(start="2024-01-01", periods=5)
    columns = pd.MultiIndex.from_product([['Close', 'Open'], ['SPY']])
    data = [[100.0, 99.0]] * 5
    df = pd.DataFrame(data, index=dates, columns=columns)
    vix_df = pd.DataFrame({'Close': [20.0] * 5}, index=dates)

    loader = BacktestDataLoader(df, vix_df)
    loader.set_date(pd.Timestamp("2024-01-05"))

    result = loader.fetch_ohlcv(["SPY"], days=5)

    # SingleIndex여야 함 (MultiIndex가 아닌)
    assert not isinstance(result.columns, pd.MultiIndex)
    assert "Close" in result.columns