# src/backtest/fetcher.py
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def download_historical_data(tickers: list, start_date: str, end_date: str):
    """
    백테스팅용 대량 데이터 다운로드
    :param start_date: '2014-01-01'
    :param end_date: '2024-01-01'
    """
    print(f"📥 Downloading Data for {tickers} ({start_date} ~ {end_date})...")
    
    # 지표 계산을 위해 start_date보다 400일 전 데이터부터 필요함 (MA180, Mom12M 등)
    real_start = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=500)
    
    # 1. 주가 데이터 (수정주가 반영)
    df = yf.download(tickers, start=real_start, end=end_date, auto_adjust=True, progress=True)
    
    # MultiIndex 정리 (Close만 추출하지 않고 전체 유지, Loader에서 처리)
    
    # 2. VIX 데이터
    vix = yf.download("^VIX", start=real_start, end=end_date, progress=False)
    
    print("✅ Download Complete.")
    return df, vix