# src/core/engine/simple.py
"""설정 전용 Full Exposure 전략 엔진 모음.

이 파일의 엔진들은 FullExposureEngine을 상속하며 클래스 속성
(ASSET_GROUPS, REBALANCE_RATIO_A)만 정의한다. 별도 메서드 오버라이드 없음.
"""
from src.core.engine.base import FullExposureEngine
from src.core.engine.registry import register_engine


@register_engine(color="#ff7f0e", backtest=False)
class QldSHVEngine(FullExposureEngine):
    """QLD(A그룹) + SHV(B그룹)만으로 구성된 Full Exposure 전략 엔진.

    - 자산군 A: [QLD]  (레버리지 나스닥 ETF)
    - 자산군 B: [SHV]  (초단기 국채 ETF — 현금 대용)
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - A:B 비율은 Rebalancer 기본값(0.5:0.5) 적용
    """

    ASSET_GROUPS: dict = {
        'A': ['QLD'],
        'B': ['SHV'],
    }



@register_engine(color="#d62728", backtest=False)
class QldSdyEngine(FullExposureEngine):
    """QLD(A그룹) + SDY(B그룹)으로 구성된 Full Exposure 전략 엔진.

    - 자산군 A: [QLD]  (레버리지 나스닥 ETF)
    - 자산군 B: [SDY] (배당 성장 ETF)
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - A:B 비율 = 0.3:0.7 (성장보다 배당 비중 강조)
    """

    ASSET_GROUPS: dict = {
        'A': ['QLD'],
        'B': ['SDY'],
    }
    REBALANCE_RATIO_A: float = 0.3


@register_engine(color="#1f77b4", backtest=False)
class QqqSdyEngine(FullExposureEngine):
    """QQQ(A그룹) + SDY(B그룹)으로 구성된 Full Exposure 전략 엔진.

    - 자산군 A: [QQQ]  (나스닥 100 ETF)
    - 자산군 B: [SDY] (배당 성장 ETF)
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - A:B 비율 = 0.3:0.7 (성장보다 배당 비중 강조)
    """

    ASSET_GROUPS: dict = {
        'A': ['QQQ'],
        'B': ['SDY'],
    }
    REBALANCE_RATIO_A: float = 0.3


@register_engine(color="#fd7e14")
class SpyEngine(FullExposureEngine):
    """SPY Buy&Hold 벤치마크 시뮬레이션 엔진.

    - 자산군 A: [SPY]  (S&P500 ETF — 벤치마크 자산)
    - 자산군 B: [SHV]  (초단기 국채 ETF — 잔여 현금 대용)
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - REBALANCE_RATIO_A=0.999 → 사실상 100% SPY 투자
      (ratio_a=1.0은 Rebalancer 내부 ZeroDivisionError 방지 제약으로 사용 불가)
    """

    ASSET_GROUPS: dict = {
        'A': ['SPY'],
        'B': ['SHV'],
    }
    REBALANCE_RATIO_A: float = 0.999


@register_engine(color="#17becf")
class QqqEngine(FullExposureEngine):
    """QQQ Buy&Hold 벤치마크 시뮬레이션 엔진.

    - 자산군 A: [QQQ]  (나스닥100 ETF — 벤치마크 자산)
    - 자산군 B: [SHV]  (초단기 국채 ETF — 잔여 현금 대용)
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - REBALANCE_RATIO_A=0.999 → 사실상 100% QQQ 투자
      (ratio_a=1.0은 Rebalancer 내부 ZeroDivisionError 방지 제약으로 사용 불가)
    """

    ASSET_GROUPS: dict = {
        'A': ['QQQ'],
        'B': ['SHV'],
    }
    REBALANCE_RATIO_A: float = 0.999


@register_engine(color="#9467bd", backtest=False)
class Asset5Engine(FullExposureEngine):
    """자산5분법 — SPY/IEMG(A그룹) + TLT/EMB/GLD(B그룹) Full Exposure 전략 엔진.

    - 자산군 A: [SPY, IEMG]  (미국/신흥국 주식 ETF)
    - 자산군 B: [TLT, EMB, GLD] (장기국채, 신흥국채권, 금 ETF)
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - A:B 비율 = 0.4:0.6 (안전자산 비중 강조)
    """

    ASSET_GROUPS: dict = {
        'A': ['SPY', 'EEM'],
        'B': ['TLT', 'EMB', 'GLD'],
    }
    REBALANCE_RATIO_A: float = 0.4


@register_engine(color="#e377c2")
class SsoSpyiEngine(FullExposureEngine):
    """SSO(A그룹) + SPYI(B그룹) Full Exposure 전략 엔진.

    - 자산군 A: [SSO]  (S&P500 2x 레버리지 ETF)
    - 자산군 B: [SPYI] (S&P500 High Income ETF — 커버드콜)
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - A:B 비율 = 0.4:0.6 (인컴 비중 강조)
    """

    ASSET_GROUPS: dict = {
        'A': ['SSO'],
        'B': ['SPYI'],
    }
    REBALANCE_RATIO_A: float = 0.4


@register_engine(color="#bcbd22", market_type="domestic",backtest=False)
class DomesticAsset5Engine(FullExposureEngine):
    """국내 자산5분법 — KODEX200/TIGER MSCI Korea(A그룹) + ACE 미국S&P500/TIGER 미국채10년/ACE 미국30년국채(B그룹) Full Exposure 전략 엔진.

    - 자산군 A: [069500(KODEX 200), 360750(TIGER MSCI Korea TR)]
    - 자산군 B: [411060(ACE 미국S&P500), 305080(TIGER 미국채10년선물), 365780(ACE 미국30년국채)]
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - A:B 비율 = 0.4:0.6 (안전자산 비중 강조)
    """

    ASSET_GROUPS: dict = {
        'A': ['069500.KS', '143850.KS'],
        'B': ['132030.KS', '305080.KS', '148070.KS'],
    }
    REBALANCE_RATIO_A: float = 0.4

@register_engine(color="#bdbd42", market_type="domestic",backtest=False)
class DomesticAsset5RealEngine(FullExposureEngine):
    """국내 자산5분법 — KODEX200/TIGER MSCI Korea(A그룹) + ACE 미국S&P500/TIGER 미국채10년/ACE 미국30년국채(B그룹) Full Exposure 전략 엔진.

    - 자산군 A: [069500(KODEX 200), 360750(TIGER MSCI Korea TR)]
    - 자산군 B: [411060(ACE 미국S&P500), 305080(TIGER 미국채10년선물), 365780(ACE 미국30년국채)]
    - exposure=1.0 항상 유지 (FullExposureEngine 상속)
    - A:B 비율 = 0.4:0.6 (안전자산 비중 강조)
    """

    ASSET_GROUPS: dict = {
        'A': ['226490.KS', '133690.KS'],
        'B': ['365780.KS', '305080.KS', '411060.KS'],
    }
    REBALANCE_RATIO_A: float = 0.4
