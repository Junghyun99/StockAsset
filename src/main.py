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
from src.infra.broker import MockBroker, KisPaperBroker, KisLiveBroker
from src.infra.notifier import TelegramNotifier
from src.infra.notifier import SlackNotifier
from src.infra.repo import JsonRepository
from src.core.models import MarketRegime, Portfolio, MarketData, TradeSignal

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
            self.logger.info("Mode: LIVE TRADING (KisLiveBroker)")
            self.broker = KisLiveBroker(
                self.config.KIS_APP_KEY,
                self.config.KIS_APP_SECRET,
                self.config.KIS_ACC_NO,
                self.logger
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

            # 이전 실행 이후 누락된 거래일을 소급 보정 (리밸런싱 전 포트폴리오 기준)
            self.fill_missing_trading_days(spy_df, pre_trade_pf)

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

    def fill_missing_trading_days(self, spy_df: pd.DataFrame, pre_trade_pf: Portfolio):
        """run() 실행 간격이 N일일 때 빠진 거래일 데이터를 summary.json에 소급 보정.

        spy_df: 이미 fetch한 400일치 SPY OHLCV (거래일 인덱스)
        pre_trade_pf: 오늘 리밸런싱 이전 포트폴리오 (누락 구간 동안 보유 상태)
        """
        last_date_str = self.repo.get_last_summary_date()
        if last_date_str is None:
            return  # 최초 실행 → 이전 기록 없음

        try:
            last_date = pd.Timestamp(last_date_str)
        except Exception:
            self.logger.warning(f"[Backfill] 마지막 날짜 파싱 실패: {last_date_str}")
            return

        today = spy_df.index[-1]
        missing_mask = (spy_df.index > last_date) & (spy_df.index < today)
        missing_dates = spy_df.index[missing_mask]

        if len(missing_dates) == 0:
            return

        self.logger.info(
            f">>> [Backfill] {len(missing_dates)}개 누락 거래일 보정: "
            f"{missing_dates[0].date()} ~ {missing_dates[-1].date()}"
        )

        lookback = len(missing_dates) + 30

        # VIX 히스토리 (실패 시 빈 DataFrame → 기본값 20.0 사용)
        vix_df = pd.DataFrame()
        try:
            vix_df = self.data_loader.fetch_ohlcv(["^VIX"], days=lookback)
        except Exception:
            pass

        # 보유 종목 히스토리
        held_tickers = [t for t, q in pre_trade_pf.holdings.items() if q > 0]
        price_history = pd.DataFrame()
        if held_tickers:
            try:
                price_history = self.data_loader.fetch_ohlcv(held_tickers, days=lookback)
            except Exception:
                pass

        for dt in missing_dates:
            date_str = dt.strftime("%Y-%m-%d")
            sliced_spy = spy_df[spy_df.index <= dt]
            if len(sliced_spy) < 253:
                self.logger.warning(f"[Backfill] {date_str}: 데이터 부족으로 스킵")
                continue

            vix_val = self._get_hist_vix(vix_df, dt)
            try:
                market_data = self.calculator.calculate(sliced_spy, vix_val)
            except ValueError as e:
                self.logger.warning(f"[Backfill] {date_str}: 지표 계산 실패 - {e}")
                continue

            # 해당 날짜의 종목 가격으로 포트폴리오 재구성
            hist_prices = dict(pre_trade_pf.current_prices)
            for ticker in held_tickers:
                p = self._get_hist_close(price_history, ticker, dt)
                if p > 0:
                    hist_prices[ticker] = p

            hist_pf = Portfolio(
                total_cash=pre_trade_pf.total_cash,
                holdings=pre_trade_pf.holdings,
                current_prices=hist_prices,
            )

            regime = self.analyzer.analyze(market_data)
            exposure = self.targeter.calculate_exposure(regime, market_data.spy_volatility)
            signal = TradeSignal(
                target_exposure=exposure,
                orders=[],
                reason=f"{regime.value} (backfill)",
            )

            self.repo.save_daily_summary(market_data, signal, hist_pf)
            self.logger.info(f"[Backfill] {date_str} 저장 완료 ({regime.value})")

    def _get_hist_vix(self, vix_df: pd.DataFrame, dt: pd.Timestamp) -> float:
        """VIX DataFrame에서 dt 이전 가장 최근 Close 반환 (기본값 20.0)"""
        try:
            if vix_df is None or vix_df.empty:
                return 20.0
            if isinstance(vix_df.columns, pd.MultiIndex):
                series = vix_df.xs('Close', axis=1, level=0).iloc[:, 0]
            else:
                series = vix_df['Close']
            avail = series[series.index <= dt].dropna()
            return float(avail.iloc[-1]) if not avail.empty else 20.0
        except Exception:
            return 20.0

    def _get_hist_close(self, price_df: pd.DataFrame, ticker: str, dt: pd.Timestamp) -> float:
        """종목 히스토리에서 ticker의 dt 이전 가장 최근 종가 반환"""
        try:
            if price_df is None or price_df.empty:
                return 0.0
            if isinstance(price_df.columns, pd.MultiIndex):
                close_df = price_df.xs('Close', axis=1, level=0)
                if ticker not in close_df.columns:
                    return 0.0
                series = close_df[ticker]
            else:
                series = price_df['Close']
            avail = series[series.index <= dt].dropna()
            return float(avail.iloc[-1]) if not avail.empty else 0.0
        except Exception:
            return 0.0

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