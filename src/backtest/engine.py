# src/backtest/engine.py
import pandas as pd
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.utils.calculator import IndicatorCalculator
# ... (필요한 모듈 임포트)

class Backtester:
    def __init__(self, start_date, end_date):
        # 1. 10년치 데이터 한 번에 다운로드
        self.full_data = self._download_all_data() 
        self.full_vix = self._download_vix()
        
        # 2. 백테스트용 인프라 조립
        self.data_loader = HistoricalDataLoader(self.full_data, self.full_vix)
        self.broker = BacktestBroker(initial_cash=10000.0)
        
        # 3. 코어 로직 (변경 없음! 그대로 사용)
        self.calculator = IndicatorCalculator()
        self.analyzer = RegimeAnalyzer()
        self.targeter = VolatilityTargeter()
        self.rebalancer = Rebalancer(config.ASSET_GROUPS)
        
        self.dates = pd.date_range(start_date, end_date, freq='B') # 영업일 기준 루프

    def run(self):
        history = []
        
        for date in self.dates:
            if date not in self.full_data.index: continue # 휴장일 스킵
            
            print(f"--- Simulating {date.date()} ---")
            
            # [Time Travel] 1. 시점 설정
            self.data_loader.set_date(date)
            
            # [Price Injection] 2. 그 날의 종가를 브로커에 주입 (현재가로 가정)
            todays_prices = self._extract_prices(self.full_data, date)
            self.broker.set_prices(todays_prices)
            
            # --- 아래부터는 main.py의 로직과 거의 동일 ---
            
            # 3. 데이터 수집 (과거 시점 Slicing)
            df = self.data_loader.fetch_ohlcv(...) 
            vix = self.data_loader.fetch_vix()
            
            # 4. 로직 실행
            market_data = self.calculator.calculate(df, vix)
            regime = self.analyzer.analyze(market_data)
            exposure = self.targeter.calculate_exposure(regime, market_data.spy_volatility)
            
            # 5. 리밸런싱
            pf = self.broker.get_portfolio()
            # 브로커에 주입된 현재가로 Portfolio 가치 갱신 필요
            pf.current_prices = todays_prices 
            
            signal = self.rebalancer.generate_signal(pf, exposure, regime)
            
            if signal.rebalance_needed:
                self.broker.execute_orders(signal.orders)
                
            # 6. 결과 기록
            final_pf = self.broker.get_portfolio()
            history.append({
                'date': date,
                'total_value': final_pf.total_value,
                'regime': regime.value
            })
            
        return pd.DataFrame(history)