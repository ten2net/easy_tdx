"""在线分钟线异动监控引擎 — 从通达信板块读取股票池，实时拉取 K 线发现异动。

不依赖本地分钟线文件，直接通过 MAC 协议在线获取最新 1/5 分钟 K 线。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..mac.enums import Adjust, Period


@dataclass
class MonitorResult:
    """单只股票的在线分钟线监控结果。"""

    rank: int = 0
    code: str = ""
    market: str = ""
    name: str = ""
    last_close: float = 0.0
    last_time: str = ""
    pct_n: float = 0.0
    volume_ratio: float = 0.0
    score: float = 0.0


_MARKET_INT_MAP: dict[str, int] = {
    "SZ": 0,
    "SH": 1,
    "BJ": 2,
}


class IntradayMonitor:
    """在线分钟线异动监控器。

    用法::

        monitor = IntradayMonitor(period="5MIN", lookback=3, min_pct=1.5)
        codes = [("SH", "600000"), ("SZ", "000001")]
        results = monitor.scan(codes)
        for r in results[:10]:
            print(f"{r.market}{r.code} 最近{r.lookback}根5分钟涨幅 {r.pct_n:.2f}%")
    """

    def __init__(
        self,
        period: str = "5MIN",
        lookback: int = 3,
        min_pct: float = 1.5,
        volume_ratio: float = 1.5,
        fetch_count: int = 50,
    ) -> None:
        """初始化监控器。

        Args:
            period: K 线周期，当前支持 1MIN / 5MIN
            lookback: 计算异动用的最近 K 线根数 N
            min_pct: 最近 N 根 K 线累计最小涨幅（%），0 表示不过滤
            volume_ratio: 最近 N 根均量相对前 N 根均量的最小倍数，0 表示不过滤
            fetch_count: 向服务器请求的 K 线数量（默认 50，需 >= lookback*2）
        """
        period_map = {"1MIN": Period.MIN_1, "5MIN": Period.MIN_5}
        if period not in period_map:
            raise ValueError(f"不支持周期 '{period}'，可选: 1MIN / 5MIN")
        self._period = period_map[period]
        self._period_label = period
        self._lookback = max(1, lookback)
        self._min_pct = min_pct / 100.0
        self._volume_ratio = volume_ratio
        self._fetch_count = max(self._lookback * 2 + 5, fetch_count)

    @property
    def period(self) -> str:
        """当前周期。"""
        return self._period_label

    def scan(
        self,
        codes: list[tuple[str, str]],
        top_n: int = 0,
        progress_callback: Any = None,
        workers: int = 4,
    ) -> list[MonitorResult]:
        """拉取股票池的分钟线并返回异动列表。

        Args:
            codes: 股票池，每个元素为 (market, code)
            progress_callback: 回调(current, total, label)
            workers: 并发线程数，0=串行

        Returns:
            按异动分数降序排列的 MonitorResult 列表
        """
        if not codes:
            return []

        total = len(codes)
        results: list[MonitorResult] = []

        if workers <= 0:
            for idx, (market, code) in enumerate(codes):
                if progress_callback:
                    progress_callback(idx, total, f"{market}{code}")
                r = self._compute_one(market, code)
                if r is not None:
                    results.append(r)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self._compute_one, market, code): (idx, market, code)
                    for idx, (market, code) in enumerate(codes)
                }
                completed = 0
                for future in futures:
                    idx, market, code = futures[future]
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total, f"{market}{code}")
                    try:
                        r = future.result()
                        if r is not None:
                            results.append(r)
                    except Exception:
                        continue

        if progress_callback:
            progress_callback(total, total, "done")

        results.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1
        if top_n > 0:
            results = results[:top_n]
        return results

    def _compute_one(self, market: str, code: str) -> MonitorResult | None:
        """获取单只股票 K 线并计算异动指标。"""
        from ..mac.client import MacClient

        mkt_int = _MARKET_INT_MAP.get(market.upper())
        if mkt_int is None:
            raise ValueError(f"不支持的市场 '{market}'")

        with MacClient.from_best_host() as client:
            df = client.get_stock_kline(
                mkt_int,
                code,
                period=self._period,
                count=self._fetch_count,
                adjust=Adjust.NONE,  # 分钟线不复权，保证最新价准确
            )

        if df is None or df.empty or len(df) < self._lookback * 2:
            return None

        df = df.sort_values("datetime").reset_index(drop=True)
        n = self._lookback

        recent = df.iloc[-n:]
        prev = df.iloc[-n * 2 : -n]

        pct_n = recent["close"].iloc[-1] / recent["open"].iloc[0] - 1
        recent_vol = recent["vol"].mean()
        prev_vol = prev["vol"].mean() if len(prev) > 0 else 0
        volume_ratio = recent_vol / prev_vol if prev_vol > 0 else 0.0

        if self._min_pct > 0 and pct_n < self._min_pct:
            return None
        if self._volume_ratio > 0 and volume_ratio < self._volume_ratio:
            return None

        score = pct_n
        if self._volume_ratio > 0:
            score += (volume_ratio - 1) * 0.1

        last = df.iloc[-1]
        return MonitorResult(
            code=code,
            market=market.upper(),
            name=str(last.get("name", "")),
            last_close=float(last["close"]),
            last_time=str(last["datetime"]),
            pct_n=pct_n,
            volume_ratio=volume_ratio,
            score=score,
        )

    @staticmethod
    def to_json(results: list[MonitorResult], period: str) -> str:
        """将结果序列化为 JSON 字符串。"""
        data = {
            "scan_time": datetime.now().isoformat(timespec="seconds"),
            "period": period,
            "total": len(results),
            "ranking": [
                {
                    "rank": r.rank,
                    "code": r.code,
                    "market": r.market,
                    "name": r.name,
                    "last_close": r.last_close,
                    "last_time": r.last_time,
                    "pct_n": r.pct_n,
                    "volume_ratio": r.volume_ratio,
                    "score": r.score,
                }
                for r in results
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)

    @staticmethod
    def to_table(results: list[MonitorResult], period: str) -> str:
        """将结果格式化为表格字符串。"""
        if not results:
            return "无有效异动结果"

        lines = [
            f"[*] 在线分钟线监控 [{period}] 共 {len(results)} 只",
            "=" * 100,
            f"{'排名':>4}  {'代码':<10} {'名称':<8} {'时间':<20} {'现价':>10} "
            f"{'N根涨幅':>10} {'量比':>8} {'分数':>8}",
            "-" * 100,
        ]
        for r in results:
            name = r.name[:6] if r.name else ""
            lines.append(
                f"{r.rank:>4}  {r.market}{r.code:<9} {name:<8} {r.last_time:<20} "
                f"{r.last_close:>9.2f} {r.pct_n:>9.2%} {r.volume_ratio:>8.2f} {r.score:>8.4f}"
            )
        return "\n".join(lines)


def _json_default(obj: Any) -> Any:
    """JSON 序列化辅助。"""
    if hasattr(obj, "item"):
        return obj.item()
    raise TypeError(f"无法序列化 {type(obj)}")
