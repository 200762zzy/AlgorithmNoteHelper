"""开发用：离屏渲染主窗口并截图（见项目文档 3.5 的精修环节）。

不弹窗、不占用桌面，直接在离屏平台上按不同窗宽各截一张，便于检查
「层级是否清楚」「窄窗会不会塌」。

用法：
    python tools/shoot.py                # 输出到仓库下的 .shots/
    python tools/shoot.py --out D:\\shots
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

# 必须在 import PySide6 之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 离屏平台自带的 basic 字体库不带字体，需要显式指向系统字体目录，
# 否则整屏中文会渲染成方框，截图就失去意义。
os.environ.setdefault(
    "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

import paths  # noqa: E402
from models import Difficulty, ErrorCategory, Note  # noqa: E402
from services import Library  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.code_dialog import CodeDialog  # noqa: E402
from ui.schedule_dialog import ScheduleDialog  # noqa: E402
from ui.theme import apply_theme  # noqa: E402

SIZES = ((1200, 800), (900, 680), (1360, 900))

FIXED_DAY = date(2026, 10, 13)


def seed(library: Library, day: date):
    """造一批有代表性的样例数据：已掌握 / 待复习 / 只填了标题各一种。

    返回第一条（它带完整的 AC 代码），供截图工具展示代码高亮。
    """
    prefix = library.create(
        "P1001 前缀和与差分",
        link="https://oj.example.com/p/1001",
        tags=["前缀和", "差分"],
        difficulty=Difficulty.HARD,
        error_category=ErrorCategory.BOUNDARY,
        note=Note(
            wrong_idea="把差分数组开成了 n，忘了差分要多一位。",
            wrong_code=(
                "int d[N];\n"
                "for (int i = 1; i <= n; ++i) {\n"
                "    d[i] += d[i - 1];   // 越界\n"
                "}"
            ),
            cause_detail="边界错误 —— 数组开到 n 而非 n+1",
            correct_idea="差分数组开到 n+2，下标从 1 开始，区间修改只动两个端点。",
            ac_code=(
                "#include <bits/stdc++.h>\n"
                "using namespace std;\n"
                "\n"
                "int main() {\n"
                "    int n, m;\n"
                "    cin >> n >> m;\n"
                "    vector<long long> d(n + 2);\n"
                "    while (m--) {\n"
                "        int l, r, v;\n"
                "        cin >> l >> r >> v;\n"
                "        d[l] += v;\n"
                "        d[r + 1] -= v;\n"
                "    }\n"
                "    long long cur = 0;\n"
                "    for (int i = 1; i <= n; ++i) {\n"
                "        cur += d[i];\n"
                "        cout << cur << ' ';\n"
                "    }\n"
                "    return 0;\n"
                "}"
            ),
            summary="区间修改一律多开一位；下标从 1 开始能省掉一堆特判。",
        ),
    )
    for _ in range(4):
        library.review(prefix.id, 5, day)

    greedy = library.create(
        "P2251 区间选点",
        tags=["贪心"],
        difficulty=Difficulty.MEDIUM,
        error_category=ErrorCategory.NO_IDEA,
        note=Note(
            wrong_idea="想按左端点排序，样例都过不了。",
            cause_detail="思路不会 —— 按右端点排序才是对的",
            correct_idea="按右端点升序，能放就放。",
            summary="区间贪心先想右端点。",
        ),
    )
    library.review(greedy.id, 3, day)

    library.create(
        "P1048 采药",
        tags=["DP", "背包"],
        difficulty=Difficulty.MEDIUM,
        error_category=ErrorCategory.OVERFLOW,
        note=Note(
            wrong_idea="价值累加用了 int，n=100 时就溢出了。",
            cause_detail="溢出 —— 累加变量开小了",
            summary="算总和一律 long long。",
        ),
    )
    library.create(
        "P1223 排队接水",
        tags=["贪心", "排序"],
        difficulty=Difficulty.EASY,
        error_category=ErrorCategory.SYNTAX_BUG,
    )
    library.create("快速新建的一条（只填了标题）")
    return prefix


def main() -> int:
    parser = argparse.ArgumentParser(description="离屏渲染主窗口并截图")
    parser.add_argument("--out", default=str(ROOT / ".shots"), help="截图输出目录")
    parser.add_argument("--seed", action="store_true", help="（默认即造样例数据）")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    apply_theme(app)

    data_dir = Path(tempfile.mkdtemp(prefix="anh-shot-")) / "data"
    library = Library(paths.ensure_layout(data_dir), today_fn=lambda: FIXED_DAY)
    entry = seed(library, FIXED_DAY)

    window = MainWindow(library)
    window.show()
    app.processEvents()

    saved: list[Path] = []
    for width, height in SIZES:
        window.resize(width, height)
        app.processEvents()
        target = out_dir / f"main-{width}x{height}.png"
        window.grab().save(str(target))
        saved.append(target)
        print(f"saved {target}")

    # 复习计划视图（到期分布 + 分组清单）
    dialog = ScheduleDialog(library, day=FIXED_DAY, parent=window)
    dialog.resize(880, 640)
    dialog.show()
    app.processEvents()
    target = out_dir / "schedule.png"
    dialog.grab().save(str(target))
    saved.append(target)
    print(f"saved {target}")
    dialog.close()

    # 代码「放大」对话框（同时检验大窗口里的语法高亮）
    code_dialog = CodeDialog(library.read_note(entry.id).ac_code, "AC 代码（C++）", parent=window)
    code_dialog.resize(1000, 700)
    code_dialog.show()
    app.processEvents()
    target = out_dir / "code-dialog.png"
    code_dialog.grab().save(str(target))
    saved.append(target)
    print(f"saved {target}")
    code_dialog.close()

    print(f"数据目录（临时）：{data_dir}")
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
