# question-paper-generator

个人自用的高考数学组卷工具：从 Typst 格式真题切题建库，按评分决策 + 加权随机
组卷，导出 PDF（含图题即时渲染 Typst 图形、卷末附答案页）。

技术栈：PySide6 + SQLite + PyTorch + Typst + MathJax。
运行环境：Windows 10，Python 3.13，CPU 离线运行。

## 运行

```
pip install -r requirements.txt
python main.py
python -m pytest tests/ -q
```

首次启动自动创建 `question_bank.db`（SQLite，本机存储）。
AI 功能需在"设置 → AI 设置"配置 API 地址、Key 与模型；未配置时其余功能正常。

## 目录

```
app/
├── domain/          实体、枚举、校验器
├── interfaces/      仓储 / AI / 导出器抽象
├── application/     题目服务、评分、抽样、组卷、导出编排
├── infrastructure/  SQLite、AI 客户端、MD/PDF 导出、Typst 渲染
├── presentation/    PySide6 主窗口与四个视图
├── config/          默认配置
└── container.py     组合根
main.py              入口
scripts/             数据修复 / 维护脚本
tests/               测试
```

## 开发

见 `AGENTS.md`。
