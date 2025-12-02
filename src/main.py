# src/main.py
import sys
import traceback

# 모듈 경로 설정
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.config import Config
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.utils.calculator import IndicatorCalculator
from src.utils.logger import TradeLogger
from src.infra.data import YFinanceLoader
from src.infra.broker import MockBroker, KisBroker
from src.infra.notifier import TelegramNotifier
from src.infra.repo import JsonRepository
from src.core.models import MarketRegime

class TradingBot:
    def __init__(self):
        # 1. 설정 및 로거 초기화
        self.config = Config()
        self.logger = TradeLogger(self.config.LOG_PATH)
        
        self.logger.info("=== Initializing Trading Bot ===")
        
        # 2. 인프라 객체 생성 (DI)
        self.data_loader = YFinanceLoader()
        self.repo = JsonRepository(self.config.DATA_PATH)
        self.notifier = TelegramNotifier(self.config.TELEGRAM_TOKEN, self.config.TELEGRAM_CHAT_ID)
        
        # 브로커 선택 (실전 vs 모의)
        if self.config.IS_LIVE_TRADING:
            self.logger.info("Mode: LIVE TRADING (KisBroker)")
            # 주의: 실제 계좌 연동 시에는 acc_no 포맷 확인 필요
            self.broker = KisBroker(
                self.config.KIS_APP_KEY, 
                self.config.KIS_APP_SECRET, 
                self.config.KIS_ACC_NO
            )
        else:
            self.logger.info("Mode: PAPER TRADING (MockBroker)")
            self.broker = MockBroker(initial_cash=10000.0) # 테스트용 초기자금

        # 3. 도메인 서비스 및 유틸 생성
        self.calculator = IndicatorCalculator()
        self.analyzer = RegimeAnalyzer()
        self.targeter = VolatilityTargeter(target_vol=0.15)
        self.rebalancer = Rebalancer(self.config.ASSET_GROUPS)

    def run(self):
        try:
            self.logger.info(">>> Step 1: Data Collection")
            # SPY 데이터 수집 (지표 계산용)
            spy_df = self.data_loader.fetch_ohlcv(["SPY"], days=400) # 여유있게 400일
            vix = self.data_loader.fetch_vix()
            
            self.logger.info(">>> Step 2: Indicator Calculation")
            market_data = self.calculator.calculate(spy_df, vix)
            self.logger.info(f"Market Data: Price={market_data.spy_price}, VIX={market_data.vix}, MDD={market_data.spy_mdd:.2%}")
            
            # 위험 감지 (Circuit Breaker)
            if market_data.is_risk_condition():
                msg = f"🚨 DANGER: Market Crash Detected (MDD={market_data.spy_mdd:.1%}, VIX={market_data.vix}). Stopping."
                self.logger.error(msg)
                self.notifier.send_alert(msg)
                return # 즉시 종료

            self.logger.info(">>> Step 3: Strategy Analysis")
            regime = self.analyzer.analyze(market_data)
            exposure = self.targeter.calculate_exposure(regime, market_data.spy_volatility)
            self.logger.info(f"Regime: {regime.value} | Target Exposure: {exposure:.2f}")
            
            self.logger.info(">>> Step 4: Portfolio Rebalancing")
            current_pf = self.broker.get_portfolio()
            self.logger.info(f"Current Portfolio: Cash=${current_pf.total_cash:,.0f}, Value=${current_pf.total_value:,.0f}")
            
            # 현재가 업데이트 (리밸런싱 계산을 위해 전체 티커 최신가 필요)
            # 여기서는 편의상 YFinance로 전체 티커 현재가 조회 후 Portfolio에 주입
            all_tickers = sum(self.config.ASSET_GROUPS.values(), [])
            prices_df = self.data_loader.fetch_ohlcv(all_tickers, days=5)
            # 마지막 종가 추출 로직 (단순화)
            current_prices = {}
            if isinstance(prices_df.columns, pd.MultiIndex):
                for t in all_tickers:
                    try:
                        current_prices[t] = float(prices_df.xs('Close', axis=1, level=0)[t].iloc[-1])
                    except:
                        current_prices[t] = 0.0
            else:
                 # 단일 티커일 경우 등 처리 필요하지만 여기선 생략
                 pass 
            
            # MockBroker인 경우 가격 정보가 없으므로 주입
            current_pf.current_prices = current_prices

            signal = self.rebalancer.generate_signal(current_pf, exposure, regime)
            
            if signal.rebalance_needed:
                self.logger.info(f"Signal Generated: {signal.reason}")
                self.logger.info(f"Executing {len(signal.orders)} orders...")
                
                success = self.broker.execute_orders(signal.orders)
                
                if success:
                    msg = f"✅ Rebalance Completed\nReason: {signal.reason}\nOrders: {len(signal.orders)}"
                    self.notifier.send_message(msg)
                else:
                    self.notifier.send_alert("❌ Order Execution Failed!")
            else:
                self.logger.info("No Rebalance Needed.")
                self.notifier.send_message(f"Bot Finished. Hold. ({regime.value})")

            self.logger.info(">>> Step 5: Archiving Data")
            self.repo.save_daily_summary(market_data, signal, current_pf)
            self.repo.save_trade_history(signal)
            self.repo.update_status(regime, exposure, current_pf)
            
        except Exception as e:
            error_msg = f"Critical Error:\n{traceback.format_exc()}"
            self.logger.error(error_msg)
            self.notifier.send_alert(f"🔥 Bot Crashed!\n{str(e)}")
            raise e # GitHub Actions 실패 처리를 위해 raise

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()