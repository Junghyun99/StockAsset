# src/backtest/runner.py
import pandas as pd
import matplotlib.pyplot as plt
from src.config import Config
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.utils.calculator import IndicatorCalculator
from src.backtest.fetcher import download_historical_data
from src.backtest.components import BacktestDataLoader, BacktestBroker

def run_backtest(start_date: str, end_date: str, initial_cash: float = 10000.0):
    # 1. 설정 로드
    config = Config()
    tickers = []
    for group in config.ASSET_GROUPS.values():
        tickers.extend(group)
    tickers = list(set(tickers)) # 중복 제거

    # 2. 데이터 준비 (10년치 한방에 로딩)
    print("--- Preparing Data ---")
    full_df, full_vix = download_historical_data(tickers, start_date, end_date)
    
    # 3. 컴포넌트 조립
    loader = BacktestDataLoader(full_df, full_vix)
    broker = BacktestBroker(initial_cash)
    
    # Core Logic (그대로 재사용!)
    calculator = IndicatorCalculator()
    analyzer = RegimeAnalyzer()
    targeter = VolatilityTargeter(target_vol=0.15)
    rebalancer = Rebalancer(config.ASSET_GROUPS)

    # 4. 루프 실행 (Time Travel)
    # 실제 데이터가 있는 날짜(거래일)만 루프
    trading_days = full_df.index
    # 사용자가 요청한 구간으로 필터링
    sim_days = [d for d in trading_days if start_date <= d.strftime("%Y-%m-%d") <= end_date]
    
    history = []
    print(f"--- Starting Backtest ({len(sim_days)} trading days) ---")

    for today in sim_days:
        # [Time Setting] 오늘 날짜 설정
        loader.set_date(today)
        
        # [Price Injection] 오늘 종가를 브로커에 주입 (종가 매매 가정)
        # MultiIndex에서 오늘 날짜의 Close 값들 추출
        current_prices = {}
        try:
            # yfinance 구조에 따라 xs 사용
            daily_slice = full_df.loc[today]
            # ('Close', 'SPY') 형태 가정
            if isinstance(daily_slice.index, pd.MultiIndex): 
                # Series with MultiIndex (Price, Ticker) -> Get Close level
                # 구조가 복잡하므로 단순화: Close 컬럼만 추출되어 있다고 가정하거나
                # full_df['Close'].loc[today] 사용
                pass
            
            # 가장 확실한 방법: full_df['Close']에서 추출
            close_prices = full_df['Close'].loc[today]
            current_prices = close_prices.to_dict()
            
        except Exception as e:
            # 데이터 누락 시 건너뜀
            continue
            
        broker.set_prices(current_prices)

        # === 봇 로직 실행 (Main.py와 동일 흐름) ===
        try:
            # 1. 지표 계산
            # 과거 400일 데이터 Fetch (Loader가 잘라서 줌)
            df_slice = loader.fetch_ohlcv(["SPY"], days=400)
            vix_val = loader.fetch_vix()
            market_data = calculator.calculate(df_slice, vix_val)
            
            # 2. 전략 판단
            regime = analyzer.analyze(market_data)
            exposure = targeter.calculate_exposure(regime, market_data.spy_volatility)
            
            # 3. 리밸런싱
            current_pf = broker.get_portfolio()
            current_pf.current_prices = current_prices # 가격 동기화
            
            signal = rebalancer.generate_signal(current_pf, exposure, regime)
            
            if signal.rebalance_needed:
                broker.execute_orders(signal.orders)
            
            # 4. 결과 기록
            final_pf = broker.get_portfolio()
            history.append({
                "date": today,
                "total_value": final_pf.total_value,
                "cash": final_pf.total_cash,
                "exposure": exposure,
                "regime": regime.value
            })
            
        except Exception as e:
            print(f"Error on {today.date()}: {e}")

    # 5. 결과 분석 및 시각화
    print("--- Backtest Finished ---")
    res_df = pd.DataFrame(history).set_index("date")
    
    # 수익률 계산
    final_value = res_df.iloc[-1]['total_value']
    cagr = (final_value / initial_cash) ** (252 / len(res_df)) - 1
    print(f"Initial: ${initial_cash:,.0f} -> Final: ${final_value:,.0f}")
    print(f"CAGR: {cagr:.2%}")
    
    # 차트 그리기
    plt.figure(figsize=(12, 6))
    plt.plot(res_df['total_value'], label='Portfolio Value')
    plt.title(f"Backtest Result ({start_date} ~ {end_date})")
    plt.legend()
    plt.show() # 혹은 plt.savefig('backtest_result.png')

if __name__ == "__main__":
    # 사용 예시: 2015년부터 2023년까지 테스트
    run_backtest("2015-01-01", "2023-12-31")