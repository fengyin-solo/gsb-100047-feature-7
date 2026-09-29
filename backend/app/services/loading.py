"""装卸作业业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.schemas import LoadingBatchItem
from app.services.shipment import STATUS_ORDER as WAYBILL_STATUSES
from app.store import store

MODULE = "loading"
REQUIRED_FIELDS = ["记录编号", "运单编号", "装卸类型"]
STATUS_ORDER = ["待装卸", "装卸中", "已完成", "已超时"]
ACTION_RULES = {"开始装卸": "装卸中", "确认完成": "已完成", "标记超时": "已超时"}
NEGATIVE_ACTIONS = []

# 装卸类型只允许装车/卸车；运单状态口径与发运单模块同源（shipment.STATUS_ORDER）。
LOADING_TYPES = ["装车", "卸车"]
UPDATABLE_FIELDS = ["装卸类型", "开门时长", "运单状态"]


class BatchUpdateError(Exception):
    """批量落库过程中的业务错误：抛出即触发整批回滚。"""


class LoadingService:
    def __init__(self) -> None:
        # 幂等台账：batch_id -> {记录id: 已落库字段}。
        # 断网重传同一批时据此识别已完成项，只从未完成项继续，不重复落库。
        self._batches: dict[str, dict[int, dict[str, Any]]] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_waybill(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """读取装卸记录关联的运单：记录不存在或未关联运单时给出原因。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"装卸记录 {entry_id} 不存在或已归档"
        waybill_no = str(entry.get("运单编号") or "").strip()
        if not waybill_no:
            return None, f"装卸记录 {entry_id} 未关联运单"
        waybill = store.find_by("shipment", "运单编号", waybill_no)
        if waybill is None:
            return None, f"运单 {waybill_no} 不存在或已归档"
        return waybill, ""

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"装卸记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于装卸作业可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"装卸记录已{action}"

    def batch_update(
        self,
        batch_id: str,
        items: list[LoadingBatchItem],
    ) -> tuple[bool, str, list[int], list[int], list[dict[str, Any]]]:
        """批量逐条更新装卸类型、开门时长、运单状态。

        - 事务性落库：所有项在同一事务里校验并写入，任何一项失败，本批本次已写全部回滚；
        - 断点续传：同一 batch_id 重传时跳过台账里已完成的记录，只处理未完成项，不重复生成写入。
        """
        ids = [item.entry_id for item in items]
        if len(ids) != len(set(ids)):
            return False, "同一批提交里装卸记录不能重复，请合并后再提交", [], [], []

        ledger = self._batches.setdefault(batch_id, {})
        pending = [item for item in items if item.entry_id not in ledger]
        skipped = [entry_id for entry_id in ids if entry_id in ledger]
        if not pending:
            entries = [store.find(MODULE, entry_id) for entry_id in ids]
            return True, self._result_message([], skipped), [], skipped, [e for e in entries if e]

        updated: list[int] = []
        try:
            with store.transaction():
                applied: dict[int, dict[str, Any]] = {}
                for item in pending:
                    self._apply_one(item, applied)
                    updated.append(item.entry_id)
                # 全部成功才登记台账；中途异常会随事务一起放弃，已完成项不会被误记。
                ledger.update(applied)
        except BatchUpdateError as exc:
            return False, str(exc), [], skipped, []

        entries = [store.find(MODULE, entry_id) for entry_id in ids]
        return True, self._result_message(updated, skipped), updated, skipped, [e for e in entries if e]

    def _apply_one(self, item: LoadingBatchItem, applied: dict[int, dict[str, Any]]) -> None:
        """校验并落库单条记录；任一环节不合法都抛 BatchUpdateError 触发整批回滚。"""
        entry_id = item.entry_id
        entry = store.find(MODULE, item.entry_id)
        if entry is None:
            raise BatchUpdateError(f"装卸记录 {entry_id} 不存在或已归档，本批已全部回滚")
        if item.loading_type not in LOADING_TYPES:
            raise BatchUpdateError(
                f"装卸记录 {entry_id} 的装卸类型「{item.loading_type}」不合法，仅支持装车/卸车，本批已全部回滚"
            )
        if item.door_minutes < 0:
            raise BatchUpdateError(f"装卸记录 {entry_id} 的开门时长不能为负数，本批已全部回滚")
        if item.waybill_status not in WAYBILL_STATUSES:
            raise BatchUpdateError(
                f"装卸记录 {entry_id} 的运单状态「{item.waybill_status}」不在允许范围内，本批已全部回滚"
            )

        waybill_no = str(entry.get("运单编号") or "").strip()
        if not waybill_no:
            raise BatchUpdateError(f"装卸记录 {entry_id} 未关联运单，无法同步运单状态，本批已全部回滚")
        waybill = store.find_by("shipment", "运单编号", waybill_no)
        if waybill is None:
            raise BatchUpdateError(f"运单 {waybill_no} 不存在或已归档，本批已全部回滚")

        # 装卸记录与关联运单同源写入，列表/运单详情/作业明细读到的是同一份字段。
        entry["装卸类型"] = item.loading_type
        entry["开门时长"] = item.door_minutes
        entry["运单状态"] = item.waybill_status
        waybill["运单状态"] = item.waybill_status
        waybill["status"] = item.waybill_status
        waybill["pending"] = item.waybill_status != WAYBILL_STATUSES[-1]

        applied[entry_id] = {
            "装卸类型": item.loading_type,
            "开门时长": item.door_minutes,
            "运单状态": item.waybill_status,
        }

    @staticmethod
    def _result_message(updated: list[int], skipped: list[int]) -> str:
        parts = [f"批量更新完成，本次落库 {len(updated)} 条"]
        if skipped:
            parts.append(f"跳过上次已完成 {len(skipped)} 条（未重复写入）")
        return "，".join(parts)
