"""엔진 공통 데이터 수집 계약.

전략은 필요한 데이터셋만 선언하고, 실제 IDataProvider 호출 순서와 VIX 수집은
TradingEngine이 담당한다.
"""

from dataclasses import dataclass, field
from typing import Mapping, Tuple

import pandas as pd


@dataclass(frozen=True)
class DataSetSpec:
    """한 OHLCV 데이터셋의 조회 명세."""

    key: str
    tickers: Tuple[str, ...]
    days: int = 400

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("dataset key must not be empty")
        if not self.tickers:
            raise ValueError(f"dataset '{self.key}' must declare at least one ticker")
        if self.days <= 0:
            raise ValueError(f"dataset '{self.key}' days must be positive")


@dataclass(frozen=True)
class StrategyDataSpec:
    """기준 지표 데이터와 전략 전용 데이터 선언."""

    reference: DataSetSpec
    strategy: Tuple[DataSetSpec, ...] = ()

    def __post_init__(self) -> None:
        specs = self.datasets
        keys = [spec.key for spec in specs]
        if len(keys) != len(set(keys)):
            raise ValueError("dataset keys must be unique")

    @property
    def datasets(self) -> Tuple[DataSetSpec, ...]:
        return (self.reference, *self.strategy)


@dataclass(frozen=True)
class CollectedData:
    """한 사이클에서 수집한 원천 데이터 묶음."""

    frames: Mapping[str, pd.DataFrame] = field(repr=False)
    vix: float
    spec: StrategyDataSpec

    def frame(self, key: str) -> pd.DataFrame:
        try:
            return self.frames[key]
        except KeyError as error:
            raise KeyError(f"dataset '{key}' was not collected") from error

    @property
    def reference(self) -> pd.DataFrame:
        return self.frame(self.spec.reference.key)
