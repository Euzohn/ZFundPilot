"""config 模块原子写入测试。"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

from zfundpilot.config import _atomic_write


class TestAtomicWrite:
    def test_writes_file(self, tmp_path):
        path = str(tmp_path / "test.json")
        _atomic_write(path, b'{"key": "value"}')
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"key": "value"}

    def test_replaces_existing_file(self, tmp_path):
        path = str(tmp_path / "test.json")
        with open(path, "w") as f:
            f.write("old")
        _atomic_write(path, b"new")
        assert open(path, encoding="utf-8").read() == "new"

    def test_no_tmp_residue_on_success(self, tmp_path):
        path = str(tmp_path / "test.json")
        _atomic_write(path, b"data")
        files = os.listdir(tmp_path)
        assert len(files) == 1  # only test.json, no .tmp

    def test_no_residue_on_failure(self, tmp_path):
        path = str(tmp_path / "test.json")
        with patch("zfundpilot.config.os.replace", side_effect=OSError("disk full")):
            try:
                _atomic_write(path, b"data")
            except OSError:
                pass
        files = os.listdir(tmp_path)
        assert len(files) == 0
        assert not os.path.exists(path)
