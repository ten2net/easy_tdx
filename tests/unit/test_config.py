"""config.py 单元测试 —— 覆盖环境变量覆盖、config.json 原子读写、save_best_host 补全逻辑。

之前这三块（env 覆盖 / config.json 读写 / save_best_host 合并）零测试，
本文件补齐该缺口（审计报告 #9）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from easy_tdx import config as cfg

# --------------------------------------------------------------------------- #
# 辅助：把 config 模块的 _CONFIG_FILE / _CONFIG_DIR 重定向到临时目录
# --------------------------------------------------------------------------- #


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 config 模块的重定向到 tmp_path，测试间互不影响。"""
    monkeypatch.setattr(cfg, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "_CONFIG_FILE", tmp_path / "config.json")
    return tmp_path


# --------------------------------------------------------------------------- #
# 环境变量覆盖（EASY_TDX_HOST / PORT / TIMEOUT）
# --------------------------------------------------------------------------- #


class TestEnvOverride:
    def test_env_host_overrides_config(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # config.json 写入一个 host，但 env 应优先
        (isolated_config / "config.json").write_text(json.dumps({"best_host": "1.1.1.1"}), "utf-8")
        monkeypatch.setenv("EASY_TDX_HOST", "9.9.9.9")
        assert cfg.get_best_host() == "9.9.9.9"

    def test_env_port_overrides_config(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EASY_TDX_PORT", "8888")
        assert cfg.get_port() == 8888

    def test_env_timeout_overrides_config(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EASY_TDX_TIMEOUT", "42.5")
        assert cfg.get_timeout() == 42.5

    def test_env_known_hosts_csv(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EASY_TDX_KNOWN_HOSTS", "a.com, b.com ,,c.com")
        assert cfg.get_known_hosts() == ["a.com", "b.com", "c.com"]


# --------------------------------------------------------------------------- #
# config.json 读写 + 默认兜底
# --------------------------------------------------------------------------- #


class TestConfigReadWrite:
    def test_no_config_file_uses_fallback(self, isolated_config: Path) -> None:
        # 无 config.json 时返回内嵌默认值
        assert cfg.get_best_host() == cfg._FALLBACK_HOSTS[0]
        assert cfg.get_port() == cfg._FALLBACK_PORT
        assert cfg.get_known_hosts() == list(cfg._FALLBACK_HOSTS)

    def test_config_json_host(self, isolated_config: Path) -> None:
        (isolated_config / "config.json").write_text(
            json.dumps({"best_host": "203.0.0.1", "port": 7709, "timeout": 12.0}),
            "utf-8",
        )
        assert cfg.get_best_host() == "203.0.0.1"
        assert cfg.get_port() == 7709
        assert cfg.get_timeout() == 12.0

    def test_load_corrupt_json_returns_empty(self, isolated_config: Path) -> None:
        # 损坏的 JSON 不应崩溃，应回退到默认
        (isolated_config / "config.json").write_text("{not valid json", "utf-8")
        assert cfg.get_best_host() == cfg._FALLBACK_HOSTS[0]


# --------------------------------------------------------------------------- #
# save_best_host 首次写入补全逻辑
# --------------------------------------------------------------------------- #


class TestSaveBestHost:
    def test_first_write_completes_defaults(self, isolated_config: Path) -> None:
        cfg.save_best_host("180.153.18.170")
        data = json.loads((isolated_config / "config.json").read_text("utf-8"))
        assert data["best_host"] == "180.153.18.170"
        # 首次写入应补全所有默认字段
        assert data["known_hosts"] == list(cfg._FALLBACK_HOSTS)
        assert data["calc_hosts"] == list(cfg._FALLBACK_CALC_HOSTS)
        assert data["mac_hosts"] == list(cfg._FALLBACK_MAC_HOSTS)
        assert data["ex_hosts"] == list(cfg._FALLBACK_EX_HOSTS)
        assert data["mac_ex_hosts"] == list(cfg._FALLBACK_MAC_EX_HOSTS)
        assert data["port"] == cfg._FALLBACK_PORT
        assert "best_host_updated_at" in data

    def test_second_write_preserves_existing(self, isolated_config: Path) -> None:
        # 预置已存在的 known_hosts，save_best_host 不应覆盖它
        existing = {
            "known_hosts": ["custom.host"],
            "port": 9999,
        }
        (isolated_config / "config.json").write_text(json.dumps(existing), "utf-8")
        cfg.save_best_host("new.host")
        data = json.loads((isolated_config / "config.json").read_text("utf-8"))
        assert data["best_host"] == "new.host"
        # 已有字段应保留，不被默认值覆盖
        assert data["known_hosts"] == ["custom.host"]
        assert data["port"] == 9999
        # 但缺失的字段应补全
        assert "calc_hosts" in data

    def test_atomic_write(self, isolated_config: Path) -> None:
        # 写入后不应残留 .tmp 文件（原子替换）
        cfg.save_best_host("x.host")
        assert not (isolated_config / "config.json.tmp").exists()
        assert (isolated_config / "config.json").exists()
