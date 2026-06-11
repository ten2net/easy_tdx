"""Pydantic request/response schemas for the Web API."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums — mirror easy_tdx.models.enums but as string-based for REST clarity
# ---------------------------------------------------------------------------


class MarketEnum(IntEnum):
    """Market identifier."""

    SZ = 0
    SH = 1
    BJ = 2


class KlineCategoryEnum(IntEnum):
    """K-line period."""

    MIN_5 = 0
    MIN_15 = 1
    MIN_30 = 2
    MIN_60 = 3
    DAY = 4
    WEEK = 5
    MONTH = 6
    MIN_1 = 7
    YEAR = 9
    SEASON = 10


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StockIdentifier(BaseModel):
    """A single stock identified by market + code."""

    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$", description="市场代码")
    code: str = Field(..., min_length=6, max_length=6, description="6位股票代码")


class QuoteRequest(BaseModel):
    """Batch quote request."""

    stocks: list[StockIdentifier] = Field(
        ..., min_length=1, max_length=80, description="股票列表（最多80只）"
    )


class ChanlunRequest(BaseModel):
    """缠论分析请求。"""

    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$")
    code: str = Field(..., min_length=6, max_length=6)
    category: str = Field(default="DAY", description="K线周期")
    count: int = Field(default=800, ge=1, le=800)
    start: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DataFrameResponse(BaseModel):
    """通用 DataFrame 响应（records 格式）。"""

    data: list[dict[str, Any]]
    count: int

    @classmethod
    def from_dataframe(cls, df: Any) -> DataFrameResponse:
        """从 pandas DataFrame 构建响应。"""
        import pandas as pd

        if isinstance(df, pd.DataFrame):
            records = df.to_dict(orient="records")
            cleaned: list[dict[str, Any]] = []
            for row in records:
                clean_row: dict[str, Any] = {}
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        clean_row[k] = v.isoformat()
                    elif hasattr(v, "item"):
                        # numpy scalar → Python native
                        clean_row[k] = v.item()
                    else:
                        clean_row[k] = v
                cleaned.append(clean_row)
            return cls(data=cleaned, count=len(cleaned))
        return cls(data=[], count=0)


class CountResponse(BaseModel):
    """简单计数响应。"""

    count: int
