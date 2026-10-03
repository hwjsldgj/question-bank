"""LocalImageStore：题目图片的本地存储（用户需求：题目图片导入）。

保存策略：把用户选择的图片复制到数据库所在目录的 ``images/`` 子目录，
数据库仅记录相对路径（如 ``images/3f2a....png``），便于整库备份与迁移。

依赖：标准库 pathlib / shutil / uuid、app.domain.errors
被使用：app.container（装配）、app.presentation.views.question_bank_view
"""

import shutil
import uuid
from pathlib import Path

from app.domain.errors import ImageImportError

#: 允许导入的图片扩展名
SUPPORTED_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".webp",
)


class LocalImageStore:
    """本地图片存储：复制导入 + 相对路径解析。"""

    def __init__(self, root: str | Path, subdir: str = "images") -> None:
        """注入存储根目录（通常为数据库文件所在目录）。

        :param root: 根目录
        :param subdir: 图片子目录名
        """
        self.root = Path(root)
        self.subdir = subdir

    @property
    def directory(self) -> Path:
        """图片目录的绝对路径（首次需要时创建）。"""
        path = self.root / self.subdir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def is_supported(source: str | Path) -> bool:
        """判断文件扩展名是否属于支持的图片格式。"""
        return Path(source).suffix.lower() in SUPPORTED_IMAGE_SUFFIXES

    def save(self, source: str | Path) -> str:
        """把外部图片复制进本地图片目录，返回相对路径。

        :raises app.domain.errors.ImageImportError: 文件不存在或格式不支持
        """
        source_path = Path(source)
        if not source_path.is_file():
            raise ImageImportError(f"图片文件不存在：{source_path}")
        if not self.is_supported(source_path):
            raise ImageImportError(
                "仅支持 " + " / ".join(SUPPORTED_IMAGE_SUFFIXES) + " 格式的图片"
            )
        target = self.directory / f"{uuid.uuid4().hex}{source_path.suffix.lower()}"
        shutil.copy2(source_path, target)
        return self.relative(target)

    def relative(self, path: str | Path) -> str:
        """把图片绝对路径转换为相对根目录的 POSIX 风格路径。"""
        candidate = Path(path)
        try:
            return candidate.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return candidate.as_posix()

    def resolve(self, relative: str | None) -> Path | None:
        """把数据库中的相对路径还原为绝对路径；为空或不存在时返回 None。"""
        if not relative:
            return None
        candidate = Path(relative)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate if candidate.is_file() else None

    def delete(self, relative: str | None) -> None:
        """删除本地图片文件；文件不存在时静默忽略。"""
        path = self.resolve(relative)
        if path is not None:
            path.unlink(missing_ok=True)
