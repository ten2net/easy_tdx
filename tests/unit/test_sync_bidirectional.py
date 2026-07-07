"""sync-all --peer 双向本地同步测试（纯离线，无网络）。"""

from __future__ import annotations

from pathlib import Path

from easy_tdx.models.bar import SecurityBar
from easy_tdx.offline.daily_bar import read_daily_bars
from easy_tdx.offline.write_daily import (
    encode_daily_bar,
    merge_daily_bars,
    sync_bidirectional_daily,
    write_daily_bars,
)


def _make_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    open_: float = 10.25,
    high: float = 10.50,
    low: float = 10.10,
    close: float = 10.30,
    vol: float = 100000.0,
    amount: float = 1025000.0,
) -> SecurityBar:
    return SecurityBar(
        open=open_,
        close=close,
        high=high,
        low=low,
        vol=vol,
        amount=amount,
        year=year,
        month=month,
        day=day,
        hour=0,
        minute=0,
    )


def _write_day_file(filepath: Path, bars: list[SecurityBar]) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    encoded = b"".join(encode_daily_bar(b, price_coeff=0.01, vol_coeff=100.0) for b in bars)
    filepath.write_bytes(encoded)


# ---------------------------------------------------------------------------
# merge_daily_bars
# ---------------------------------------------------------------------------


class TestMergeDailyBars:
    def test_disjoint_lists_are_combined(self) -> None:
        left = [_make_bar(year=2026, month=6, day=4), _make_bar(year=2026, month=6, day=6)]
        right = [_make_bar(year=2026, month=6, day=5), _make_bar(year=2026, month=6, day=7)]
        merged = merge_daily_bars(left, right)
        assert [b.day for b in merged] == [4, 5, 6, 7]

    def test_overlap_prefer_left(self) -> None:
        left = [_make_bar(year=2026, month=6, day=5, close=10.0)]
        right = [_make_bar(year=2026, month=6, day=5, close=20.0)]
        merged = merge_daily_bars(left, right, prefer="left")
        assert merged[0].close == 10.0

    def test_overlap_prefer_right(self) -> None:
        left = [_make_bar(year=2026, month=6, day=5, close=10.0)]
        right = [_make_bar(year=2026, month=6, day=5, close=20.0)]
        merged = merge_daily_bars(left, right, prefer="right")
        assert merged[0].close == 20.0

    def test_both_keeps_left_for_overlap(self) -> None:
        left = [_make_bar(year=2026, month=6, day=5, close=10.0)]
        right = [_make_bar(year=2026, month=6, day=5, close=20.0)]
        merged = merge_daily_bars(left, right, prefer="both")
        assert merged[0].close == 10.0


# ---------------------------------------------------------------------------
# write_daily_bars
# ---------------------------------------------------------------------------


class TestWriteDailyBars:
    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        _write_day_file(filepath, [_make_bar(year=2026, month=6, day=5)])

        write_daily_bars(
            filepath, [_make_bar(year=2026, month=6, day=6)], price_coeff=0.01, vol_coeff=100.0
        )

        bars = read_daily_bars(filepath)
        assert len(bars) == 1
        assert bars[0].day == 6

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh" / "lday" / "sh600000.day"
        write_daily_bars(filepath, [_make_bar()], price_coeff=0.01, vol_coeff=100.0)
        assert filepath.is_file()

    def test_empty_bars_clears_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        _write_day_file(filepath, [_make_bar()])
        write_daily_bars(filepath, [], price_coeff=0.01, vol_coeff=100.0)
        assert filepath.read_bytes() == b""


# ---------------------------------------------------------------------------
# sync_bidirectional_daily
# ---------------------------------------------------------------------------


class TestSyncBidirectionalDaily:
    def test_copies_missing_records_to_dst(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        _write_day_file(src_file, [_make_bar(year=2026, month=6, day=5)])
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_bytes(b"")  # empty file

        stats = sync_bidirectional_daily(src_file, dst_file)

        assert stats["src_to_dst_added"] == 1
        assert stats["dst_to_src_added"] == 0
        src_bars = read_daily_bars(src_file)
        dst_bars = read_daily_bars(dst_file)
        assert len(src_bars) == len(dst_bars) == 1

    def test_copies_missing_records_to_src(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_bytes(b"")  # empty file
        _write_day_file(dst_file, [_make_bar(year=2026, month=6, day=5)])

        stats = sync_bidirectional_daily(src_file, dst_file)

        assert stats["src_to_dst_added"] == 0
        assert stats["dst_to_src_added"] == 1
        src_bars = read_daily_bars(src_file)
        dst_bars = read_daily_bars(dst_file)
        assert len(src_bars) == len(dst_bars) == 1

    def test_merges_gaps_both_directions(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        _write_day_file(src_file, [_make_bar(day=4), _make_bar(day=6)])
        _write_day_file(dst_file, [_make_bar(day=5), _make_bar(day=7)])

        stats = sync_bidirectional_daily(src_file, dst_file)

        assert stats["src_to_dst_added"] == 2  # 5, 7
        assert stats["dst_to_src_added"] == 2  # 4, 6
        assert stats["conflicts"] == 0
        src_bars = read_daily_bars(src_file)
        dst_bars = read_daily_bars(dst_file)
        assert [b.day for b in src_bars] == [4, 5, 6, 7]
        assert [b.day for b in dst_bars] == [4, 5, 6, 7]

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        _write_day_file(src_file, [_make_bar(day=5)])
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_bytes(b"")

        stats = sync_bidirectional_daily(src_file, dst_file, dry_run=True)

        assert stats["src_to_dst_added"] == 1
        assert dst_file.read_bytes() == b""

    def test_prefer_newer_uses_dst_when_dst_is_newer(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        _write_day_file(src_file, [_make_bar(day=5, close=10.0)])
        _write_day_file(dst_file, [_make_bar(day=5, close=20.0), _make_bar(day=6, close=20.0)])

        stats = sync_bidirectional_daily(src_file, dst_file, prefer="newer")

        # dst 更新，冲突日期应保留 dst 的 close=20.0
        src_bars = read_daily_bars(src_file)
        assert stats["conflicts"] == 1
        assert src_bars[0].close == 20.0

    def test_prefer_src_keeps_src_on_conflict(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        _write_day_file(src_file, [_make_bar(day=5, close=10.0)])
        _write_day_file(dst_file, [_make_bar(day=5, close=20.0)])

        sync_bidirectional_daily(src_file, dst_file, prefer="src")

        src_bars = read_daily_bars(src_file)
        assert src_bars[0].close == 10.0

    def test_prefer_dst_keeps_dst_on_conflict(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        _write_day_file(src_file, [_make_bar(day=5, close=10.0)])
        _write_day_file(dst_file, [_make_bar(day=5, close=20.0)])

        sync_bidirectional_daily(src_file, dst_file, prefer="dst")

        src_bars = read_daily_bars(src_file)
        assert src_bars[0].close == 20.0

    def test_identical_files_are_not_rewritten(self, tmp_path: Path) -> None:
        src_file = tmp_path / "src" / "sh" / "lday" / "sh600000.day"
        dst_file = tmp_path / "dst" / "sh" / "lday" / "sh600000.day"
        bars = [_make_bar(day=5), _make_bar(day=6)]
        _write_day_file(src_file, bars)
        _write_day_file(dst_file, bars)

        src_mtime_before = src_file.stat().st_mtime
        dst_mtime_before = dst_file.stat().st_mtime

        sync_bidirectional_daily(src_file, dst_file)

        assert src_file.stat().st_mtime == src_mtime_before
        assert dst_file.stat().st_mtime == dst_mtime_before
