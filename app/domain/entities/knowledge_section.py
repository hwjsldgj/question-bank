"""KnowledgeSection：科目下的知识点板块，板块内再细分具体知识点。

对应用户需求：

- 手动导入（录入）时提供板块项目，选中板块后提供该板块的知识点细分；
- AI 辨识不再一次性笼统输出知识点，而是先按知识点板块分级、再对每个板块
  细化到具体知识点，一道题可涉及多个板块与多个知识点。

依赖：无（领域值对象）
被使用：app.infrastructure.config_store（配置持久化返回值）、
        app.application.question_service（知识点板块列表与提示词）
        app.presentation.views.settings_view / question_bank_view（录入联动）
"""

from dataclasses import dataclass, field


@dataclass
class KnowledgeSection:
    """科目 -> 知识点板块 -> 细分知识点的一级映射。

    :param subject: 所属科目
    :param section: 知识点板块名称（如数学的"代数"、"几何"）
    :param knowledge_points: 该板块下的细分知识点，录入时作为该板块的候选
    """

    subject: str
    section: str
    knowledge_points: list[str] = field(default_factory=list)

    def add_point(self, point: str) -> None:
        """追加一个细分知识点（去重，保持顺序）。"""
        name = str(point).strip()
        if name and name not in self.knowledge_points:
            self.knowledge_points.append(name)

    def remove_point(self, point: str) -> None:
        """删除一个细分知识点。"""
        name = str(point).strip()
        if name in self.knowledge_points:
            self.knowledge_points.remove(name)