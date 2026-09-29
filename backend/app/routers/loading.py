"""装卸作业接口：维护装卸记录，覆盖开始装卸、确认完成、标记超时等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchActionResult,
    EntryPayload,
    LoadingBatchPayload,
    PageResult,
)
from app.services.loading import LOADING_TYPES, LoadingService
from app.services.shipment import STATUS_ORDER as WAYBILL_STATUSES

router = APIRouter(prefix="/api/loading", tags=["装卸作业"])

service = LoadingService()

LIST_FIELDS = ["记录编号", "运单编号", "装卸类型", "月台编号", "开门时长", "装卸人员", "开始时间", "运单状态", "装卸状态"]
STATUSES = ["待装卸", "装卸中", "已完成", "已超时"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="待装卸、装卸中、已完成、已超时"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤装卸作业列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/batch", response_model=BatchActionResult)
def batch_update(payload: LoadingBatchPayload) -> BatchActionResult:
    """批量逐条更新装卸类型、开门时长、运单状态。

    同一批次号重传视为断网续传：服务端只落库未完成项，已完成项跳过、不重复写入；
    任一项校验失败，本批本次写入整体回滚。
    """
    ok, message, updated, skipped, entries = service.batch_update(
        payload.batch_id, payload.items
    )
    return BatchActionResult(
        ok=ok,
        message=message,
        batch_id=payload.batch_id,
        updated=updated,
        skipped=skipped,
        entries=entries,
    )


@router.get("/options")
def update_options() -> dict[str, Any]:
    """批量更新可选项：装卸类型与运单状态枚举，前后端同源，避免页面硬编码。"""
    return {"装卸类型": LOADING_TYPES, "运单状态": WAYBILL_STATUSES}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条装卸记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"装卸记录 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/waybill", response_model=dict)
def get_entry_waybill(entry_id: int) -> dict:
    """读取装卸记录关联的运单详情，作业明细与运单详情同源返回。"""
    waybill, message = service.get_waybill(entry_id)
    if waybill is None:
        raise HTTPException(status_code=404, detail=message)
    return waybill


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条装卸记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="装卸记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条装卸记录执行开始装卸、确认完成、标记超时；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出装卸作业清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "loading", "total": total, "items": items}
