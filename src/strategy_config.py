import os
from dotenv import load_dotenv

load_dotenv()


class StrategyConfig:
    """전략 핵심 파라미터 설정.

    인프라 설정(API 키, 경로 등)과 분리하여 시나리오별로 독립적으로
    생성·주입할 수 있도록 한 전략 전용 설정 클래스.

    사용 예시::

        # 기본값 (환경변수 또는 하드코딩된 기본값)
        cfg = StrategyConfig()

        # 시나리오 테스트용 오버라이드
        cfg = StrategyConfig(
            asset_groups={'A': ['SSO'], 'B': ['IEF'], 'C': ['SHV']},
            trading_interval_days=10,
            rebalance_ratio_a=0.7,
        )
    """

    def __init__(
        self,
        asset_groups: dict | None = None,
        trading_interval_days: int | None = None,
        rebalance_ratio_a: float | None = None,
    ):
        # 1. 자산군 정의
        self.ASSET_GROUPS: dict = asset_groups or {
            'A': ['SSO', 'QLD'],           # 성장성
            'B': ['IEF', 'GLD', 'DBC'],   # 안전성
            'C': ['SHV'],                  # 현금성
        }

        # 2. 리밸런싱 인터벌 (거래일 기준)
        self.TRADING_INTERVAL_DAYS: int = (
            trading_interval_days
            if trading_interval_days is not None
            else int(os.getenv("TRADING_INTERVAL_DAYS", "1"))
        )

        # 3. 리밸런싱 A:B 비율 (A그룹 비율, B = 1 - A)
        self.REBALANCE_RATIO_A: float = (
            rebalance_ratio_a
            if rebalance_ratio_a is not None
            else float(os.getenv("REBALANCE_RATIO_A", "0.5"))
        )
