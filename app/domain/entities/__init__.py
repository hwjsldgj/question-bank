"""领域实体与值对象（Data Models）。

对应设计文档 "Data Models" 章节，每个文件一个聚合根或值对象：

- ``question``      Question：题目（核心实体）+ Option / QuestionFilter
- ``usage_record``  UsageRecord：题目使用记录（近期重复抑制的数据基础）
- ``criteria``      PaperCriteria：组卷条件（两部分均可选）
- ``paper``         Paper / Section：试卷与分区
- ``scoring``       ScoreFactors / ScoredQuestion / ScoringContext：评分模型
- ``configs``       ScoringConfig / AIConfig / ExportOptions：配置值对象
- ``task``          GenerationTask：组卷任务记录

依赖：app.domain.enums
被使用：app.domain.validators、app.interfaces.*、app.application.*、
        app.infrastructure.*、app.presentation.*
"""
