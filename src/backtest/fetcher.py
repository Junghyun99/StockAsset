# src/backtest/fetcher.py
import pandas as pd
from datetime import datetime, timedelta
from src.backtest.cache import BacktestDataCache


def download_historical_data(
    tickers: list,
    start_date: str,
    end_date: str,
    cache: BacktestDataCache = None,
):
    """
    백테스팅용 대량 데이터 다운로드 (캐시 활용)
    :param start_date: '2014-01-01'
    :param end_date: '2024-01-01'
    :param cache: BacktestDataCache 인스턴스. None이면 기본 인스턴스를 생성한다.
    """
    if cache is None:
        cache = BacktestDataCache()

    print(f"📥 Preparing Data for {tickers} ({start_date} ~ {end_date})...")

    # 지표 계산을 위해 start_date보다 500일 전 데이터부터 필요함 (MA180, Mom12M 등)
    real_start = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=500)
    real_start_str = real_start.strftime("%Y-%m-%d")

    df, vix = cache.get_data(tickers, real_start_str, end_date)

    print("✅ Data Ready.")
    return df, vix
