import os
import uuid
import base64
from io import StringIO, BytesIO
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List

import pytz
from fastapi import FastAPI, APIRouter, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# =====================================================
# LDA WORK APP - COMPLETE SERVER.PY
# Includes workers, jobs, materials, time entries,
# activity map/device flags and PDF timesheet export.
# =====================================================

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "lda_work_app")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

UK_TZ = pytz.timezone("Europe/London")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="LDA Work App API")
api_router = APIRouter(prefix="/api")

allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://lda-group.vercel.app",
    "https://lda-group-one.vercel.app",
]
extra_origins = os.environ.get("CORS_ORIGINS")
if extra_origins:
    allowed_origins.extend([o.strip() for o in extra_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# Helpers
# ----------------------

def now_uk_naive() -> datetime:
    return datetime.now(UK_TZ).replace(tzinfo=None)


def make_id() -> str:
    return str(uuid.uuid4())


def clean_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


def parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo:
            dt = dt.astimezone(UK_TZ).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def parse_date_start(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value[:10])


def minutes_between(start: Any, end: Any) -> int:
    s = parse_datetime(start)
    e = parse_datetime(end)
    if not s or not e:
        return 0
    return max(0, int((e - s).total_seconds() / 60))


def auth_from_basic_header(header: Optional[str]) -> bool:
    if not header:
        return False
    try:
        scheme, encoded = header.split(" ", 1)
        if scheme.lower() != "basic":
            return False
        raw = base64.b64decode(encoded).decode("utf-8")
        username, password = raw.split(":", 1)
        return username == ADMIN_USERNAME and password == ADMIN_PASSWORD
    except Exception:
        return False


async def get_current_admin(request: Request):
    # Existing frontend stores base64 credentials in localStorage and sends Basic auth.
    # During development you can set ADMIN_USERNAME / ADMIN_PASSWORD in Render env vars.
    if auth_from_basic_header(request.headers.get("Authorization")):
        return {"username": ADMIN_USERNAME}
    raise HTTPException(status_code=401, detail="Admin authentication required")


async def get_worker(worker_id: str) -> Dict[str, Any]:
    worker = await db.workers.find_one({"id": worker_id})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return clean_doc(worker)


async def get_job(job_id: str) -> Dict[str, Any]:
    job = await db.jobs.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return clean_doc(job)


def normalise_worker_type(worker: Dict[str, Any]) -> str:
    value = (worker.get("worker_type") or worker.get("type") or worker.get("role") or "worker").lower()
    if "contractor" in value:
        return "contractor"
    return "worker"


def get_hourly_rate(worker: Dict[str, Any], entry: Optional[Dict[str, Any]] = None) -> float:
    entry = entry or {}
    for key in ["hourly_rate", "hourlyRate", "rate"]:
        if entry.get(key) not in [None, ""]:
            try:
                return float(entry.get(key))
            except Exception:
                pass
        if worker.get(key) not in [None, ""]:
            try:
                return float(worker.get(key))
            except Exception:
                pass
    return 0.0


def build_time_query(worker_id=None, job_id=None, start_date=None, end_date=None, include_archived=False):
    query: Dict[str, Any] = {}
    if worker_id:
        query["worker_id"] = worker_id
    if job_id:
        query["job_id"] = job_id
    if not include_archived:
        query["archived"] = {"$ne": True}
    if start_date or end_date:
        date_query: Dict[str, Any] = {}
        sd = parse_date_start(start_date)
        ed = parse_date_start(end_date)
        if sd:
            date_query["$gte"] = sd
        if ed:
            date_query["$lt"] = ed + timedelta(days=1)
        query["clock_in"] = date_query
    return query


async def enrich_time_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    entry = clean_doc(entry)
    worker = await db.workers.find_one({"id": entry.get("worker_id")}) or {}
    job = await db.jobs.find_one({"id": entry.get("job_id")}) or {}
    clean_doc(worker)
    clean_doc(job)

    entry["worker_name"] = entry.get("worker_name") or worker.get("name") or "Unknown"
    entry["job_name"] = entry.get("job_name") or job.get("name") or "Unknown"
    entry["job_client"] = entry.get("job_client") or job.get("client") or ""
    entry["job_location"] = entry.get("job_location") or job.get("location") or job.get("address") or ""
    entry["worker_division"] = worker.get("division") or entry.get("worker_division") or "-"
    entry["job_division"] = job.get("division") or entry.get("job_division") or "-"
    entry["worker_type"] = entry.get("worker_type") or normalise_worker_type(worker)
    entry["hourly_rate"] = get_hourly_rate(worker, entry)
    entry["duration_minutes"] = entry.get("duration_minutes") or minutes_between(entry.get("clock_in"), entry.get("clock_out"))
    entry["duration_hours"] = round(float(entry.get("duration_minutes") or 0) / 60, 2)
    entry["cost"] = entry.get("cost") if entry.get("cost") is not None else round(entry["duration_hours"] * entry["hourly_rate"], 2)
    entry.setdefault("suspicious_flags", [])
    return entry


def make_flags(entry: Dict[str, Any], worker: Dict[str, Any], job: Dict[str, Any]) -> List[str]:
    flags = list(entry.get("suspicious_flags") or [])
    gps_exempt = bool(worker.get("gps_exempt") or worker.get("gpsExempt") or job.get("gps_exempt") or job.get("gpsExempt"))
    if gps_exempt and "WORKER_GPS_EXEMPT" not in flags:
        flags.append("WORKER_GPS_EXEMPT")
    if not gps_exempt and not (entry.get("latitude") and entry.get("longitude")) and "MISSING_GPS" not in flags:
        flags.append("MISSING_GPS")
    try:
        accuracy = float(entry.get("accuracy") or 0)
        if accuracy > 100 and "POOR_GPS_ACCURACY" not in flags:
            flags.append("POOR_GPS_ACCURACY")
    except Exception:
        pass
    return flags


# ----------------------
# Basic / health
# ----------------------

@app.get("/ping")
async def ping_root():
    return {"status": "ok"}

@app.head("/ping")
async def ping_head():
    return JSONResponse(content=None, status_code=200)

@api_router.get("/ping")
async def ping_api():
    return {"status": "ok"}

@api_router.get("/health")
async def health():
    try:
        await db.command("ping")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})

@api_router.post("/admin/login")
async def admin_login(payload: Dict[str, Any]):
    username = payload.get("username") or payload.get("email")
    password = payload.get("password")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"success": True, "token": token}
    raise HTTPException(status_code=401, detail="Invalid admin credentials")

# ----------------------
# Workers
# ----------------------

@api_router.get("/workers")
async def list_workers(include_archived: bool = False):
    query = {} if include_archived else {"archived": {"$ne": True}}
    workers = await db.workers.find(query).sort("name", 1).to_list(5000)
    return [clean_doc(w) for w in workers]

@api_router.post("/workers")
async def create_worker(payload: Dict[str, Any]):
    item = dict(payload)
    item.setdefault("id", make_id())
    item.setdefault("role", item.get("worker_type") or item.get("type") or "worker")
    item.setdefault("worker_type", normalise_worker_type(item))
    item.setdefault("archived", False)
    item.setdefault("created_at", now_uk_naive())
    await db.workers.insert_one(item)
    return clean_doc(item)

@api_router.get("/workers/{worker_id}")
async def read_worker(worker_id: str):
    return await get_worker(worker_id)

@api_router.put("/workers/{worker_id}")
async def update_worker(worker_id: str, payload: Dict[str, Any]):
    payload.pop("_id", None)
    payload["updated_at"] = now_uk_naive()
    await db.workers.update_one({"id": worker_id}, {"$set": payload}, upsert=False)
    return await get_worker(worker_id)

@api_router.put("/workers/{worker_id}/archive")
async def archive_worker(worker_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.workers.update_one({"id": worker_id}, {"$set": {"archived": True, "archived_at": now_uk_naive()}})
    return {"success": True}

@api_router.put("/workers/{worker_id}/unarchive")
async def unarchive_worker(worker_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.workers.update_one({"id": worker_id}, {"$set": {"archived": False}, "$unset": {"archived_at": ""}})
    return {"success": True}

@api_router.delete("/workers/{worker_id}")
async def delete_worker(worker_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.workers.delete_one({"id": worker_id})
    return {"success": True}

# ----------------------
# Jobs
# ----------------------

@api_router.get("/jobs")
async def list_jobs(include_archived: bool = False, status: Optional[str] = None):
    query: Dict[str, Any] = {} if include_archived else {"archived": {"$ne": True}}
    if status:
        query["status"] = status
    jobs = await db.jobs.find(query).sort("name", 1).to_list(5000)
    return [clean_doc(j) for j in jobs]

@api_router.post("/jobs")
async def create_job(payload: Dict[str, Any]):
    item = dict(payload)
    item.setdefault("id", make_id())
    item.setdefault("archived", False)
    item.setdefault("status", "active")
    item.setdefault("created_at", now_uk_naive())
    await db.jobs.insert_one(item)
    return clean_doc(item)

@api_router.get("/jobs/{job_id}")
async def read_job(job_id: str):
    return await get_job(job_id)

@api_router.put("/jobs/{job_id}")
async def update_job(job_id: str, payload: Dict[str, Any]):
    payload.pop("_id", None)
    payload["updated_at"] = now_uk_naive()
    await db.jobs.update_one({"id": job_id}, {"$set": payload})
    return await get_job(job_id)

@api_router.put("/jobs/{job_id}/archive")
async def archive_job(job_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.jobs.update_one({"id": job_id}, {"$set": {"archived": True, "archived_at": now_uk_naive()}})
    return {"success": True}

@api_router.put("/jobs/{job_id}/unarchive")
async def unarchive_job(job_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.jobs.update_one({"id": job_id}, {"$set": {"archived": False}, "$unset": {"archived_at": ""}})
    return {"success": True}

@api_router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.jobs.delete_one({"id": job_id})
    return {"success": True}

# ----------------------
# Materials
# ----------------------

@api_router.get("/materials")
async def list_materials(job_id: Optional[str] = None):
    query = {"job_id": job_id} if job_id else {}
    materials = await db.materials.find(query).sort("created_at", -1).to_list(5000)
    return [clean_doc(m) for m in materials]

@api_router.post("/materials")
async def create_material(payload: Dict[str, Any]):
    item = dict(payload)
    item.setdefault("id", make_id())
    item.setdefault("quantity", 1)
    item.setdefault("cost", 0)
    item.setdefault("created_at", now_uk_naive())
    await db.materials.insert_one(item)
    return clean_doc(item)

@api_router.put("/materials/{material_id}")
async def update_material(material_id: str, payload: Dict[str, Any]):
    payload.pop("_id", None)
    payload["updated_at"] = now_uk_naive()
    await db.materials.update_one({"id": material_id}, {"$set": payload})
    material = await db.materials.find_one({"id": material_id})
    return clean_doc(material)

@api_router.delete("/materials/{material_id}")
async def delete_material(material_id: str):
    await db.materials.delete_one({"id": material_id})
    return {"success": True}

# ----------------------
# Time entries / clocking
# ----------------------

@api_router.get("/time-entries")
async def list_time_entries(
    worker_id: Optional[str] = None,
    job_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_archived: bool = False,
):
    query = build_time_query(worker_id, job_id, start_date, end_date, include_archived)
    entries = await db.time_entries.find(query).sort("clock_in", -1).to_list(5000)
    return [await enrich_time_entry(e) for e in entries]

@api_router.post("/time-entries")
async def create_time_entry(payload: Dict[str, Any]):
    item = dict(payload)
    item.setdefault("id", make_id())
    item.setdefault("entry_id", item["id"])
    item.setdefault("created_at", now_uk_naive())
    if isinstance(item.get("clock_in"), str):
        item["clock_in"] = parse_datetime(item["clock_in"])
    if isinstance(item.get("clock_out"), str):
        item["clock_out"] = parse_datetime(item["clock_out"])
    item["duration_minutes"] = item.get("duration_minutes") or minutes_between(item.get("clock_in"), item.get("clock_out"))
    await db.time_entries.insert_one(item)
    return await enrich_time_entry(item)

@api_router.put("/time-entries/{entry_id}")
async def update_time_entry(entry_id: str, payload: Dict[str, Any], current_admin: dict = Depends(get_current_admin)):
    payload.pop("_id", None)
    for key in ["clock_in", "clock_out"]:
        if isinstance(payload.get(key), str):
            payload[key] = parse_datetime(payload[key])
    if "clock_in" in payload or "clock_out" in payload:
        existing = await db.time_entries.find_one({"$or": [{"id": entry_id}, {"entry_id": entry_id}]}) or {}
        clock_in = payload.get("clock_in", existing.get("clock_in"))
        clock_out = payload.get("clock_out", existing.get("clock_out"))
        payload["duration_minutes"] = minutes_between(clock_in, clock_out)
    payload["updated_at"] = now_uk_naive()
    await db.time_entries.update_one({"$or": [{"id": entry_id}, {"entry_id": entry_id}]}, {"$set": payload})
    updated = await db.time_entries.find_one({"$or": [{"id": entry_id}, {"entry_id": entry_id}]})
    return await enrich_time_entry(updated)

@api_router.delete("/time-entries/{entry_id}")
async def delete_time_entry(entry_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.time_entries.delete_one({"$or": [{"id": entry_id}, {"entry_id": entry_id}]})
    return {"success": True}

@api_router.post("/time-entries/{entry_id}/archive")
@api_router.put("/time-entries/{entry_id}/archive")
async def archive_time_entry(entry_id: str, current_admin: dict = Depends(get_current_admin)):
    await db.time_entries.update_one({"$or": [{"id": entry_id}, {"entry_id": entry_id}]}, {"$set": {"archived": True, "archived_at": now_uk_naive()}})
    return {"success": True}

@api_router.post("/clock-in")
async def clock_in(payload: Dict[str, Any]):
    worker = await get_worker(payload.get("worker_id"))
    job = await get_job(payload.get("job_id"))
    open_entry = await db.time_entries.find_one({"worker_id": worker["id"], "clock_out": {"$exists": False}, "archived": {"$ne": True}})
    if open_entry:
        raise HTTPException(status_code=400, detail="Worker is already clocked in")

    entry = {
        "id": make_id(),
        "entry_id": make_id(),
        "worker_id": worker["id"],
        "worker_name": worker.get("name"),
        "worker_type": normalise_worker_type(worker),
        "job_id": job["id"],
        "job_name": job.get("name"),
        "job_client": job.get("client", ""),
        "job_location": job.get("location") or job.get("address") or "",
        "clock_in": now_uk_naive(),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "accuracy": payload.get("accuracy"),
        "address": payload.get("address"),
        "clock_in_address": payload.get("address"),
        "device_id_in": payload.get("device_id") or payload.get("deviceId"),
        "archived": False,
        "created_at": now_uk_naive(),
    }
    entry["suspicious_flags"] = make_flags(entry, worker, job)
    await db.time_entries.insert_one(entry)
    return await enrich_time_entry(entry)

@api_router.post("/clock-out")
async def clock_out(payload: Dict[str, Any]):
    worker_id = payload.get("worker_id")
    query = {"worker_id": worker_id, "clock_out": {"$exists": False}, "archived": {"$ne": True}}
    entry = await db.time_entries.find_one(query, sort=[("clock_in", -1)])
    if not entry:
        raise HTTPException(status_code=404, detail="No open clock-in found for this worker")
    worker = await get_worker(entry.get("worker_id"))
    job = await get_job(entry.get("job_id"))
    update = {
        "clock_out": now_uk_naive(),
        "clock_out_latitude": payload.get("latitude"),
        "clock_out_longitude": payload.get("longitude"),
        "clock_out_accuracy": payload.get("accuracy"),
        "clock_out_address": payload.get("address"),
        "device_id_out": payload.get("device_id") or payload.get("deviceId"),
        "updated_at": now_uk_naive(),
    }
    update["duration_minutes"] = minutes_between(entry.get("clock_in"), update["clock_out"])
    merged = {**entry, **update}
    update["suspicious_flags"] = make_flags(merged, worker, job)
    await db.time_entries.update_one({"id": entry.get("id")}, {"$set": update})
    updated = await db.time_entries.find_one({"id": entry.get("id")})
    return await enrich_time_entry(updated)

# ----------------------
# Reports
# ----------------------

@api_router.get("/reports/dashboard")
async def dashboard_report(current_admin: dict = Depends(get_current_admin)):
    today = now_uk_naive().date()
    month_start = today.replace(day=1)
    active_jobs = await db.jobs.count_documents({"archived": {"$ne": True}})
    active_workers = await db.workers.count_documents({"archived": {"$ne": True}, "role": {"$ne": "admin"}})
    open_entries = await db.time_entries.count_documents({"clock_out": {"$exists": False}, "archived": {"$ne": True}})
    month_entries = await db.time_entries.find({"clock_in": {"$gte": datetime.combine(month_start, datetime.min.time())}, "archived": {"$ne": True}}).to_list(5000)
    total_minutes = sum(minutes_between(e.get("clock_in"), e.get("clock_out")) for e in month_entries)
    materials = await db.materials.find({}).to_list(5000)
    total_materials = sum(float(m.get("cost") or 0) * float(m.get("quantity") or 1) for m in materials)
    return {
        "active_jobs": active_jobs,
        "active_workers": active_workers,
        "workers_clocked_in": open_entries,
        "total_hours_this_month": round(total_minutes / 60, 2),
        "total_materials_cost_this_month": round(total_materials, 2),
    }

@api_router.get("/reports/time-entries")
async def report_time_entries(
    worker_id: Optional[str] = None,
    job_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    worker_division: Optional[str] = None,
    job_division: Optional[str] = None,
    worker_type: Optional[str] = None,
    current_admin: dict = Depends(get_current_admin),
):
    entries = await list_time_entries(worker_id, job_id, start_date, end_date)
    out = []
    for e in entries:
        if worker_division and e.get("worker_division") != worker_division:
            continue
        if job_division and e.get("job_division") != job_division:
            continue
        if worker_type and worker_type.lower() not in str(e.get("worker_type", "")).lower():
            continue
        out.append(e)
    return out

@api_router.get("/reports/activity-map")
async def activity_map(date: Optional[str] = None, current_admin: dict = Depends(get_current_admin)):
    selected = parse_date_start(date) if date else datetime.combine(now_uk_naive().date(), datetime.min.time())
    start = selected
    end = selected + timedelta(days=1)
    entries = await db.time_entries.find({"clock_in": {"$gte": start, "$lt": end}, "archived": {"$ne": True}}).sort("clock_in", 1).to_list(5000)
    rows = []
    for raw in entries:
        e = await enrich_time_entry(raw)
        base = {
            "entry_id": e.get("entry_id") or e.get("id"),
            "worker_id": e.get("worker_id"),
            "worker_name": e.get("worker_name"),
            "worker_type": e.get("worker_type"),
            "job_id": e.get("job_id"),
            "job_name": e.get("job_name"),
            "job_client": e.get("job_client"),
            "job_location": e.get("job_location"),
            "clock_in": e.get("clock_in"),
            "clock_out": e.get("clock_out"),
            "device_id_in": e.get("device_id_in"),
            "device_id_out": e.get("device_id_out"),
            "suspicious_flags": e.get("suspicious_flags", []),
        }
        rows.append({**base, "marker_type": "clock_in", "latitude": e.get("latitude"), "longitude": e.get("longitude"), "accuracy": e.get("accuracy"), "address": e.get("clock_in_address") or e.get("address")})
        if e.get("clock_out"):
            rows.append({**base, "marker_type": "clock_out", "latitude": e.get("clock_out_latitude") or e.get("latitude"), "longitude": e.get("clock_out_longitude") or e.get("longitude"), "accuracy": e.get("clock_out_accuracy") or e.get("accuracy"), "address": e.get("clock_out_address") or e.get("address")})
    return rows

@api_router.get("/reports/export/time-entries")
async def export_time_entries_csv(
    worker_id: Optional[str] = None,
    job_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    worker_division: Optional[str] = None,
    job_division: Optional[str] = None,
    worker_type: Optional[str] = None,
    current_admin: dict = Depends(get_current_admin),
):
    entries = await report_time_entries(worker_id, job_id, start_date, end_date, worker_division, job_division, worker_type, current_admin)
    output = StringIO()
    headers = ["Date", "Worker", "Worker Division", "Job", "Job Division", "Type", "Clock In", "Clock Out", "Hours", "Rate", "Cost", "Flags"]
    output.write(",".join(headers) + "\n")
    for e in entries:
        flags = "; ".join(e.get("suspicious_flags") or []) or "OK"
        row = [
            (parse_datetime(e.get("clock_in")) or datetime.min).strftime("%d/%m/%Y"),
            e.get("worker_name", ""), e.get("worker_division", ""), e.get("job_name", ""), e.get("job_division", ""), e.get("worker_type", ""),
            (parse_datetime(e.get("clock_in")) or datetime.min).strftime("%H:%M") if e.get("clock_in") else "",
            (parse_datetime(e.get("clock_out")) or datetime.min).strftime("%H:%M") if e.get("clock_out") else "",
            str(e.get("duration_hours", 0)), str(e.get("hourly_rate", 0)), str(e.get("cost", 0)), flags,
        ]
        output.write(",".join('"' + str(x).replace('"', '""') + '"' for x in row) + "\n")
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=LDA_timesheet_export.csv"})

@api_router.get("/reports/export/attendance-alerts")
async def export_attendance_alerts(current_admin: dict = Depends(get_current_admin)):
    entries = await db.time_entries.find({"suspicious_flags": {"$exists": True, "$ne": []}}).sort("clock_in", -1).to_list(5000)
    output = StringIO()
    output.write("Date,Worker,Job,Flags\n")
    for raw in entries:
        e = await enrich_time_entry(raw)
        output.write(f'"{(parse_datetime(e.get("clock_in")) or datetime.min).strftime("%d/%m/%Y")}","{e.get("worker_name", "")}","{e.get("job_name", "")}","{"; ".join(e.get("suspicious_flags") or [])}"\n')
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=LDA_attendance_alerts.csv"})

# ----------------------
# Device unlocks
# ----------------------

@api_router.get("/device-unlock-requests")
async def list_device_unlock_requests(current_admin: dict = Depends(get_current_admin)):
    items = await db.device_unlock_requests.find({}).sort("created_at", -1).to_list(5000)
    return [clean_doc(i) for i in items]

@api_router.post("/device-unlocks")
async def create_device_unlock(payload: Dict[str, Any], current_admin: dict = Depends(get_current_admin)):
    item = dict(payload)
    item.setdefault("id", make_id())
    item.setdefault("created_at", now_uk_naive())
    item.setdefault("created_by", current_admin.get("username"))
    await db.device_unlocks.insert_one(item)
    return clean_doc(item)

# ----------------------
# PDF export
# ----------------------

def _pdf_safe(value, fallback="-"):
    if value is None or value == "":
        return fallback
    return str(value)


def _format_date(value):
    dt = parse_datetime(value)
    return dt.strftime("%d/%m/%Y") if dt else "-"


def _format_time(value):
    dt = parse_datetime(value)
    return dt.strftime("%H:%M") if dt else "-"


def _format_hours(minutes):
    try:
        return f"{float(minutes or 0) / 60:.2f}"
    except Exception:
        return "0.00"


def _format_money(value):
    try:
        return f"£{float(value or 0):,.2f}"
    except Exception:
        return "£0.00"


def _flag_text(entry):
    flags = entry.get("suspicious_flags") or []
    readable = [str(flag).replace("_", " ").title() for flag in flags]
    wd = entry.get("worker_division")
    jd = entry.get("job_division")
    if wd and jd and wd != "-" and jd != "-" and wd != jd:
        readable.append("Cross-Division Labour")
    return ", ".join(readable) if readable else "OK"


def _add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(285 * mm, 10 * mm, f"Page {doc.page}")
    canvas.drawString(12 * mm, 10 * mm, "LDA Group - Timesheet Export")
    canvas.restoreState()

@api_router.get("/reports/export/time-entries-pdf")
async def export_time_entries_pdf(
    worker_id: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    worker_division: Optional[str] = Query(None),
    job_division: Optional[str] = Query(None),
    worker_type: Optional[str] = Query(None),
    current_admin: dict = Depends(get_current_admin),
):
    if not REPORTLAB_AVAILABLE:
        raise HTTPException(status_code=500, detail="reportlab is not installed. Add reportlab==4.2.5 to requirements.txt and redeploy.")

    enriched = await report_time_entries(worker_id, job_id, start_date, end_date, worker_division, job_division, worker_type, current_admin)
    enriched = sorted(enriched, key=lambda x: parse_datetime(x.get("clock_in")) or datetime.min)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("LDATitle", parent=styles["Title"], fontSize=22, alignment=TA_CENTER, textColor=colors.HexColor("#111827"), spaceAfter=8)
    h2 = ParagraphStyle("LDAHeading", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor("#d01f2f"), spaceBefore=8, spaceAfter=6)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, leading=10)

    story = [Paragraph("LDA Group", title_style), Paragraph("Timesheet Export Report", h2)]
    story.append(Paragraph(f"<b>Report Period:</b> {start_date or 'All'} to {end_date or 'All'}", styles["Normal"]))
    story.append(Paragraph(f"<b>Generated On:</b> {now_uk_naive().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 8))

    filter_rows = [["Filter", "Selection"], ["Job Division", job_division or "All"], ["Worker Division", worker_division or "All"], ["Worker Type", worker_type or "Employees + Contractors"], ["Worker", worker_id or "All"], ["Job", job_id or "All"]]
    ft = Table(filter_rows, colWidths=[55*mm, 100*mm])
    ft.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#111827")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d1d5db")), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8)]))
    story.append(ft)
    story.append(Spacer(1, 10))

    division_summary: Dict[str, Dict[str, Any]] = {}
    worker_summary: Dict[str, Dict[str, Any]] = {}
    job_summary: Dict[str, Dict[str, Any]] = {}
    exception_rows = [["Date", "Worker", "Job", "Issue"]]

    for e in enriched:
        jd = e.get("job_division") or "-"
        wn = e.get("worker_name") or "Unknown"
        jn = e.get("job_name") or "Unknown"
        mins = float(e.get("duration_minutes") or 0)
        cost = float(e.get("cost") or 0)
        division_summary.setdefault(jd, {"workers": set(), "shifts": 0, "minutes": 0, "cost": 0})
        division_summary[jd]["workers"].add(wn)
        division_summary[jd]["shifts"] += 1
        division_summary[jd]["minutes"] += mins
        division_summary[jd]["cost"] += cost
        worker_summary.setdefault(wn, {"division": e.get("worker_division") or "-", "shifts": 0, "minutes": 0, "cost": 0})
        worker_summary[wn]["shifts"] += 1
        worker_summary[wn]["minutes"] += mins
        worker_summary[wn]["cost"] += cost
        job_summary.setdefault(jn, {"division": jd, "workers": set(), "minutes": 0, "cost": 0})
        job_summary[jn]["workers"].add(wn)
        job_summary[jn]["minutes"] += mins
        job_summary[jn]["cost"] += cost
        flag = _flag_text(e)
        if flag != "OK":
            exception_rows.append([_format_date(e.get("clock_in")), wn, jn, Paragraph(flag, small)])

    summary_rows = [["Division", "Total Workers", "Total Shifts", "Total Hours", "Labour Cost"]]
    total_workers, total_shifts, total_minutes, total_cost = set(), 0, 0, 0
    for div, data in sorted(division_summary.items()):
        summary_rows.append([div, str(len(data["workers"])), str(data["shifts"]), _format_hours(data["minutes"]), _format_money(data["cost"])])
        total_workers.update(data["workers"]); total_shifts += data["shifts"]; total_minutes += data["minutes"]; total_cost += data["cost"]
    summary_rows.append(["Total", str(len(total_workers)), str(total_shifts), _format_hours(total_minutes), _format_money(total_cost)])
    story.append(Paragraph("Summary", h2))
    st = Table(summary_rows, colWidths=[70*mm, 35*mm, 35*mm, 35*mm, 40*mm])
    st.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#d01f2f")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d1d5db")), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"), ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#f3f4f6")), ("FONTSIZE", (0,0), (-1,-1), 8)]))
    story.append(st)
    story.append(PageBreak())

    story.append(Paragraph("Timesheet Detail", h2))
    detail_rows = [["Date", "Worker", "Worker Division", "Job", "Job Division", "Type", "Clock In", "Clock Out", "Hours", "Rate", "Cost", "Flags"]]
    for e in enriched:
        detail_rows.append([_format_date(e.get("clock_in")), _pdf_safe(e.get("worker_name")), _pdf_safe(e.get("worker_division")), _pdf_safe(e.get("job_name")), _pdf_safe(e.get("job_division")), _pdf_safe(e.get("worker_type")), _format_time(e.get("clock_in")), _format_time(e.get("clock_out")), _format_hours(e.get("duration_minutes")), _format_money(e.get("hourly_rate")), _format_money(e.get("cost")), Paragraph(_flag_text(e), small)])
    dt = Table(detail_rows, repeatRows=1, colWidths=[20*mm, 28*mm, 27*mm, 35*mm, 25*mm, 20*mm, 18*mm, 18*mm, 16*mm, 18*mm, 20*mm, 42*mm])
    dt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#111827")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.2, colors.HexColor("#d1d5db")), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 7), ("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(dt)
    story.append(PageBreak())

    story.append(Paragraph("Worker Summary", h2))
    wr = [["Worker", "Worker Division", "Shifts", "Total Hours", "Total Cost"]] + [[w, d["division"], str(d["shifts"]), _format_hours(d["minutes"]), _format_money(d["cost"])] for w, d in sorted(worker_summary.items())]
    wt = Table(wr, repeatRows=1, colWidths=[70*mm, 55*mm, 25*mm, 35*mm, 40*mm])
    wt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#d01f2f")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d1d5db")), ("FONTSIZE", (0,0), (-1,-1), 8)]))
    story.append(wt)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Job Summary", h2))
    jr = [["Job", "Job Division", "Workers Used", "Total Hours", "Total Cost"]] + [[j, d["division"], str(len(d["workers"])), _format_hours(d["minutes"]), _format_money(d["cost"])] for j, d in sorted(job_summary.items())]
    jt = Table(jr, repeatRows=1, colWidths=[80*mm, 55*mm, 30*mm, 35*mm, 40*mm])
    jt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#111827")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d1d5db")), ("FONTSIZE", (0,0), (-1,-1), 8)]))
    story.append(jt)
    story.append(PageBreak())

    story.append(Paragraph("Exception / Flag Section", h2))
    if len(exception_rows) == 1:
        exception_rows.append(["-", "-", "-", "No exceptions found"])
    et = Table(exception_rows, repeatRows=1, colWidths=[30*mm, 55*mm, 70*mm, 115*mm])
    et.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#d01f2f")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d1d5db")), ("FONTSIZE", (0,0), (-1,-1), 8), ("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(et)
    story.append(Spacer(1, 18))
    story.append(Paragraph("Approval", h2))
    at = Table([["Prepared By", ""], ["Reviewed By", ""], ["Approved By", ""], ["Date", ""]], colWidths=[45*mm, 120*mm], rowHeights=[12*mm]*4)
    at.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#9ca3af")), ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 9), ("VALIGN", (0,0), (-1,-1), "MIDDLE")]))
    story.append(at)

    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
    buffer.seek(0)
    filename = f"LDA_timesheet_{start_date or 'all'}_{end_date or 'all'}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})

app.include_router(api_router)
