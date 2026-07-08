"""板块数据读取与写入（.dat 文件和自定义板块目录）。"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..codec.block import parse_block_dat
from ..exceptions import TdxFileNotFoundError, TdxOfflineError
from ..models.finance import TdxBlock

# 市场标识 → .blk 文件首位字符
_DEFAULT_MARKER_MAP: dict[str, str] = {
    "SZ": "0",
    "SH": "1",
    "BJ": "2",  # 部分新版本通达信对北交所使用 2
}

# 危险字符：防止路径穿越或破坏 cfg/blk 格式
_UNSAFE_BLOCK_NAME = re.compile(r"[\\/:*?\"<>|\.\x00-\x1f]")


@dataclass
class CustomerBlock:
    """自定义板块。"""

    blockname: str
    block_type: str
    codes: list[str] = field(default_factory=list)


def read_block_dat(filepath: str | Path) -> list[TdxBlock]:
    """从本地 .dat 板块文件读取板块数据。

    直接复用 codec/block.py 的 parse_block_dat()。

    Args:
        filepath: .dat 文件路径（如 block_zs.dat）。

    Returns:
        TdxBlock 列表。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"板块数据文件不存在: {filepath}")
    data = filepath.read_bytes()
    return parse_block_dat(data, filename=filepath.name)


def _read_cfg_entries(block_dir: Path) -> list[tuple[str, str]]:
    """读取 blocknew.cfg，返回 [(板块名, blk 文件名)] 列表。"""
    cfg_path = block_dir / "blocknew.cfg"
    if not cfg_path.is_file():
        return []

    cfg_data = cfg_path.read_bytes()
    entries: list[tuple[str, str]] = []
    pos = 0
    while pos + 120 <= len(cfg_data):
        name = cfg_data[pos : pos + 50].split(b"\x00")[0].decode("gbk", errors="replace")
        blk_filename = (
            cfg_data[pos + 50 : pos + 120].split(b"\x00")[0].decode("gbk", errors="replace")
        )
        pos += 120
        if name:
            entries.append((name, blk_filename))
    return entries


def _write_cfg_entries(block_dir: Path, entries: list[tuple[str, str]]) -> None:
    """把板块索引写回 blocknew.cfg（每条 120 字节：50B 名称 + 70B 文件名）。"""
    cfg_path = block_dir / "blocknew.cfg"
    buf = bytearray()
    for name, blk_filename in entries:
        name_b = name.encode("gbk", errors="ignore")[:49].ljust(50, b"\x00")
        file_b = blk_filename.encode("gbk", errors="ignore")[:69].ljust(70, b"\x00")
        buf.extend(name_b)
        buf.extend(file_b)
    cfg_path.write_bytes(bytes(buf))


def _sanitize_block_name(name: str) -> str:
    """校验板块名称，拒绝非法字符与空名称。"""
    if not name or not name.strip():
        raise ValueError("板块名称不能为空")
    name = name.strip()
    if _UNSAFE_BLOCK_NAME.search(name):
        raise ValueError(f"板块名称包含非法字符: {name}")
    return name


def _generate_blk_filename(block_dir: Path, block_name: str) -> str:
    """为新板块生成一个合法的 blk 文件名。

    若 block_name 可全部编码为 ascii，则直接使用；否则使用 block_{序号}。
    """
    ascii_name = block_name.encode("ascii", "ignore").decode()
    if ascii_name and ascii_name.isalnum():
        candidate = ascii_name.lower()[:60]
        if not (block_dir / f"{candidate}.blk").exists():
            return candidate

    idx = 1
    while True:
        candidate = f"block_{idx}"
        if not (block_dir / f"{candidate}.blk").exists():
            return candidate
        idx += 1


def _market_to_marker(market: str, marker_map: dict[str, str] | None) -> str:
    """把市场字符串转换为 .blk 行首的市场标识字符。"""
    mapping = marker_map or _DEFAULT_MARKER_MAP
    key = market.upper()
    if key not in mapping:
        raise ValueError(f"不支持的市场 '{market}'，可用: {list(mapping.keys())}")
    return mapping[key]


def read_customer_blocks(block_dir: str | Path) -> list[CustomerBlock]:
    """从通达信自定义板块目录读取板块数据。

    目录结构：
      blocknew.cfg  — 板块索引（120 字节/条：50B 名称 + 70B 文件名）
      *.blk         — 板块内容（每行一个代码，首位为市场标识）

    Args:
        block_dir: 自定义板块目录路径。

    Returns:
        CustomerBlock 列表。
    """
    block_dir = Path(block_dir)
    if not block_dir.is_dir():
        raise TdxOfflineError(f"自定义板块目录不存在: {block_dir}")

    entries = _read_cfg_entries(block_dir)
    results: list[CustomerBlock] = []

    for name, blk_filename in entries:
        if not blk_filename:
            continue
        blk_path = block_dir / f"{blk_filename}.blk"
        if not blk_path.is_file():
            continue

        codes: list[str] = []
        for line in blk_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and len(line) > 1:
                codes.append(line[1:])  # 去掉首位的市场标识

        results.append(
            CustomerBlock(
                blockname=name,
                block_type=blk_filename,
                codes=codes,
            )
        )

    return results


def write_customer_block(
    block_dir: str | Path,
    block_name: str,
    codes: Iterable[tuple[str, str]],
    *,
    mode: str = "overwrite",
    marker_map: dict[str, str] | None = None,
    backup: bool = True,
) -> tuple[str, int]:
    """把股票列表写入/追加到通达信自定义板块。

    若 blocknew.cfg 中已存在同名板块，则更新其 .blk 文件；否则新建 .blk
    并在 blocknew.cfg 末尾注册该板块。操作前会自动备份 blocknew.cfg 与
    目标 .blk 文件（backup=True 时）。

    Args:
        block_dir: 通达信自定义板块目录路径（如 C:\\new_jyplug\\T0002\\blocknew）。
        block_name: 板块显示名称（如 "强势股"）。
        codes: 股票列表，每个元素为 (market, code)，market 支持 SZ/SH/BJ。
        mode: "overwrite" 覆盖写入（默认）或 "append" 追加。
        marker_map: 自定义市场到 .blk 首位标识的映射，默认 SZ=0, SH=1, BJ=2。
        backup: 是否先备份 blocknew.cfg 与目标 .blk 文件。

    Returns:
        (blk_filename, 写入后板块内股票数量)

    Raises:
        TdxOfflineError: 目录不存在或写入失败。
        ValueError: 板块名称非法或包含不支持的市场。
    """
    block_dir = Path(block_dir)
    if not block_dir.is_dir():
        raise TdxOfflineError(f"自定义板块目录不存在: {block_dir}")

    block_name = _sanitize_block_name(block_name)
    cfg_path = block_dir / "blocknew.cfg"

    # 读取当前索引
    entries = _read_cfg_entries(block_dir)

    # 查找是否已存在
    blk_filename: str | None = None
    for name, filename in entries:
        if name == block_name:
            blk_filename = filename
            break

    if not blk_filename:
        blk_filename = _generate_blk_filename(block_dir, block_name)
        entries.append((block_name, blk_filename))

    blk_path = block_dir / f"{blk_filename}.blk"

    # 备份原文件
    if backup:
        if cfg_path.is_file():
            shutil.copy2(cfg_path, cfg_path.with_suffix(".cfg.bak"))
        if blk_path.is_file():
            shutil.copy2(blk_path, blk_path.with_suffix(".blk.bak"))

    # 构造 .blk 行
    new_lines: list[str] = []
    for market, code in codes:
        marker = _market_to_marker(market, marker_map)
        # code 只保留 6 位数字/字母，防止注入
        code_clean = re.sub(r"[^0-9a-zA-Z]", "", code)
        if len(code_clean) != 6:
            raise ValueError(f"代码格式错误，应为 6 位: {code}")
        new_lines.append(f"{marker}{code_clean}")

    # 合并已有内容（append 模式）
    if mode == "append" and blk_path.is_file():
        existing = [
            line.strip()
            for line in blk_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        # 去重并保持顺序：新内容追加到末尾
        seen = set(existing)
        for line in new_lines:
            if line not in seen:
                existing.append(line)
                seen.add(line)
        final_lines = existing
    else:
        final_lines = new_lines

    # 写入 .blk
    try:
        blk_path.write_text("\n".join(final_lines) + "\n", encoding="utf-8")
    except OSError as e:
        raise TdxOfflineError(f"写入板块文件失败: {blk_path}, {e}") from e

    # 更新 blocknew.cfg（新板块需要注册）
    try:
        _write_cfg_entries(block_dir, entries)
    except OSError as e:
        raise TdxOfflineError(f"写入板块索引失败: {cfg_path}, {e}") from e

    return blk_filename, len(final_lines)
