"""分钟线异动扫描引擎 — 从本地 .5/.lc5 文件发现异动个股。

支持自定义规则：
- N 根 K 线累计涨幅
- N 根成交量相对前 N 根的放量倍数
- 突破近期高点/低点
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from easy_tdx.exceptions import TdxFileNotFoundError
from easy_tdx.offline.daily_bar import _detect_security_type
from easy_tdx.offline.min_bar import read_5min_bars, read_lc_min_bars
from easy_tdx.offline.paths import resolve_vipdoc

_A_STOCK_TYPES = frozenset({"SH_A_STOCK", "SZ_A_STOCK"})

# period → 文件扩展名与读取函数
_PERIOD_FILES: dict[str, list[tuple[str, Any]]] = {
    "1MIN": [(".lc1", read_lc_min_bars)],
    "5MIN": [(".5", read_5min_bars), (".lc5", read_lc_min_bars)],
}


@dataclass
class IntradayResult:
    """单只股票的分钟线异动结果。"""

    rank: int = 0
    code: str = ""
    market: str = ""
    last_close: float = 0.0
    last_time: str = ""
    pct_n: float = 0.0
    volume_ratio: float = 0.0
    breakout_high: float | None = None
    breakout_low: float | None = None
    score: float = 0.0


class IntradayScanner:
    """本地分钟线异动扫描器。

    用法::

        scanner = IntradayScanner(period="5MIN", lookback=6, min_pct=2.0)
        results = scanner.scan(universe="all")
        for r in results[:10]:
            print(f"{r.market}{r.code} 最近{r.lookback}根5分钟涨幅 {r.pct_n:.2f}%")
    """

    def __init__(
        self,
        vipdoc_path: str | Path | None = None,
        period: str = "5MIN",
        lookback: int = 6,
        min_pct: float = 2.0,
        volume_ratio: float = 1.5,
        breakout_lookback: int = 0,
        min_bars: int = 30,
    ) -> None:
        """初始化扫描器。

        Args:
            vipdoc_path: vipdoc 目录路径，None 则自动检测
            period: 周期，当前支持 1MIN / 5MIN
            lookback: 计算异动用的最近 K 线根数 N
            min_pct: 最近 N 根 K 线累计最小涨幅（%），0 表示不过滤
            volume_ratio: 最近 N 根均量相对前 N 根均量的最小倍数，0 表示不过滤
            breakout_lookback: 突破近期高低点的观察窗口（0=不判断突破）
            min_bars: 单只股票最少需要的数据条数
        """
        if period not in _PERIOD_FILES:
            raise ValueError(f"不支持周期 '{period}'，可选: {list(_PERIOD_FILES.keys())}")
        self._vipdoc = resolve_vipdoc(vipdoc_path)
        self._period = period
        self._lookback = max(1, lookback)
        self._min_pct = min_pct / 100.0
        self._volume_ratio = volume_ratio
        self._breakout_lookback = max(0, breakout_lookback)
        self._min_bars = max(self._lookback * 2 + 1, min_bars)

    @property
    def period(self) -> str:
        """当前周期。"""
        return self._period

    def scan(
        self,
        universe: str = "all",
        top_n: int = 50,
        progress_callback: Any = None,
        workers: int = 0,
    ) -> list[IntradayResult]:
        """扫描全市场并返回异动个股。

        Args:
            universe: all/sh/sz/<文件路径>
            top_n: 返回前 N 名，0=全部
            progress_callback: 回调(current, total, name)
            workers: 并发进程数（当前仅支持串行，保留参数用于后续扩展）

        Returns:
            按异动分数降序排列的 IntradayResult 列表
        """
        files = self._collect_files(universe)
        if not files:
            return []
        total = len(files)

        # 并发可后续扩展，当前先串行
        _ = workers

        results: list[IntradayResult] = []
        for idx, (filepath, market, code) in enumerate(files):
            if progress_callback:
                progress_callback(idx, total, filepath.name)
            try:
                r = self._compute_one(filepath, market, code)
                if r is not None:
                    results.append(r)
            except Exception:
                continue

        if progress_callback:
            progress_callback(total, total, "done")

        # 排序 + 赋名次
        results.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        if top_n > 0:
            results = results[:top_n]
        return results

    def _collect_files(self, universe: str) -> list[tuple[Path, str, str]]:
        """收集需要扫描的分钟线文件列表。"""
        exchanges: list[str] = []
        if universe in ("all", "sz"):
            exchanges.append("sz")
        if universe in ("all", "sh"):
            exchanges.append("sh")

        if universe not in ("all", "sh", "sz"):
            return self._collect_from_file(universe)

        files: list[tuple[Path, str, str]] = []
        for exchange in exchanges:
            fzline_dir = self._vipdoc / exchange / "fzline"
            if not fzline_dir.is_dir():
                continue

            # 按扩展名优先级收集文件
            seen: set[str] = set()
            for ext, _ in _PERIOD_FILES[self._period]:
                for filepath in sorted(fzline_dir.glob(f"*{ext}")):
                    name = filepath.name.lower()
                    code = name[2:8]
                    if code in seen:
                        continue
                    sec_type = _detect_security_type(name[:8] + ".day")
                    if sec_type not in _A_STOCK_TYPES:
                        continue
                    seen.add(code)
                    files.append((filepath, exchange.upper(), code))

        return files

    def _collect_from_file(self, filepath: str) -> list[tuple[Path, str, str]]:
        """从文件读取股票列表（每行 "市场 代码"）。"""
        path = Path(filepath)
        if not path.is_file():
            raise FileNotFoundError(f"股票列表文件不存在: {filepath}")

        files: list[tuple[Path, str, str]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                market_str = parts[0].upper()
                code = parts[1]
                exchange = market_str.lower()

                # 按扩展名优先级查找分钟线文件
                fzline_dir = self._vipdoc / exchange / "fzline"
                found = False
                for ext, _ in _PERIOD_FILES[self._period]:
                    min_file = fzline_dir / f"{exchange}{code}{ext}"
                    if min_file.is_file():
                        files.append((min_file, market_str, code))
                        found = True
                        break
                if not found:
                    continue
        return files

    def _read_bars(self, filepath: Path) -> list[Any]:
        """按扩展名读取分钟线数据。"""
        suffix = filepath.suffix.lower()
        if suffix == ".5":
            return read_5min_bars(filepath)
        if suffix in (".lc1", ".lc5"):
            return read_lc_min_bars(filepath)
        raise TdxFileNotFoundError(f"不支持的分钟线文件格式: {filepath}")

    def _compute_one(self, filepath: Path, market: str, code: str) -> IntradayResult | None:
        """计算单只股票的异动指标。"""
        bars = self._read_bars(filepath)
        if len(bars) < self._min_bars:
            return None

        df = pd.DataFrame(
            {
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "vol": [b.vol for b in bars],
                "amount": [b.amount for b in bars],
                "datetime": [datetime(b.year, b.month, b.day, b.hour, b.minute) for b in bars],
            }
        )

        n = self._lookback
        recent = df.iloc[-n:]
        prev = df.iloc[-n * 2 : -n]

        # 涨幅
        pct_n = recent["close"].iloc[-1] / recent["open"].iloc[0] - 1

        # 成交量比
        recent_vol = recent["vol"].mean()
        prev_vol = prev["vol"].mean() if len(prev) > 0 else 0
        volume_ratio = recent_vol / prev_vol if prev_vol > 0 else 0.0

        # 突破
        breakout_high = None
        breakout_low = None
        if self._breakout_lookback > 0:
            window = df.iloc[-(n + self._breakout_lookback) : -n]
            if len(window) > 0:
                if recent["close"].iloc[-1] > window["high"].max():
                    breakout_high = window["high"].max()
                if recent["close"].iloc[-1] < window["low"].min():
                    breakout_low = window["low"].min()

        # 过滤
        if self._min_pct > 0 and pct_n < self._min_pct:
            return None
        if self._volume_ratio > 0 and volume_ratio < self._volume_ratio:
            return None

        # 综合分数：涨幅 + 放量幅度 + 突破加分
        score = pct_n
        if self._volume_ratio > 0:
            score += (volume_ratio - 1) * 0.1
        if breakout_high is not None:
            score += 0.005
        if breakout_low is not None:
            score -= 0.005

        last = df.iloc[-1]
        return IntradayResult(
            code=code,
            market=market,
            last_close=last["close"],
            last_time=last["datetime"].strftime("%Y-%m-%d %H:%M"),
            pct_n=pct_n,
            volume_ratio=volume_ratio,
            breakout_high=breakout_high,
            breakout_low=breakout_low,
            score=score,
        )

    @staticmethod
    def to_json(results: list[IntradayResult], period: str) -> str:
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
                    "last_close": r.last_close,
                    "last_time": r.last_time,
                    "pct_n": r.pct_n,
                    "volume_ratio": r.volume_ratio,
                    "breakout_high": r.breakout_high,
                    "breakout_low": r.breakout_low,
                    "score": r.score,
                }
                for r in results
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)

    @staticmethod
    def to_table(results: list[IntradayResult], period: str) -> str:
        """将结果格式化为表格字符串。"""
        if not results:
            return "无有效异动结果"

        lines = [
            f"[*] 分钟线异动扫描 [{period}] 共 {len(results)} 只",
            "=" * 90,
            f"{'排名':>4}  {'代码':<10} {'时间':<16} {'现价':>10} "
            f"{'N根涨幅':>10} {'量比':>8} {'分数':>8}",
            "-" * 90,
        ]
        for r in results:
            lines.append(
                f"{r.rank:>4}  {r.market}{r.code:<9} {r.last_time:<16} {r.last_close:>9.2f} "
                f"{r.pct_n:>9.2%} {r.volume_ratio:>8.2f} {r.score:>8.4f}"
            )
        return "\n".join(lines)


def _json_default(obj: Any) -> Any:
    """JSON 序列化辅助。"""
    if hasattr(obj, "item"):
        return obj.item()
    raise TypeError(f"无法序列化 {type(obj)}")
