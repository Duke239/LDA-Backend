from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import math
import re

from bson import ObjectId
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
import pandas as pd


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _money(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return round(float(value), 2)
    except Exception:
        return 0.0


def _float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _safe_code(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    # Keep codes like 411107.01 stable even if Excel reads as float.
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") if not str(value).endswith(".0") else str(int(value))
    return str(value).strip()


def _serialise_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    out = dict(doc)
    if "_id" in out:
        out["id"] = str(out.pop("_id"))
    return out


def _line_totals(line: Dict[str, Any]) -> Dict[str, Any]:
    quantity = _float(line.get("quantity", 0))
    library_rate = _money(line.get("library_unit_rate", 0))
    override_rate = line.get("override_unit_rate")
    unit_rate = _money(override_rate if override_rate not in [None, ""] else library_rate)

    labour_value_per_uom = _money(line.get("est_labour_value_per_uom", 0))
    materials_value_per_uom = _money(line.get("est_materials_other_value_per_uom", 0))
    labour_hours_per_uom = _float(line.get("est_labour_hours_per_uom", 0))

    net = round(quantity * unit_rate, 2)
    vat_rate = _float(line.get("vat_rate", 0.2))
    vat = round(net * vat_rate, 2)
    gross = round(net + vat, 2)

    # Scale labour/material split to the selected unit rate. This preserves the imported split
    # even when a quote-only override rate is used.
    imported_split_total = labour_value_per_uom + materials_value_per_uom
    if imported_split_total > 0:
        split_scale = unit_rate / imported_split_total
    elif unit_rate > 0:
        split_scale = 1
    else:
        split_scale = 0

    labour_total = round(quantity * labour_value_per_uom * split_scale, 2)
    materials_total = round(quantity * materials_value_per_uom * split_scale, 2)
    labour_hours_total = round(quantity * labour_hours_per_uom, 2)

    line.update({
        "effective_unit_rate": unit_rate,
        "net_amount": net,
        "vat_amount": vat,
        "gross_amount": gross,
        "est_labour_total": labour_total,
        "est_materials_other_total": materials_total,
        "est_labour_hours_total": labour_hours_total,
    })
    return line


def _build_totals(lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    calculated = [_line_totals(dict(line)) for line in lines]
    net = round(sum(_money(line.get("net_amount")) for line in calculated), 2)
    vat = round(sum(_money(line.get("vat_amount")) for line in calculated), 2)
    gross = round(sum(_money(line.get("gross_amount")) for line in calculated), 2)
    labour = round(sum(_money(line.get("est_labour_total")) for line in calculated), 2)
    materials = round(sum(_money(line.get("est_materials_other_total")) for line in calculated), 2)
    hours = round(sum(_float(line.get("est_labour_hours_total")) for line in calculated), 2)
    return {
        "net_total": net,
        "vat_total": vat,
        "gross_total": gross,
        "est_labour_total": labour,
        "est_materials_other_total": materials,
        "est_labour_hours_total": hours,
        "line_count": len(calculated),
    }


class PriceBuildLine(BaseModel):
    sor_code: Optional[str] = None
    parent_nhf_code: Optional[str] = None
    description: str
    uom: str = "item"
    quantity: float = 1
    library_unit_rate: float = 0
    override_unit_rate: Optional[float] = None
    override_reason: Optional[str] = None
    vat_rate: float = 0.2
    trade_required: Optional[str] = None
    job_type: Optional[str] = None
    line_type: Optional[str] = None
    labour_rate_used: Optional[float] = None
    labour_allocation_percent: Optional[float] = None
    est_labour_value_per_uom: Optional[float] = 0
    est_materials_other_value_per_uom: Optional[float] = 0
    est_labour_hours_per_uom: Optional[float] = 0
    est_labour_minutes_per_uom: Optional[float] = 0
    split_confidence: Optional[str] = None
    split_note: Optional[str] = None
    pricing_note: Optional[str] = None


class PriceBuildPayload(BaseModel):
    project_id: Optional[str] = None
    quote_reference: Optional[str] = None
    build_name: str = Field(default="New price build")
    status: str = Field(default="Draft")
    notes: Optional[str] = None
    lines: List[PriceBuildLine] = []


def create_price_builder_router(db) -> APIRouter:
    router = APIRouter()
    sor_collection = db["sor_rates"]
    builds_collection = db["price_builds"]

    @router.on_event("startup")
    async def _ensure_indexes():
        await sor_collection.create_index("granular_sor_code", unique=True)
        await sor_collection.create_index("parent_nhf_code")
        await sor_collection.create_index("job_type")
        await sor_collection.create_index("trade_required")
        await sor_collection.create_index("line_type")
        await builds_collection.create_index("project_id")
        await builds_collection.create_index("created_at")

    @router.post("/price-builder/import-sor-library")
    async def import_sor_library(file: UploadFile = File(...), replace_existing: bool = Query(False)):
        if not file.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="Upload an Excel workbook (.xlsx or .xls).")

        content = await file.read()
        from io import BytesIO
        try:
            df = pd.read_excel(BytesIO(content), sheet_name="SOR Rates")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read 'SOR Rates' sheet: {exc}")

        if replace_existing:
            await sor_collection.delete_many({})

        docs = []
        for _, row in df.iterrows():
            unit_rate = _money(row.get("Granular Unit Net Rate"))
            labour_value = _money(row.get("Est. Labour Value / UOM"))
            materials_value = _money(row.get("Est. Materials/Other Value / UOM"))
            labour_hours = _float(row.get("Est. Labour Hours / UOM"))
            labour_minutes = _float(row.get("Est. Labour Minutes / UOM"))
            labour_rate = _money(row.get("Labour Rate Used (£/hr)"))

            # Fallback for importing the older workbook before the split columns existed.
            if labour_value == 0 and materials_value == 0 and unit_rate > 0:
                labour_value = round(unit_rate * 0.6, 2)
                materials_value = round(unit_rate - labour_value, 2)
                if labour_rate <= 0:
                    labour_rate = 37.0
                labour_hours = round(labour_value / labour_rate, 4)
                labour_minutes = round(labour_hours * 60, 1)

            doc = {
                "parent_nhf_code": _safe_code(row.get("Parent NHF Code")),
                "granular_sor_code": _safe_code(row.get("Granular SOR Code")),
                "job_type": _clean_value(row.get("Job Type")),
                "trade_required": _clean_value(row.get("Trade Required")),
                "description": _clean_value(row.get("Granular Task Description")),
                "uom": _clean_value(row.get("UOM")) or "item",
                "source_quantity_basis": _float(row.get("Source Quantity Basis")),
                "nhf_baseline_rate": _money(row.get("NHF Baseline Rate")),
                "split_percent": _float(row.get("Split %")),
                "granular_unit_net_rate": unit_rate,
                "vat_rate": _float(row.get("VAT Rate")) or 0.2,
                "line_type": _clean_value(row.get("Line Type")),
                "parent_price_item": _clean_value(row.get("Parent Price Item")),
                "original_nhf_description": _clean_value(row.get("Original NHF Description")),
                "pricing_split_note": _clean_value(row.get("Pricing / Split Note")),
                "source_row": _clean_value(row.get("Source Row")),
                "labour_rate_used": labour_rate,
                "labour_allocation_percent": _float(row.get("Labour Allocation %")),
                "est_labour_value_per_uom": labour_value,
                "est_materials_other_value_per_uom": materials_value,
                "est_labour_hours_per_uom": labour_hours,
                "est_labour_minutes_per_uom": labour_minutes,
                "split_confidence": _clean_value(row.get("Split Confidence")),
                "split_note": _clean_value(row.get("Split Note")),
                "selection_label": f"{_clean_value(row.get('Granular Task Description'))} — {_clean_value(row.get('UOM')) or 'item'} — {_clean_value(row.get('Line Type')) or 'Rate'}",
                "updated_at": _now_iso(),
            }
            if doc["granular_sor_code"] and doc["description"]:
                docs.append(doc)

        upserted = 0
        for doc in docs:
            await sor_collection.update_one(
                {"granular_sor_code": doc["granular_sor_code"]},
                {"$set": doc, "$setOnInsert": {"created_at": _now_iso()}},
                upsert=True,
            )
            upserted += 1

        return {"success": True, "imported_or_updated": upserted, "replace_existing": replace_existing}

    @router.get("/price-builder/filters")
    async def get_price_builder_filters():
        return {
            "job_types": sorted([v for v in await sor_collection.distinct("job_type") if v]),
            "trades": sorted([v for v in await sor_collection.distinct("trade_required") if v]),
            "line_types": sorted([v for v in await sor_collection.distinct("line_type") if v]),
            "uoms": sorted([v for v in await sor_collection.distinct("uom") if v]),
        }

    @router.get("/price-builder/rates")
    async def search_rates(
        search: str = "",
        job_type: str = "",
        trade: str = "",
        line_type: str = "",
        include_non_priceable: bool = False,
        limit: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
    ):
        query: Dict[str, Any] = {}
        if job_type:
            query["job_type"] = job_type
        if trade:
            query["trade_required"] = trade
        if line_type:
            query["line_type"] = line_type
        elif not include_non_priceable:
            query["line_type"] = {"$regex": "priceable|single|parent", "$options": "i"}

        if search.strip():
            escaped = re.escape(search.strip())
            query["$or"] = [
                {"granular_sor_code": {"$regex": escaped, "$options": "i"}},
                {"parent_nhf_code": {"$regex": escaped, "$options": "i"}},
                {"description": {"$regex": escaped, "$options": "i"}},
                {"original_nhf_description": {"$regex": escaped, "$options": "i"}},
                {"parent_price_item": {"$regex": escaped, "$options": "i"}},
            ]

        cursor = sor_collection.find(query).sort([("job_type", 1), ("description", 1)]).skip(skip).limit(limit)
        rates = [_serialise_doc(doc) async for doc in cursor]
        total = await sor_collection.count_documents(query)
        return {"rates": rates, "total": total, "skip": skip, "limit": limit}

    @router.get("/price-builder/rates/{sor_code}")
    async def get_rate(sor_code: str):
        rate = await sor_collection.find_one({"granular_sor_code": sor_code})
        if not rate:
            raise HTTPException(status_code=404, detail="SOR rate not found")
        siblings = []
        parent = rate.get("parent_nhf_code")
        if parent:
            siblings = [_serialise_doc(doc) async for doc in sor_collection.find({"parent_nhf_code": parent}).sort("granular_sor_code", 1)]
        return {"rate": _serialise_doc(rate), "siblings": siblings}

    @router.post("/price-builds")
    async def create_price_build(payload: PriceBuildPayload):
        lines = [_line_totals(line.model_dump()) for line in payload.lines]
        doc = payload.model_dump()
        doc["lines"] = lines
        doc["totals"] = _build_totals(lines)
        doc["created_at"] = _now_iso()
        doc["updated_at"] = _now_iso()
        result = await builds_collection.insert_one(doc)
        saved = await builds_collection.find_one({"_id": result.inserted_id})
        return _serialise_doc(saved)

    @router.get("/price-builds")
    async def list_price_builds(project_id: str = "", limit: int = Query(50, ge=1, le=200)):
        query = {"project_id": project_id} if project_id else {}
        builds = [_serialise_doc(doc) async for doc in builds_collection.find(query).sort("updated_at", -1).limit(limit)]
        return {"builds": builds}

    @router.get("/price-builds/{build_id}")
    async def get_price_build(build_id: str):
        if not ObjectId.is_valid(build_id):
            raise HTTPException(status_code=400, detail="Invalid build id")
        doc = await builds_collection.find_one({"_id": ObjectId(build_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Price build not found")
        return _serialise_doc(doc)

    @router.put("/price-builds/{build_id}")
    async def update_price_build(build_id: str, payload: PriceBuildPayload):
        if not ObjectId.is_valid(build_id):
            raise HTTPException(status_code=400, detail="Invalid build id")
        lines = [_line_totals(line.model_dump()) for line in payload.lines]
        update = payload.model_dump()
        update["lines"] = lines
        update["totals"] = _build_totals(lines)
        update["updated_at"] = _now_iso()
        result = await builds_collection.update_one({"_id": ObjectId(build_id)}, {"$set": update})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Price build not found")
        doc = await builds_collection.find_one({"_id": ObjectId(build_id)})
        return _serialise_doc(doc)

    @router.delete("/price-builds/{build_id}")
    async def delete_price_build(build_id: str):
        if not ObjectId.is_valid(build_id):
            raise HTTPException(status_code=400, detail="Invalid build id")
        result = await builds_collection.delete_one({"_id": ObjectId(build_id)})
        return {"success": result.deleted_count == 1}

    return router
