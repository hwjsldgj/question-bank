"""导出器实现：MD 与 PDF 两种格式（需求 R12 / R18）。

- ``md_exporter.MdExporter``：Markdown 源文件排版，标准库实现，零第三方依赖
- ``pdf_exporter.PdfExporter``：先用 MdExporter 产出 ``.md``，再用 pymd2pdf
  把它转成同名 ``.pdf``；pymd2pdf 在方法内惰性导入

两者输出内容结构一致：选择题 / 解答题两部分、分区小计、总分、卷末答案页。
被使用：app.container（装配为 PaperExporter 的格式映射）、tests
"""
