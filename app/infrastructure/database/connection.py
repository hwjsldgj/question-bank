"""SQLite 连接管理器。

封装本地数据库连接的创建、事务与行工厂设置，供各仓储实现共享，
保证整个应用共享同一连接（桌面单用户场景，需求 R18）。

依赖：标准库 sqlite3 / contextlib
被使用：app.infrastructure.repositories.*、app.infrastructure.config_store、
        app.container
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DatabaseConnection:
    """SQLite 连接管理器：单连接 + 上下文管理器式事务。"""

    def __init__(self, db_path: str | Path) -> None:
        """记录数据库文件路径；连接在首次 :meth:`connect` 时惰性创建。"""
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """返回共享连接（惰性创建，启用外键与 Row 行工厂）。"""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文：正常退出提交，异常退出回滚（需求 R16 第 1 / 2 条）。

        用法::

            with db.transaction() as conn:
                conn.execute(...)
        """
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """关闭连接（程序退出时调用）。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
