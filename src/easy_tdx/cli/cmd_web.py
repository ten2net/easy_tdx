"""easy-tdx serve — 启动 Web API 服务器。"""

from __future__ import annotations

import click


@click.command("serve")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=8000, type=int, help="监听端口")
@click.option("--tdx-host", default=None, help="TDX 服务器地址（默认自动选择最优）")
@click.option("--tdx-port", default=None, type=int, help="TDX 服务器端口")
@click.option("--reload", is_flag=True, help="开发模式（自动重载）")
def serve(host: str, port: int, tdx_host: str | None, tdx_port: int | None, reload: bool) -> None:
    """启动 Web API 服务器（需要安装 easy-tdx[web]）。"""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "错误：缺少 web 依赖。请运行: pip install easy-tdx[web]",
            err=True,
        )
        raise SystemExit(1) from None

    if reload:
        uvicorn.run(
            "easy_tdx.web:app_factory",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
    else:
        from easy_tdx.web import create_app

        app = create_app(host=tdx_host, port=tdx_port)
        uvicorn.run(app, host=host, port=port)
