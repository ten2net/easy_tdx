"""离线自定义板块读写单元测试。"""

from pathlib import Path

import pytest

from easy_tdx.exceptions import TdxOfflineError
from easy_tdx.offline import read_customer_blocks, write_customer_block


def _make_blocknew_dir(tmp_path: Path) -> Path:
    """构造一个最小可用的 blocknew 目录。"""
    block_dir = tmp_path / "blocknew"
    block_dir.mkdir()
    (block_dir / "blocknew.cfg").write_bytes(b"")
    return block_dir


def _cfg_entries(block_dir: Path) -> list[tuple[str, str]]:
    """读取 blocknew.cfg 中的索引记录。"""
    data = (block_dir / "blocknew.cfg").read_bytes()
    entries = []
    pos = 0
    while pos + 120 <= len(data):
        name = data[pos : pos + 50].split(b"\x00")[0].decode("gbk", errors="replace")
        filename = data[pos + 50 : pos + 120].split(b"\x00")[0].decode("gbk", errors="replace")
        entries.append((name, filename))
        pos += 120
    return entries


def test_write_customer_block_new(tmp_path: Path) -> None:
    """写入一个全新的自定义板块。"""
    block_dir = _make_blocknew_dir(tmp_path)

    filename, count = write_customer_block(
        block_dir,
        "强势股",
        [("SH", "600000"), ("SZ", "000001")],
        backup=False,
    )

    assert count == 2
    assert filename == "block_1"
    assert _cfg_entries(block_dir) == [("强势股", "block_1")]

    blk_text = (block_dir / f"{filename}.blk").read_text(encoding="utf-8")
    assert blk_text == "1600000\n0000001\n"


def test_write_customer_block_overwrite(tmp_path: Path) -> None:
    """覆盖已有板块内容。"""
    block_dir = _make_blocknew_dir(tmp_path)

    write_customer_block(
        block_dir,
        "test",
        [("SH", "600000"), ("SZ", "000001")],
        backup=False,
    )

    filename, count = write_customer_block(
        block_dir,
        "test",
        [("SH", "600001")],
        mode="overwrite",
        backup=False,
    )

    assert count == 1
    assert _cfg_entries(block_dir) == [("test", filename)]
    assert (block_dir / f"{filename}.blk").read_text(encoding="utf-8") == "1600001\n"


def test_write_customer_block_append(tmp_path: Path) -> None:
    """追加到已有板块并去重。"""
    block_dir = _make_blocknew_dir(tmp_path)

    write_customer_block(
        block_dir,
        "test",
        [("SH", "600000"), ("SZ", "000001")],
        backup=False,
    )

    filename, count = write_customer_block(
        block_dir,
        "test",
        [("SZ", "000001"), ("SH", "600002")],
        mode="append",
        backup=False,
    )

    assert count == 3
    blk_text = (block_dir / f"{filename}.blk").read_text(encoding="utf-8")
    assert blk_text == "1600000\n0000001\n1600002\n"


def test_write_customer_block_ascii_name(tmp_path: Path) -> None:
    """英文板块名可直接用作 blk 文件名。"""
    block_dir = _make_blocknew_dir(tmp_path)

    filename, _ = write_customer_block(
        block_dir,
        "StrongStocks",
        [("SH", "600000")],
        backup=False,
    )

    assert filename == "strongstocks"
    assert _cfg_entries(block_dir) == [("StrongStocks", "strongstocks")]


def test_write_customer_block_invalid_name(tmp_path: Path) -> None:
    """非法板块名称应抛出 ValueError。"""
    block_dir = _make_blocknew_dir(tmp_path)

    with pytest.raises(ValueError, match="非法字符"):
        write_customer_block(block_dir, "a/b", [("SH", "600000")], backup=False)

    with pytest.raises(ValueError, match="不能为空"):
        write_customer_block(block_dir, "   ", [("SH", "600000")], backup=False)


def test_write_customer_block_bad_market(tmp_path: Path) -> None:
    """不支持的市场应抛出 ValueError。"""
    block_dir = _make_blocknew_dir(tmp_path)

    with pytest.raises(ValueError, match="不支持的市场"):
        write_customer_block(block_dir, "test", [("HK", "00700")], backup=False)


def test_write_customer_block_bad_code(tmp_path: Path) -> None:
    """非法代码格式应抛出 ValueError。"""
    block_dir = _make_blocknew_dir(tmp_path)

    with pytest.raises(ValueError, match="代码格式错误"):
        write_customer_block(block_dir, "test", [("SH", "60000")], backup=False)


def test_read_customer_blocks_roundtrip(tmp_path: Path) -> None:
    """写入后通过 read_customer_blocks 能正确读回。"""
    block_dir = _make_blocknew_dir(tmp_path)

    write_customer_block(
        block_dir,
        "roundtrip",
        [("SH", "600000"), ("SZ", "000001"), ("SZ", "000002")],
        backup=False,
    )

    blocks = read_customer_blocks(block_dir)
    assert len(blocks) == 1
    assert blocks[0].blockname == "roundtrip"
    assert blocks[0].codes == ["600000", "000001", "000002"]


def test_write_customer_block_missing_dir(tmp_path: Path) -> None:
    """目录不存在时抛出 TdxOfflineError。"""
    with pytest.raises(TdxOfflineError, match="自定义板块目录不存在"):
        write_customer_block(tmp_path / "not_exist", "test", [("SH", "600000")])


def test_read_customer_block_codes(tmp_path: Path) -> None:
    """按名称读取单个板块的代码列表。"""
    from easy_tdx.offline import read_customer_block_codes

    block_dir = _make_blocknew_dir(tmp_path)
    write_customer_block(
        block_dir,
        "test_block",
        [("SH", "600000"), ("SZ", "000001")],
        backup=False,
    )

    codes = read_customer_block_codes(block_dir, "test_block")
    assert set(codes) == {("SH", "600000"), ("SZ", "000001")}


def test_read_customer_block_codes_missing(tmp_path: Path) -> None:
    """板块不存在时抛出 TdxOfflineError。"""
    from easy_tdx.offline import read_customer_block_codes

    block_dir = _make_blocknew_dir(tmp_path)
    with pytest.raises(TdxOfflineError, match="未找到板块"):
        read_customer_block_codes(block_dir, "不存在")
