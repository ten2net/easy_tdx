"""捉妖大师多周期共振策略。

基于 ZHUOYAO 指标（20/60/120 日涨幅及指数平滑），通过短中长线趋势共振判断买卖时机。

入场条件（三条件全部满足）：
  1. SHORT > 0  — 20 日涨幅为正，短线处于强势
  2. TREND > 0  — 60 日涨幅的 EMA 为正，中期趋势向上
  3. SHORT > MID — 短线强于中线，处于加速阶段（非衰竭）

出场条件（任一触发即卖出）：
  1. SHORT < 0  — 短线转弱
  2. TREND < 0  — 中期趋势转向

适合单边趋势行情，震荡市信号较少（这是过滤噪音的设计）。

用法::

    easy-tdx backtest SZ 000001 --strategy-file strategies/zhuoyao_momentum.py --count 2000 --table
"""

from easy_tdx import MyTT
from easy_tdx.backtest import Strategy


class ZhuoyaoStrategy(Strategy):
    """捉妖大师多周期共振策略。"""

    def init(self) -> None:
        # ZHUOYAO 返回 4 个数组: LONG, MID, SHORT, TREND
        self.long, self.mid, self.short, self.trend = self.I(
            MyTT.ZHUOYAO, self.data.close,
        )

    def next(self) -> None:
        short = float(self.short[self._bar_index])
        mid = float(self.mid[self._bar_index])
        trend = float(self.trend[self._bar_index])

        # 入场：短线强势 + 中期趋势向上 + 短线加速（短>中）
        if short > 0 and trend > 0 and short > mid:
            if self.position["size"] == 0:
                self.buy(size=0)

        # 出场：短线转弱 或 中期趋势转向（任一即卖，保守预警）
        elif short < 0 or trend < 0:
            if self.position["size"] > 0:
                self.sell(size=0)
