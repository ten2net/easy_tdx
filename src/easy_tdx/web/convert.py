"""共享参数转换工具（market/category 字符串 → 枚举）。"""

from __future__ import annotations

from typing import Any

from easy_tdx.web.schemas import KlineCategoryEnum, MarketEnum


def market_from_str(s: str) -> Any:
    """将字符串转为 Market 枚举，支持大小写，非法值抛 ValueError。

    >>> market_from_str("SZ")  # 正常
    >>> market_from_str("sz")  # 也正常（自动转大写）
    >>> market_from_str("ZZZ")  # ValueError
    """
    from easy_tdx.models.enums import Market

    key = s.upper()
    try:
        return Market[MarketEnum[key].name]
    except KeyError:
        valid = ", ".join(m.name for m in MarketEnum)
        raise ValueError(f"无效市场代码 '{s}'，可选值: {valid}") from None


def category_from_str(s: str) -> Any:
    """将字符串转为 KlineCategory 枚举，支持大小写和数字字符串。"""
    from easy_tdx.models.enums import KlineCategory

    key = s.upper()
    # 支持纯数字（如 "4" 表示日线）
    try:
        return KlineCategory(int(key))
    except (ValueError, TypeError):
        pass
    try:
        return KlineCategory[KlineCategoryEnum[key].name]
    except KeyError:
        valid = ", ".join(c.name for c in KlineCategoryEnum)
        raise ValueError(f"无效K线周期 '{s}'，可选值: {valid}") from None
