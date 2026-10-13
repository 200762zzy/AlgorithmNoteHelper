"""共享 fixture。

两点说明：

1. 数据层与业务层刻意不依赖 Qt，所以这些测试不需要 GUI 环境。
2. 这里**自己实现 `tmp_path`**，不使用 pytest 内置的：内置实现会在 basetemp 里做
   目录重命名与「整目录删除」，在受限环境下会失败并留下无法删除的残留目录。
   自建实现只做「创建唯一目录」，从不重命名、从不删除目录，因此既不需要清理，
   也不会与上一次运行互相干扰。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest

# 保证可以直接 import 项目根目录下的模块（pytest.ini 的 pythonpath 之外的保险）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paths  # noqa: E402
from services import Library  # noqa: E402

# 固定日期，避免测试结果随真实日期/时区变化（见文档 3.2 的时间基准约束）
FIXED_DAY = date(2026, 10, 13)

# 每次运行一个独立命名空间，保证目录永远是全新的
_RUN_TOKEN = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    """给每条用例一个全新的空目录（只创建，不重命名，不删除）。"""
    slug = re.sub(r"[^0-9A-Za-z_.\-]+", "-", request.node.name).strip("-") or "test"
    digest = uuid.uuid5(uuid.NAMESPACE_OID, request.node.nodeid).hex[:10]
    target = (
        Path(tempfile.gettempdir()) / "anh-tests" / _RUN_TOKEN / f"{slug[:60]}-{digest}"
    )
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture
def day() -> date:
    return FIXED_DAY


@pytest.fixture
def layout(tmp_path: Path) -> paths.DataLayout:
    return paths.ensure_layout(tmp_path / "data")


@pytest.fixture
def library(layout: paths.DataLayout, day: date) -> Library:
    return Library(layout, today_fn=lambda: day)
