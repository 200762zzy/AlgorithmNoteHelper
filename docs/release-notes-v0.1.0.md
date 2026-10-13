# AlgorithmNoteHelper v0.1.0

面向蓝桥杯 C/C++ 刷题的**本地**错题管理工具。首个可分发版本。

纯本地运行：不联网、不装数据库、不需要账号。数据就是几个 Markdown 文件加一个 JSON 索引，
随时可以打开看、可以拷走。

![主界面](https://raw.githubusercontent.com/200762zzy/AlgorithmNoteHelper/main/docs/main-window.png)

## 下载后怎么用

1. 下载下面的 `AlgorithmNoteHelper-v0.1.0-win64.zip`，解压到任意目录。
   建议**不要**放在 `C:\Program Files\` 这类只读位置（程序会把数据存在自己旁边，
   放只读位置时会自动改存到 `%APPDATA%`，那样就不是便携版了）。
2. 双击 `AlgorithmNoteHelper.exe`。
3. **首次运行 SmartScreen 会拦一下** —— 点「更多信息」→「仍要运行」即可。
   这不是病毒警报，详见压缩包内的 `FIRST_RUN.md`。
4. 数据存在 exe 旁边的 `data/`。整个文件夹拷到 U 盘或另一台电脑，错题一起跟过去。

> ⚠️ **不要用 Typora / Obsidian 直接编辑 `data/notes/*.md`。**
> 程序保存时会整篇重新生成，你的外部修改会被覆盖。要外部编辑，请用「导出 md」导一份副本。

## 这个版本有什么

- **只填标题就能录**：题目简述是唯一必填字段，难度与错因有默认值、可事后补
- **剪贴板快速新建**（`Ctrl+Shift+N`）：标题取自剪贴板首行，是链接就顺手填进题目链接
- **三档复习评分**（忘记 / 困难 / 轻松）驱动 SM-2：自动算下次复习日期，自动生成「待复习」队列
- **「已掌握」不是终点**：间隔拉长到 30 天以上进入已掌握，但逾期一周仍会回到队列，
  避免 SM-2 最有价值的长间隔段被截断
- 按关键词 / 标签 / 难度 / 复习状态筛选，一键筛出今天该复习的
- 导出单条错题为 Markdown，front-matter 齐全，可直接进 Typora / Obsidian
- **单文件全量快照**：一个 JSON 含索引与全部正文，可备份、可恢复、
  **可与同学互导题解**（重复条目可选跳过 / 覆盖 / 收为副本）

## 数据安全

这个工具的全部价值是那些正文（错因分析、AC 代码），所以对"别丢数据"处理得比较偏执：

- 原子写（同目录临时文件 → `fsync` → `os.replace`），写到一半崩溃不会损坏索引/正文
- 每次保存前轮转备份 `index.json`（保留最近 10 份）
- 删除前先把该条（含正文）单独存一份快照
- 单实例锁（`QLockFile`）：防止双击两次开两个进程、退出时互相覆盖索引
- 数据目录不可写时自动回落 `%APPDATA%`
- 导入/恢复前校验每个 `id` 是合法 uuid4（`id` 直接用作文件名，不校验就能路径穿越）；
  校验失败即**整份拒绝**，绝不写进半个数据目录

## 已验证 / 未验证

**已验证：**

- 116 项 pytest 全绿，覆盖数据层的全部一致性约束
- 分发件通过两项非交互自检：数据层自检，以及 Qt 平台插件与界面层自检
  （后者确认打包件加载了 `windows` 平台插件，并渲染出 1200×800 的一帧）

**未验证（如实说明）：**

- 只在作者的 Windows 11 25H2 家用版上跑过，**没有在其他机器 / 其他 Windows 版本上测试过**
- UI 没有自动化测试，交互与手感靠手工验证

遇到问题欢迎开 issue。

## 已知限制

- 没有 C++ 语法高亮（`QSyntaxHighlighter` 可随时接入，列入 V0.2）
- 搜索只覆盖索引字段，不含正文全文搜索
- 快速新建是**应用内**快捷键，不是系统级全局热键
- 不支持把外部编辑过的 md 回读进应用
- 打包体积 119.6 MB。模块级 `--exclude-module` 只排 Python 侧模块，排不掉底层 Qt DLL
  （`Qt6Quick` / `Qt6Qml` / `libcrypto` / `opengl32sw` 合计约 35 MB 仍在包内）
- 未做代码签名，所以每次分发都会触发 SmartScreen 提醒

## 不想用 exe？

装好 Python 3.10+ 之后：

```
pip install -r requirements.txt
python main.py
```

出问题可以先跑一次自检（不会打开界面，结果同时写进 `data/self-check.log`）：

```
AlgorithmNoteHelper.exe --self-check
```

## 从源码构建

```
powershell -ExecutionPolicy Bypass -File tools/build.ps1
```

## 许可证

MIT
