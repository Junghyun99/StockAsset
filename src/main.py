# src/main.py
import sys
import traceback
import pandas as pd
import time

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
from src.infra.notifier import SlackNotifier
from src.infra.repo import JsonRepository
from src.core.models import MarketRegime, Portfolio, MarketData

class TradingBot:
    def __init__(self):
        # 1. 설정 및 로거 초기화
        self.config = Config()
        self.logger = TradeLogger(self.config.LOG_PATH)
        
        self.logger.info("=== Initializing Trading Bot ===")
        
        # 2. 인프라 객체 생성 (DI)
        self.data_loader = YFinanceLoader(self.logger)
        self.repo = JsonRepository(
            self.config.DATA_PATH,
            max_summary_records=self.config.MAX_SUMMARY_RECORDS,
            max_history_records=self.config.MAX_HISTORY_RECORDS,
        )
        #self.notifier = TelegramNotifier(self.config.TELEGRAM_TOKEN, self.config.TELEGRAM_CHAT_ID)
        self.notifier = SlackNotifier(self.config.SLACK_WEBHOOK_URL, self.logger)
        
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
            self.broker = MockBroker(initial_cash=10000.0, logger=self.logger) # 테스트용 초기자금

        # 3. 도메인 서비스 및 유틸 생성
        self.calculator = IndicatorCalculator()
        self.analyzer = RegimeAnalyzer()
        self.targeter = VolatilityTargeter(target_vol=0.15)
        self.rebalancer = Rebalancer(self.config.ASSET_GROUPS, logger=self.logger)

    def run(self):
        try:
            self.logger.info(">>> Step 1: Data Collection")
            # SPY 데이터 수집 (지표 계산용)
            spy_df = self.data_loader.fetch_ohlcv(["SPY"], days=400) # 여유있게 400일
            vix = self.data_loader.fetch_vix()

            self.logger.info(">>> Step 2: Indicator Calculation")
            market_data = self.calculator.calculate(spy_df, vix)
            self.logger.info(f"Market Data: Price={market_data.spy_price}, VIX={market_data.vix}, MDD={market_data.spy_mdd:.2%}")

            self.logger.info(">>> Step 3: Strategy Analysis")
            nan_fields = market_data.nan_fields()
            if nan_fields:
                self.logger.error(f"NaN detected in: {', '.join(nan_fields)}. Treating as CRASH.")
                regime = MarketRegime.CRASH
                exposure = 0.0
            else:
                regime = self.analyzer.analyze(market_data)
                exposure = self.targeter.calculate_exposure(regime, market_data.spy_volatility)
            self.logger.info(f"Regime: {regime.value} | Target Exposure: {exposure:.2f}")

            self.logger.info(">>> Step 4: Portfolio Rebalancing")
            pre_trade_pf = self.broker.get_portfolio()
            self.logger.info(f"Current Portfolio: Cash=${pre_trade_pf.total_cash:,.0f}, Value=${pre_trade_pf.total_value:,.0f}")

            # 현재가 업데이트 (리밸런싱 계산을 위해 전체 티커 최신가 필요)
            self.logger.info("Fetching Real-time prices from Broker...")
            all_tickers = sum(self.config.ASSET_GROUPS.values(), [])
            real_time_prices = self.broker.fetch_current_prices(all_tickers)
            for t, price in real_time_prices.items():
                if price > 0:
                    pre_trade_pf.current_prices[t] = price

            signal = self.rebalancer.generate_signal(pre_trade_pf, exposure, regime)
            final_pf = pre_trade_pf
            executions = []

            if nan_fields:
                # NaN: 데이터 품질 이상 → CRASH와 동일하게 매매 중단, 알림만 전송
                msg = (
                    f"⚠️ Data Quality Alert — 매매 중단\n"
                    f"날짜: {market_data.date}\n"
                    f"NaN 필드: {', '.join(nan_fields)}\n"
                    f"데이터 품질 이상으로 매매를 중단합니다."
                )
                self.logger.error(msg)
                self.notifier.send_alert(msg)
            elif regime == MarketRegime.CRASH:
                # CRASH: 매매 중단, 포지션 정보 포함 알림 전송, 사용자 액션 대기
                msg = self._build_crash_alert(market_data, pre_trade_pf)
                self.logger.error(msg)
                self.notifier.send_alert(msg)
            elif signal.has_orders:
                self.logger.info(f"Signal Generated: {signal.reason}")
                self.logger.info(f"Executing {len(signal.orders)} orders...")

                executions = self.broker.execute_orders(signal.orders)

                if executions:
                    msg = f"✅ Orders Executed. Count: {len(executions)}"
                    self.notifier.send_message(msg)
                    if self.config.IS_LIVE_TRADING:
                        time.sleep(3)

                    final_pf = self.broker.get_portfolio()
                    self.logger.info(f"Updated Portfolio: Cash=${final_pf.total_cash:,.0f}, Value=${final_pf.total_value:,.0f}")
                else:
                    self.notifier.send_alert("⚠️ Orders sent but NO execution result returned.")
            else:
                self.logger.info("No Rebalance Needed.")
                self.notifier.send_message(f"Bot Finished. Hold. ({regime.value})")

            self.logger.info(">>> Step 5: Archiving Data")
            self.repo.save_daily_summary(market_data, signal, final_pf)
            self.repo.save_trade_history(executions, final_pf, signal.reason)
            self.repo.update_status(regime, exposure, final_pf, market_data, signal.reason)

        except Exception as e:
            error_msg = f"Critical Error:\n{traceback.format_exc()}"
            self.logger.error(error_msg)
            self.notifier.send_alert(f"🔥 Bot Crashed!\n{str(e)}")
            raise e # GitHub Actions 실패 처리를 위해 raise

    def _build_crash_alert(self, market_data: MarketData, portfolio: Portfolio) -> str:
        """CRASH 알림 메시지 생성 (포지션 정보 포함)"""
        holdings_lines = []
        for ticker, qty in portfolio.holdings.items():
            if qty > 0:
                price = portfolio.current_prices.get(ticker, 0)
                value = qty * price
                holdings_lines.append(f"  • {ticker}: {qty}주 (${value:,.0f})")

        if not holdings_lines:
            holdings_lines.append("  • (보유 종목 없음)")

        holdings_info = "\n".join(holdings_lines)

        return (
            f"🚨 CRASH Detected — 매매 중단\n"
            f"MDD: {market_data.spy_mdd:.1%} | VIX: {market_data.vix:.1f}\n"
            f"SPY: ${market_data.spy_price:.2f}\n"
            f"\n"
            f"📊 현재 포지션:\n"
            f"{holdings_info}\n"
            f"💰 현금: ${portfolio.total_cash:,.0f}\n"
            f"📈 총 자산: ${portfolio.total_value:,.0f}\n"
            f"\n"
            f"⏸️ 사용자 액션 대기 중"
        )

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()