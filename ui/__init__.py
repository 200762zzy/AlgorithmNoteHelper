"""PySide6 界面层。

分层硬约束（见项目文档 3.1）：只有本包与 `main.py` 允许 import Qt；
业务层与持久化层保持纯 Python，可以直接用 pytest 测试。所以本包只做
「把 Library 的数据搬上屏幕、把用户的动作翻译成 Library 调用」。
"""
