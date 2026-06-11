"""FastAPI application factory and lifespan management."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from easy_tdx.web.errors import register_exception_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """管理 TDX 连接生命周期：启动时连接，关闭时断开。"""
    from easy_tdx.client import AsyncTdxClient

    host = app.state.tdx_host
    port = app.state.tdx_port
    timeout = app.state.tdx_timeout

    client = AsyncTdxClient(host=host, port=port, timeout=timeout)
    try:
        await client.connect()
        logger.info("TDX client connected to %s:%s", host, port)
    except Exception:
        logger.warning("TDX client connection failed — endpoints will return 503")

    app.state.tdx_client = client
    yield

    try:
        await client.close()
        logger.info("TDX client disconnected")
    except Exception:
        pass


def _create_app(
    host: str | None = None,
    port: int | None = None,
    timeout: float | None = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    from easy_tdx.config import get_best_host, get_port, get_timeout

    if host is None:
        host = get_best_host()
    if port is None:
        port = get_port()
    if timeout is None:
        timeout = get_timeout()

    app = FastAPI(
        title="easy-tdx API",
        description="通达信行情数据 REST + WebSocket API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Store connection config in app.state for lifespan to use
    app.state.tdx_host = host
    app.state.tdx_port = port
    app.state.tdx_timeout = timeout
    app.state.tdx_client = None  # will be set in lifespan

    # CORS middleware (permissive for development)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register exception handlers
    register_exception_handlers(app)

    # Mount routers
    from easy_tdx.web.routers.bars import router as bars_router
    from easy_tdx.web.routers.block import router as block_router
    from easy_tdx.web.routers.chanlun import router as chanlun_router
    from easy_tdx.web.routers.finance import router as finance_router
    from easy_tdx.web.routers.market import router as market_router
    from easy_tdx.web.routers.realtime import router as realtime_router

    app.include_router(market_router, prefix="/api/v1")
    app.include_router(bars_router, prefix="/api/v1")
    app.include_router(finance_router, prefix="/api/v1")
    app.include_router(block_router, prefix="/api/v1")
    app.include_router(chanlun_router, prefix="/api/v1")
    app.include_router(realtime_router, prefix="/api/v1")

    return app
