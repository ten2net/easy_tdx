"""screen 命令组 — 策略选股扫描器 CLI。

子命令：
    scan — 纯离线扫描信号
    rank — 回测排名
    strength — 全市场强势股排名（5/20/60 日涨幅加权）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click


@click.group()
def screen() -> None:
    """策略选股扫描器 — 用策略扫描全市场触发信号的股票。

    两步走工作流：

      easy-tdx screen scan --strategy strategies/rsi_reversal.py --output signals.json

      easy-tdx screen rank --from signals.json --sort sharpe --top 20 --table
    """


# ── scan 子命令 ──────────────────────────────────────────────────────────────


@screen.command()
@click.option("--strategy", "strategy_file", required=True, help="策略文件路径")
@click.option("--output", "output_file", default=None, help="输出 JSON 文件路径（默认 stdout）")
@click.option(
    "--universe",
    default="all",
    help="股票范围: all/sh/sz/<文件路径>（默认 all）",
)
@click.option("--vipdoc", default=None, help="离线数据目录（默认自动检测）")
@click.option("--cash", default=100_000.0, type=float, help="初始资金")
@click.option("--commission", default=0.0003, type=float, help="佣金率")
@click.option(
    "--workers",
    default=0,
    type=int,
    help="并发工作进程数: 0=串行（默认），2+=ProcessPoolExecutor 并发（推荐 4-8）",
)
@click.option("--cache", "cache_file", default=None, help="增量扫描缓存文件路径（JSON）")
@click.option(
    "--to-block",
    "to_block",
    default=None,
    help="同时写入通达信自定义板块名称，需配合 --block-dir",
)
@click.option(
    "--block-dir",
    "block_dir",
    default=None,
    help="通达信自定义板块目录路径（如 C:\\new_jyplug\\T0002\\blocknew）",
)
@click.option(
    "--block-mode",
    "block_mode",
    type=click.Choice(["overwrite", "append"]),
    default="overwrite",
    help="写入板块方式: overwrite(覆盖,默认) / append(追加)",
)
def scan(
    strategy_file: str,
    output_file: str | None,
    universe: str,
    vipdoc: str | None,
    cash: float,
    commission: float,
    workers: int,
    cache_file: str | None,
    to_block: str | None,
    block_dir: str | None,
    block_mode: str,
) -> None:
    """纯离线扫描全市场，找出触发买入信号的股票。

    读取本地通达信 .day 文件，零网络 IO，串行约 30-60 秒，并发可提速 4-8 倍。

    示例：

      easy-tdx screen scan --strategy strategies/rsi_reversal.py

      easy-tdx screen scan --strategy strategies/rsi_reversal.py --output signals.json

      easy-tdx screen scan --strategy strategies/rsi_reversal.py --universe sz --workers 4

      easy-tdx screen scan --strategy strategies/rsi_reversal.py --cache scan_cache.json
    """

    strategy_cls = _load_strategy(strategy_file)
    strategy_name = strategy_cls.__name__
    click.echo(f"策略: {strategy_name}", err=True)
    click.echo(f"范围: {universe}", err=True)
    if workers > 0:
        click.echo(f"并发: {workers} 进程", err=True)
    if workers > 0 and cache_file:
        click.echo("注意: 并发模式暂不支持增量缓存，--cache 仅串行模式生效", err=True)
    if cache_file and workers <= 0:
        click.echo(f"缓存: {cache_file}", err=True)

    from .scanner import SignalScanner

    scanner = SignalScanner(
        strategy_cls=strategy_cls,
        vipdoc_path=vipdoc,
        cash=cash,
        commission=commission,
        cache_file=cache_file,
    )

    # 进度回调（输出到 stderr，避免污染 stdout 的 JSON）
    total_scanned = 0

    def on_progress(current: int, total: int, name: str) -> None:
        nonlocal total_scanned
        total_scanned = total
        if name == "done":
            click.echo(f"\r扫描完成: {total} 只", err=True)
        else:
            pct = current * 100 // total if total > 0 else 0
            click.echo(f"\r[{current}/{total}] {pct}% scanning {name}", nl=False, err=True)

    results = scanner.scan(universe=universe, progress_callback=on_progress, workers=workers)

    # 生成 JSON
    json_str = scanner.to_json(
        results=results,
        strategy_name=strategy_name,
        strategy_file=strategy_file,
        total_scanned=total_scanned,
    )

    # 输出
    if output_file:
        Path(output_file).write_text(json_str, encoding="utf-8")
        click.echo(f"信号数: {len(results)} → {output_file}")
    else:
        click.echo(json_str)

    # 写入通达信自定义板块
    if to_block:
        if not block_dir:
            click.echo("错误: --to-block 必须配合 --block-dir 使用", err=True)
            raise SystemExit(1)
        try:
            _write_to_block(results, to_block, block_dir, block_mode)
        except Exception as e:
            click.echo(f"写入板块失败: {e}", err=True)
            raise SystemExit(1)


# ── rank 子命令 ──────────────────────────────────────────────────────────────


@screen.command("rank")
@click.option("--from", "from_source", required=True, help="信号 JSON 文件路径（- 表示 stdin）")
@click.option("--strategy", "strategy_file", default=None, help="覆盖策略文件（默认从 JSON 读取）")
@click.option("--sort", "sort_by", default="sharpe", help="排序指标（默认 sharpe）")
@click.option("--sort-reverse", is_flag=True, help="升序排列（用于回撤等越小越好的指标）")
@click.option("--top", "top_n", default=20, type=int, help="只显示前 N 名（默认 20）")
@click.option("--cash", default=1_000_000.0, type=float, help="初始资金")
@click.option("--count", default=0, type=int, help="使用最近 N 条 K 线，0=全部")
@click.option("--commission", default=0.0003, type=float, help="佣金率")
@click.option("--vipdoc", default=None, help="离线数据目录（默认自动检测）")
@click.option("--names/--no-names", default=False, help="是否在线查询股票名称（默认关闭）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
def rank_cmd(
    from_source: str,
    strategy_file: str | None,
    sort_by: str,
    sort_reverse: bool,
    top_n: int,
    cash: float,
    count: int,
    commission: float,
    vipdoc: str | None,
    names: bool,
    use_table: bool,
) -> None:
    """对扫描结果做历史回测并按指标排名。

    读取 scan 输出的 JSON，对每只股票跑完整回测，按指定指标排序。

    示例：

      easy-tdx screen rank --from signals.json --sort sharpe --top 20 --table

      easy-tdx screen rank --from signals.json --sort max_drawdown --sort-reverse

      easy-tdx screen scan --strategy strats/rsi.py | easy-tdx screen rank --from - --table
    """
    from .ranker import SignalRanker, load_signals

    # 加载信号
    signals, strategy_name, strategy_file_from_json = load_signals(from_source)

    if not signals:
        click.echo("无信号数据，无需排名")
        return

    # 确定策略
    effective_strategy_file = strategy_file or strategy_file_from_json
    if not effective_strategy_file:
        click.echo(
            "错误: 未指定策略文件，请使用 --strategy 或确保 JSON 包含 strategy_file", err=True
        )
        raise SystemExit(1)

    strategy_cls = _load_strategy(effective_strategy_file)
    strategy_name = strategy_cls.__name__

    click.echo(f"策略: {strategy_name} | 信号数: {len(signals)} | 排序: {sort_by}", err=True)

    ranker = SignalRanker(
        strategy_cls=strategy_cls,
        vipdoc_path=vipdoc,
        cash=cash,
        commission=commission,
        count=count,
    )

    # 进度回调（输出到 stderr，避免污染 stdout）
    def on_progress(current: int, total: int, label: str) -> None:
        if label == "done":
            click.echo(f"\r排名完成: {total} 只", err=True)
        else:
            pct = current * 100 // total if total > 0 else 0
            click.echo(f"\r[{current}/{total}] {pct}% backtesting {label}", nl=False, err=True)

    entries = ranker.rank(
        signals=signals,
        sort_by=sort_by,
        sort_reverse=sort_reverse,
        top_n=top_n,
        progress_callback=on_progress,
    )

    # 补齐名称（可选，需要网络）
    if names and entries:
        click.echo("\n正在获取股票名称...", err=True)
        entries = ranker.enrich_names(entries)

    # 输出
    if use_table:
        click.echo(ranker.to_table(entries, sort_by))
    else:
        click.echo(ranker.to_json(entries, strategy_name, sort_by))


# ── strength 子命令 ──────────────────────────────────────────────────────────


@screen.command("strength")
@click.option(
    "--preset",
    default="steady",
    type=click.Choice(["steady", "breakout", "balanced"]),
    help="预设模式: steady(中长期稳健,默认) / breakout(近期妖股) / balanced(均衡)",
)
@click.option("--w5", default=None, type=float, help="自定义 5 日权重（覆盖预设）")
@click.option("--w20", default=None, type=float, help="自定义 20 日权重（覆盖预设）")
@click.option("--w60", default=None, type=float, help="自定义 60 日权重（覆盖预设）")
@click.option(
    "--vol-adjusted/--no-vol-adjusted",
    default=None,
    help="是否波动率惩罚（覆盖预设）",
)
@click.option("--top", "top_n", default=50, type=int, help="返回前 N 名（默认 50）")
@click.option("--universe", default="all", help="范围: all/sh/sz/<文件路径>")
@click.option("--vipdoc", default=None, help="离线数据目录（默认自动检测）")
@click.option("--min-listed-days", default=65, type=int, help="最小上市天数（默认 65）")
@click.option(
    "--min-amount",
    default=0.0,
    type=float,
    help="最近 5 日日均成交额下限（元，默认不过滤）",
)
@click.option(
    "--workers",
    default=0,
    type=int,
    help="并发进程数: 0=串行（默认），4-8 推荐",
)
@click.option("--output", "output_file", default=None, help="输出 JSON 文件（默认 stdout）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--names/--no-names", default=False, help="在线查询股票名称（默认关闭）")
@click.option(
    "--to-block",
    "to_block",
    default=None,
    help="同时写入通达信自定义板块名称（如 '强势股'），需配合 --block-dir",
)
@click.option(
    "--block-dir",
    "block_dir",
    default=None,
    help="通达信自定义板块目录路径（如 C:\\new_jyplug\\T0002\\blocknew）",
)
@click.option(
    "--block-mode",
    "block_mode",
    type=click.Choice(["overwrite", "append"]),
    default="overwrite",
    help="写入板块方式: overwrite(覆盖,默认) / append(追加)",
)
def strength_cmd(
    preset: str,
    w5: float | None,
    w20: float | None,
    w60: float | None,
    vol_adjusted: bool | None,
    top_n: int,
    universe: str,
    vipdoc: str | None,
    min_listed_days: int,
    min_amount: float,
    workers: int,
    output_file: str | None,
    use_table: bool,
    names: bool,
    to_block: str | None,
    block_dir: str | None,
    block_mode: str,
) -> None:
    """全市场强势股排名 — 按 5/20/60 日涨幅加权排序。

    三种预设：

      steady   — 中长期稳健（60日主导 + 波动率惩罚），选稳着涨的票

      breakout — 近期妖股爆发（5日主导，纯涨幅），选最猛的票

      balanced — 三周期均衡 + 波动率调整

    示例：

      easy-tdx screen strength --preset steady --top 50 --table

      easy-tdx screen strength --preset breakout --top 20 --names --table

      easy-tdx screen strength --w5 0.5 --w20 0.3 --w60 0.2 --top 30
    """
    from .strength import StrengthRanker

    click.echo(f"模式: {preset}", err=True)
    click.echo(f"范围: {universe} | Top: {top_n}", err=True)
    if workers > 0:
        click.echo(f"并发: {workers} 进程", err=True)

    ranker = StrengthRanker(
        vipdoc_path=vipdoc,
        preset=preset,
        w5=w5,
        w20=w20,
        w60=w60,
        vol_adjusted=vol_adjusted,
        min_listed_days=min_listed_days,
        min_amount=min_amount,
    )

    def on_progress(current: int, total: int, name: str) -> None:
        if name == "done":
            click.echo(f"\r扫描完成: {total} 只", err=True)
        else:
            pct = current * 100 // total if total > 0 else 0
            click.echo(f"\r[{current}/{total}] {pct}% {name}", nl=False, err=True)

    results = ranker.rank(
        universe=universe,
        top_n=top_n,
        workers=workers,
        progress_callback=on_progress,
    )

    # 数据截止日期（取排名第一的 last_date）
    data_date = results[0].last_date if results else 0

    # 可选补齐名称
    if names and results:
        click.echo("\n获取股票名称...", err=True)
        results = _enrich_strength_names(results)

    if use_table:
        click.echo(ranker.to_table(results, preset, data_date))
    else:
        json_str = ranker.to_json(results, preset, data_date)
        if output_file:
            Path(output_file).write_text(json_str, encoding="utf-8")
            click.echo(f"排名: {len(results)} 只 → {output_file}")
        else:
            click.echo(json_str)

    # 写入通达信自定义板块
    if to_block:
        if not block_dir:
            click.echo("错误: --to-block 必须配合 --block-dir 使用", err=True)
            raise SystemExit(1)
        try:
            _write_to_block(results, to_block, block_dir, block_mode)
        except Exception as e:
            click.echo(f"写入板块失败: {e}", err=True)
            raise SystemExit(1)


# ── intraday 子命令 ──────────────────────────────────────────────────────────


@screen.command("intraday")
@click.option(
    "--period",
    default="5MIN",
    type=click.Choice(["1MIN", "5MIN"]),
    help="分钟线周期: 1MIN / 5MIN（默认 5MIN）",
)
@click.option(
    "--lookback",
    default=6,
    type=int,
    help="统计最近 N 根 K 线的异动（默认 6，即 5MIN 为最近 30 分钟）",
)
@click.option(
    "--min-pct",
    default=2.0,
    type=float,
    help="最近 N 根 K 线累计最小涨幅（%%，默认 2.0，0=不过滤）",
)
@click.option(
    "--volume-ratio",
    default=1.5,
    type=float,
    help="最近 N 根均量相对前 N 根均量的最小倍数（默认 1.5，0=不过滤）",
)
@click.option(
    "--breakout-lookback",
    default=0,
    type=int,
    help="突破近期高低点的观察窗口（0=不判断突破，默认 0）",
)
@click.option("--top", "top_n", default=50, type=int, help="返回前 N 名（默认 50）")
@click.option("--universe", default="all", help="范围: all/sh/sz/<文件路径>")
@click.option("--vipdoc", default=None, help="离线数据目录（默认自动检测）")
@click.option("--output", "output_file", default=None, help="输出 JSON 文件（默认 stdout）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option(
    "--to-block",
    "to_block",
    default=None,
    help="同时写入通达信自定义板块名称，需配合 --block-dir",
)
@click.option(
    "--block-dir",
    "block_dir",
    default=None,
    help="通达信自定义板块目录路径（如 C:\\new_jyplug\\T0002\\blocknew）",
)
@click.option(
    "--block-mode",
    "block_mode",
    type=click.Choice(["overwrite", "append"]),
    default="overwrite",
    help="写入板块方式: overwrite(覆盖,默认) / append(追加)",
)
def intraday_cmd(
    period: str,
    lookback: int,
    min_pct: float,
    volume_ratio: float,
    breakout_lookback: int,
    top_n: int,
    universe: str,
    vipdoc: str | None,
    output_file: str | None,
    use_table: bool,
    to_block: str | None,
    block_dir: str | None,
    block_mode: str,
) -> None:
    """从本地分钟线文件扫描异动个股。

    基于用户自定义规则（N 根 K 线涨幅 + 量比 + 突破）发现盘中异动。

    示例：

      easy-tdx screen intraday --period 5MIN --lookback 6 --min-pct 2.0 --table

      easy-tdx screen intraday --period 5MIN --lookback 3 --volume-ratio 2.0 --top 20

      easy-tdx screen intraday --period 5MIN --breakout-lookback 24 --top 30 --table \
        --to-block 异动 --block-dir "C:\\new_jyplug\\T0002\\blocknew"
    """
    from .intraday import IntradayScanner

    click.echo(f"周期: {period} | 范围: {universe} | Top: {top_n}", err=True)
    click.echo(
        f"规则: 最近 {lookback} 根涨幅≥{min_pct}% 且 量比≥{volume_ratio}",
        err=True,
    )

    scanner = IntradayScanner(
        vipdoc_path=vipdoc,
        period=period,
        lookback=lookback,
        min_pct=min_pct,
        volume_ratio=volume_ratio,
        breakout_lookback=breakout_lookback,
    )

    def on_progress(current: int, total: int, name: str) -> None:
        if name == "done":
            click.echo(f"\r扫描完成: {total} 只", err=True)
        else:
            pct = current * 100 // total if total > 0 else 0
            click.echo(f"\r[{current}/{total}] {pct}% {name}", nl=False, err=True)

    results = scanner.scan(
        universe=universe,
        top_n=top_n,
        progress_callback=on_progress,
    )

    if use_table:
        click.echo(scanner.to_table(results, period))
    else:
        json_str = scanner.to_json(results, period)
        if output_file:
            Path(output_file).write_text(json_str, encoding="utf-8")
            click.echo(f"异动: {len(results)} 只 → {output_file}")
        else:
            click.echo(json_str)

    # 写入通达信自定义板块
    if to_block:
        if not block_dir:
            click.echo("错误: --to-block 必须配合 --block-dir 使用", err=True)
            raise SystemExit(1)
        try:
            _write_to_block(results, to_block, block_dir, block_mode)
        except Exception as e:
            click.echo(f"写入板块失败: {e}", err=True)
            raise SystemExit(1)


# ── monitor 子命令 ───────────────────────────────────────────────────────────


@screen.command("monitor")
@click.option(
    "--block-dir",
    "block_dir",
    required=True,
    help="通达信自定义板块目录路径（如 C:\\new_jyplug\\T0002\\blocknew）",
)
@click.option(
    "--from-block",
    "from_block",
    required=True,
    help="源板块名称（如 '强势股'），从此板块读取监控股票池",
)
@click.option(
    "--period",
    default="5MIN",
    type=click.Choice(["1MIN", "5MIN"]),
    help="K线周期: 1MIN / 5MIN（默认 5MIN）",
)
@click.option(
    "--lookback",
    default=3,
    type=int,
    help="统计最近 N 根 K 线的异动（默认 3）",
)
@click.option(
    "--min-pct",
    default=1.5,
    type=float,
    help="最近 N 根 K 线累计最小涨幅（%%，默认 1.5，0=不过滤）",
)
@click.option(
    "--volume-ratio",
    default=1.5,
    type=float,
    help="最近 N 根均量相对前 N 根均量的最小倍数（默认 1.5，0=不过滤）",
)
@click.option(
    "--workers",
    default=4,
    type=int,
    help="并发线程数（默认 4，0=串行）",
)
@click.option("--top", "top_n", default=50, type=int, help="返回前 N 名（默认 50）")
@click.option("--output", "output_file", default=None, help="输出 JSON 文件（默认 stdout）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option(
    "--to-block",
    "to_block",
    default=None,
    help="把结果写入通达信自定义板块名称，需配合 --block-dir",
)
@click.option(
    "--block-mode",
    "block_mode",
    type=click.Choice(["overwrite", "append"]),
    default="overwrite",
    help="写入板块方式: overwrite(覆盖,默认) / append(追加)",
)
def monitor_cmd(
    block_dir: str,
    from_block: str,
    period: str,
    lookback: int,
    min_pct: float,
    volume_ratio: float,
    workers: int,
    top_n: int,
    output_file: str | None,
    use_table: bool,
    to_block: str | None,
    block_mode: str,
) -> None:
    """从通达信板块读取股票池，在线拉取分钟 K 线监控异动。

    不依赖本地分钟线文件，直接通过行情服务器获取最新 1/5 分钟数据。

    示例：

      easy-tdx screen monitor --block-dir "C:\\new_jyplug\\T0002\\blocknew" \
        --from-block 强势股 --period 5MIN --lookback 3 --table

      easy-tdx screen monitor --block-dir "C:\\new_jyplug\\T0002\\blocknew" \
        --from-block 强势股 --to-block 异动 --top 20
    """
    from ..offline import read_customer_block_codes
    from .monitor import IntradayMonitor

    click.echo(f"源板块: {from_block} | 周期: {period} | Top: {top_n}", err=True)

    try:
        codes = read_customer_block_codes(block_dir, from_block)
    except Exception as e:
        click.echo(f"读取板块失败: {e}", err=True)
        raise SystemExit(1)

    if not codes:
        click.echo("源板块为空，无需监控")
        return

    click.echo(f"股票池: {len(codes)} 只", err=True)
    click.echo(
        f"规则: 最近 {lookback} 根涨幅≥{min_pct}% 且 量比≥{volume_ratio}",
        err=True,
    )

    monitor = IntradayMonitor(
        period=period,
        lookback=lookback,
        min_pct=min_pct,
        volume_ratio=volume_ratio,
    )

    def on_progress(current: int, total: int, label: str) -> None:
        if label == "done":
            click.echo(f"\r监控完成: {total} 只", err=True)
        else:
            pct = current * 100 // total if total > 0 else 0
            click.echo(f"\r[{current}/{total}] {pct}% {label}", nl=False, err=True)

    results = monitor.scan(
        codes=codes,
        top_n=top_n,
        workers=workers,
        progress_callback=on_progress,
    )

    if use_table:
        click.echo(monitor.to_table(results, period))
    else:
        json_str = monitor.to_json(results, period)
        if output_file:
            Path(output_file).write_text(json_str, encoding="utf-8")
            click.echo(f"异动: {len(results)} 只 → {output_file}")
        else:
            click.echo(json_str)

    # 写入通达信自定义板块
    if to_block:
        try:
            _write_to_block(results, to_block, block_dir, block_mode)
        except Exception as e:
            click.echo(f"写入板块失败: {e}", err=True)
            raise SystemExit(1)


def _write_to_block(
    results: list[Any],
    to_block: str,
    block_dir: str,
    block_mode: str,
) -> None:
    """把选股结果写入通达信自定义板块（results 需有 market/code 属性）。"""
    from ..offline import write_customer_block

    filename, count = write_customer_block(
        block_dir=block_dir,
        block_name=to_block,
        codes=[(r.market, r.code) for r in results],
        mode=block_mode,
    )
    click.echo(
        f"已{('追加' if block_mode == 'append' else '覆盖')}写入板块 "
        f"[{to_block}] ({filename}.blk): {count} 只",
        err=True,
    )


def _enrich_strength_names(
    results: list[Any],
) -> list[Any]:
    """在线查询补齐股票名称（复用 ranker 的逻辑）。

    分批查询（每批最多 80 只），避免超出 MAC 协议单次报价上限导致末尾名字丢失。
    """
    try:
        from easy_tdx.cli.parsers import parse_market
        from easy_tdx.mac.client import MacClient

        pairs = [(parse_market(r.market), r.code) for r in results]
        client = MacClient.from_best_host()
        try:
            client.connect()
            # 分批查询：MAC 协议单次最多 80 只，超出部分会被服务器丢弃
            import pandas as pd

            frames: list[pd.DataFrame] = []
            for i in range(0, len(pairs), 80):
                batch = pairs[i : i + 80]
                frames.append(client.get_stock_quotes(batch))
            quotes_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        finally:
            client.close()

        if quotes_df.empty or "name" not in quotes_df.columns:
            return results

        _market_map = {0: "SZ", 1: "SH"}
        name_map: dict[str, str] = {}
        for _, row in quotes_df.iterrows():
            mkt_int = row.get("market", -1)
            mkt_str = _market_map.get(mkt_int, str(mkt_int))
            key = f"{mkt_str}{row.get('code', '')}"
            name_map[key] = str(row.get("name", ""))

        for r in results:
            r.name = name_map.get(f"{r.market}{r.code}", "")
    except Exception:
        # 名称查询失败不影响主流程
        pass

    return results


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _load_strategy(strategy_file: str) -> type:
    """加载策略类（复用 backtest.cli 的加载逻辑）。

    Args:
        strategy_file: 策略文件路径

    Returns:
        Strategy 子类
    """
    import importlib.util

    from easy_tdx.backtest.strategy import Strategy

    file_path = Path(strategy_file)
    if not file_path.exists():
        click.echo(f"错误: 策略文件不存在: {strategy_file}", err=True)
        raise SystemExit(1)

    spec = importlib.util.spec_from_file_location("strategy_module", file_path)
    if spec is None or spec.loader is None:
        click.echo(f"错误: 无法加载策略文件: {strategy_file}", err=True)
        raise SystemExit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 查找 Strategy 子类
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        try:
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                return obj
        except TypeError:
            pass

    click.echo(f"错误: 文件中未找到 Strategy 子类: {strategy_file}", err=True)
    raise SystemExit(1)
