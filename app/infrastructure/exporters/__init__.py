"""导出器实现：MD 与 PDF 两种格式（需求 R12 / R18）。

- ``md_exporter.MdExporter``：Markdown 源文件排版，标准库实现，零第三方依赖
- ``pdf_exporter.PdfExporter``：先用 MdExporter 产出 ``.md``，再渲染成带 MathJax
  与打印 CSS 的 HTML，最后用 Edge 无头模式打印为同名 ``.pdf``
  （参考实现 ``exports/试卷.py``）；``markdown`` 包在方法内惰性导入

两者输出内容结构一致：选择题 / 解答题两部分、分区小计、总分、卷末答案页。
被使用：app.container（装配为 PaperExporter 的格式映射）、tests
"""
