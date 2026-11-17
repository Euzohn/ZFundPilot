"""配置导入时的跨平台时区初始化测试。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("tzset_mode", ["present", "absent"])
def test_config_import_initializes_timezone(tmp_path, tzset_mode):
    # 在子进程中模拟两种平台能力，隔离 config 导入对 TZ 的影响。
    script = """
import os
import sys
import time

calls = []
has_tzset = sys.argv[1] == "present"
if has_tzset:
    time.tzset = lambda: calls.append(os.environ["TZ"])
elif hasattr(time, "tzset"):
    del time.tzset

from zfundpilot import config

assert config.TIMEZONE_STR == "America/New_York"
assert config.TIMEZONE.key == "America/New_York"
assert calls == (["America/New_York"] if has_tzset else [])
assert os.environ["TZ"] == ("America/New_York" if has_tzset else "UTC")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, tzset_mode],
        cwd=Path(__file__).resolve().parents[1] / "src",
        env={
            **os.environ,
            "TZ": "UTC",
            "ZFUNDPILOT_HOME": str(tmp_path),
            "ZFUNDPILOT_TIMEZONE": "America/New_York",
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
