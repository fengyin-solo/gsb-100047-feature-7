"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 批量操作的行级锁：保证一批记录的「校验 + 落库」不会和其他写请求交织。
        self._lock = threading.RLock()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def find_by(self, module: str, field: str, value: str) -> dict[str, Any] | None:
        """按业务编号（如运单编号）定位一条记录。"""
        for row in self.rows(module):
            if str(row.get(field, "")) == str(value):
                return row
        return None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """事务边界：进入时对全部表做深拷贝快照，块内异常则整体回滚。

        内存仓库里的「落库」就是改这些 dict/list，深拷贝快照即可保证
        「任何一项失败，本批已写结果全部回滚」；真实数据库场景换成
        BEGIN/COMMIT/ROLLBACK 即可，service 层代码不用动。
        """
        with self._lock:
            snapshot = {name: [dict(row) for row in rows] for name, rows in self._tables.items()}
            try:
                yield
            except Exception:
                self._tables = snapshot
                raise

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
