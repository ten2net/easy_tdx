"""市场信息路由：证券列表、实时行情、市场统计、资金流向。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import market_from_str
from easy_tdx.web.deps import get_client
from easy_tdx.web.schemas import (
    CountResponse,
    DataFrameResponse,
    QuoteRequest,
)

router = APIRouter(tags=["market"])


def _df_response(df: Any) -> DataFrameResponse:
    """将 DataFrame 转为 API 响应。"""
    return DataFrameResponse.from_dataframe(df)


@router.get("/security/count", response_model=CountResponse)
async def security_count(
    market: str = Query(..., description="市场: SZ, SH, BJ"),
    client: Any = Depends(get_client),
) -> CountResponse:
    """获取市场证券总数。"""
    count = await client.get_security_count(market_from_str(market))
    return CountResponse(count=count)


@router.get("/security/list", response_model=DataFrameResponse)
async def security_list(
    market: str = Query(..., description="市场: SZ, SH, BJ"),
    start: int = Query(0, ge=0, description="分页起始位置"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取证券列表（每页约1000条）。"""
    df = await client.get_security_list(market_from_str(market), start)
    return _df_response(df)


@router.get("/security/list-all", response_model=DataFrameResponse)
async def security_list_all(
    pages: int = Query(1, ge=1, description="拉取页数（每个市场每页1000条）"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取沪深 A 股完整列表。"""
    df = await client.get_security_list_all(pages=pages)
    return _df_response(df)


@router.post("/quotes", response_model=DataFrameResponse)
async def security_quotes(
    req: QuoteRequest,
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """批量获取实时五档行情（最多80只/次）。"""
    stocks_parsed: list[tuple[Any, str]] = []
    for s in req.stocks:
        m = market_from_str(s.market)
        stocks_parsed.append((m, s.code))
    df = await client.get_security_quotes(stocks_parsed)
    return _df_response(df)


@router.get("/market/stat", response_model=DataFrameResponse)
async def market_stat(
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取 A 股全市场涨跌统计。"""
    df = await client.get_market_stat()
    return _df_response(df)


@router.get("/fund-flow", response_model=DataFrameResponse)
async def fund_flow(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取个股当日资金流向。"""
    df = await client.get_fund_flow(market_from_str(market), code)
    return _df_response(df)


@router.get("/fund-flow/history", response_model=DataFrameResponse)
async def history_fund_flow(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    start: int = Query(0, ge=0),
    count: int = Query(100, ge=1, le=800),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取个股历史日线资金流向。"""
    df = await client.get_history_fund_flow(market_from_str(market), code, start, count)
    return _df_response(df)
