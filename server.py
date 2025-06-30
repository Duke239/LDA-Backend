from fastapi import FastAPI, APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
import json
import io
import csv
from decimal import Decimal
import secrets
import pytz


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# UK timezone handling
UK_TZ = pytz.timezone('Europe/London')

def get_uk_time():
    """Get current UK time (handles BST/GMT automatically)"""
    return datetime.now(UK_TZ)

def utc_to_uk(utc_dt):
    """Convert UTC datetime to UK time"""
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = pytz.utc.localize(utc_dt)
    return utc_dt.astimezone(UK_TZ)

def uk_to_utc(uk_dt):
    """Convert UK time to UTC"""
    if uk_dt is None:
        return None
    if uk_dt.tzinfo is None:
        uk_dt = UK_TZ.localize(uk_dt)
    return uk_dt.astimezone(pytz.utc)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(
    mongo_url,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
    socketTimeoutMS=10000,
    maxPoolSize=10,
    tlsInsecure=True  # Allow insecure TLS connections
)
db = client[os.environ.get('DB_NAME', 'lda_timetracking')]

# Security
security = HTTPBasic()

# Admin credentials (in production, store securely)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ldagroup2024"

# Create the main app without a prefix
app = FastAPI(title="LDA Group Time Tracking API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")
@app.api_route("/ping", methods=["GET", "HEAD"])
async def ping():
    print("Ping received")  # or use logging.info("Ping received")
    return {"status": "ok"}

# Define Models
class Worker(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: str
    phone: str
    role: str = "worker"  # worker, admin, supervisor
    hourly_rate: float = 15.0  # Default £15/hour
    password: Optional[str] = None  # For admin users
    active: bool = True
    archived: bool = False
    created_date: datetime = Field(default_factory=datetime.utcnow)

class WorkerCreate(BaseModel):
    name: str
    email: str
    phone: str
    role: str = "worker"
    hourly_rate: float = 15.0
    password: Optional[str] = None

class WorkerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    hourly_rate: Optional[float] = None
    password: Optional[str] = None
    active: Optional[bool] = None
    archived: Optional[bool] = None

class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    location: str
    client: str
    quoted_cost: float
    status: str = "active"  # active, completed, cancelled
    archived: bool = False
    created_date: datetime = Field(default_factory=datetime.utcnow)

class JobCreate(BaseModel):
    name: str
    description: str
    location: str
    client: str
    quoted_cost: float

class JobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    client: Optional[str] = None
    quoted_cost: Optional[float] = None
    status: Optional[str] = None
    archived: Optional[bool] = None

class GPSLocation(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    address: Optional[str] = None  # Human readable address

class TimeEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    worker_id: str
    job_id: str
    clock_in: datetime
    clock_out: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    gps_location_in: Optional[GPSLocation] = None
    gps_location_out: Optional[GPSLocation] = None
    notes: str = ""
    created_date: datetime = Field(default_factory=datetime.utcnow)

class TimeEntryClockIn(BaseModel):
    worker_id: str
    job_id: str
    gps_location: Optional[GPSLocation] = None
    notes: str = ""

class TimeEntryClockOut(BaseModel):
    gps_location: Optional[GPSLocation] = None
    notes: str = ""

class TimeEntryUpdate(BaseModel):
    worker_id: Optional[str] = None
    job_id: Optional[str] = None
    clock_in: Optional[str] = None
    clock_out: Optional[str] = None
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None

class Material(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    name: str
    cost: float
    quantity: int
    supplier: str = ""  # Supplier name
    reference: str = ""  # Receipt number or reference
    purchase_date: datetime = Field(default_factory=datetime.utcnow)
    notes: str = ""
    created_date: datetime = Field(default_factory=datetime.utcnow)

class MaterialCreate(BaseModel):
    job_id: str
    name: str
    cost: float
    quantity: int
    supplier: str = ""
    reference: str = ""
    notes: str = ""

class MaterialUpdate(BaseModel):
    name: Optional[str] = None
    cost: Optional[float] = None
    quantity: Optional[int] = None
    supplier: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None

class AdminLogin(BaseModel):
    username: str
    password: str

class WorkerLogin(BaseModel):
    worker_id: str
    password: Optional[str] = None  # For admin workers

# Security functions
async def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials"""
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    
    if is_correct_username and is_correct_password:
        return credentials.username
    
    # Check if it's an admin user in the database
    try:
        admin_user = await db.workers.find_one({
            "email": credentials.username,
            "role": "admin",
            "password": credentials.password,
            "active": True,
            "archived": {"$ne": True}
        })
        
        if admin_user:
            return credentials.username
    except Exception as e:
        print(f"Error checking admin user: {e}")
    
    raise HTTPException(
        status_code=401,
        detail="Invalid admin credentials",
        headers={"WWW-Authenticate": "Basic"},
    )

# Helper functions
def calculate_duration(clock_in: datetime, clock_out: datetime) -> int:
    """Calculate duration in minutes between two datetime objects"""
    delta = clock_out - clock_in
    return int(delta.total_seconds() / 60)

# AUTHENTICATION ENDPOINTS
@api_router.post("/admin/login")
async def admin_login(login_data: AdminLogin):
    """Admin login endpoint"""
    if login_data.username == ADMIN_USERNAME and login_data.password == ADMIN_PASSWORD:
        return {"success": True, "message": "Admin login successful"}
    
    # Check if it's an admin user in the database
    admin_user = await db.workers.find_one({
        "email": login_data.username,
        "role": "admin", 
        "password": login_data.password,
        "active": True,
        "archived": {"$ne": True}
    })
    
    if admin_user:
        return {"success": True, "message": "Admin login successful"}
    
    raise HTTPException(status_code=401, detail="Invalid admin credentials")

# WORKER ENDPOINTS
@api_router.post("/workers", response_model=Worker)
async def create_worker(worker: WorkerCreate, admin: str = Depends(verify_admin)):
    """Create a new worker (Admin only)"""
    worker_dict = worker.dict()
    worker_obj = Worker(**worker_dict)
    await db.workers.insert_one(worker_obj.dict())
    return worker_obj

@api_router.get("/workers", response_model=List[Worker])
async def get_workers(active_only: bool = Query(True), include_archived: bool = Query(False)):
    filter_dict = {"active": True} if active_only else {}
    if not include_archived:
        filter_dict["archived"] = {"$ne": True}
    workers = await db.workers.find(filter_dict).to_list(1000)
    return [Worker(**worker) for worker in workers]

@api_router.get("/workers/{worker_id}", response_model=Worker)
async def get_worker(worker_id: str):
    worker = await db.workers.find_one({"id": worker_id})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return Worker(**worker)

@api_router.put("/workers/{worker_id}", response_model=Worker)
async def update_worker(worker_id: str, worker_update: WorkerUpdate, admin: str = Depends(verify_admin)):
    """Update worker (Admin only)"""
    update_dict = {k: v for k, v in worker_update.dict().items() if v is not None}
    
    result = await db.workers.update_one({"id": worker_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    updated_worker = await db.workers.find_one({"id": worker_id})
    return Worker(**updated_worker)

@api_router.delete("/workers/{worker_id}")
async def delete_worker(worker_id: str, admin: str = Depends(verify_admin)):
    """Delete worker (Admin only)"""
    result = await db.workers.delete_one({"id": worker_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"message": "Worker deleted successfully"}

@api_router.put("/workers/{worker_id}/archive")
async def archive_worker(worker_id: str, admin: str = Depends(verify_admin)):
    """Archive worker (Admin only)"""
    result = await db.workers.update_one({"id": worker_id}, {"$set": {"archived": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"message": "Worker archived successfully"}

# JOB ENDPOINTS
@api_router.post("/jobs", response_model=Job)
async def create_job(job: JobCreate, admin: str = Depends(verify_admin)):
    """Create a new job (Admin only)"""
    job_dict = job.dict()
    job_obj = Job(**job_dict)
    await db.jobs.insert_one(job_obj.dict())
    return job_obj

@api_router.get("/jobs", response_model=List[Job])
async def get_jobs(active_only: bool = Query(False), include_archived: bool = Query(False)):
    filter_dict = {}
    
    if active_only:
        filter_dict["status"] = {"$ne": "cancelled"}
        filter_dict["archived"] = {"$ne": True}
    elif not include_archived:
        filter_dict["archived"] = {"$ne": True}
        
    jobs = await db.jobs.find(filter_dict).to_list(1000)
    return [Job(**job) for job in jobs]

@api_router.get("/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str):
    job = await db.jobs.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return Job(**job)

@api_router.put("/jobs/{job_id}", response_model=Job)
async def update_job(job_id: str, job_update: JobUpdate, admin: str = Depends(verify_admin)):
    """Update job (Admin only)"""
    update_dict = {k: v for k, v in job_update.dict().items() if v is not None}
    
    result = await db.jobs.update_one({"id": job_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    
    updated_job = await db.jobs.find_one({"id": job_id})
    return Job(**updated_job)

@api_router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, admin: str = Depends(verify_admin)):
    """Delete job (Admin only)"""
    result = await db.jobs.delete_one({"id": job_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "Job deleted successfully"}

@api_router.put("/jobs/{job_id}/archive")
async def archive_job(job_id: str, admin: str = Depends(verify_admin)):
    """Archive job (Admin only)"""
    result = await db.jobs.update_one({"id": job_id}, {"$set": {"archived": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "Job archived successfully"}

@api_router.put("/jobs/{job_id}/unarchive")
async def unarchive_job(job_id: str, admin: str = Depends(verify_admin)):
    """Unarchive job (Admin only)"""
    result = await db.jobs.update_one({"id": job_id}, {"$set": {"archived": False}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "Job unarchived successfully"}

# TIME ENTRY ENDPOINTS
@api_router.post("/time-entries/clock-in", response_model=TimeEntry)
async def clock_in(entry: TimeEntryClockIn):
    # Check if worker has any active (not clocked out) time entries
    active_entry = await db.time_entries.find_one({
        "worker_id": entry.worker_id,
        "clock_out": None
    })
    
    if active_entry:
        raise HTTPException(status_code=400, detail="Worker already clocked in. Must clock out first.")
    
    time_entry_dict = entry.dict()
    time_entry_dict["clock_in"] = datetime.utcnow()
    time_entry_dict["gps_location_in"] = entry.gps_location
    time_entry_dict.pop("gps_location", None)
    
    time_entry_obj = TimeEntry(**time_entry_dict)
    await db.time_entries.insert_one(time_entry_obj.dict())
    return time_entry_obj

@api_router.put("/time-entries/{entry_id}/clock-out", response_model=TimeEntry)
async def clock_out(entry_id: str, clock_out_data: TimeEntryClockOut):
    # Find the active time entry
    time_entry = await db.time_entries.find_one({"id": entry_id, "clock_out": None})
    if not time_entry:
        raise HTTPException(status_code=404, detail="Active time entry not found")
    
    clock_out_time = datetime.utcnow()
    clock_in_time = time_entry["clock_in"]
    duration = calculate_duration(clock_in_time, clock_out_time)
    
    update_dict = {
        "clock_out": clock_out_time,
        "duration_minutes": duration,
        "gps_location_out": clock_out_data.gps_location.dict() if clock_out_data.gps_location else None,
        "notes": clock_out_data.notes
    }
    
    await db.time_entries.update_one({"id": entry_id}, {"$set": update_dict})
    
    updated_entry = await db.time_entries.find_one({"id": entry_id})
    return TimeEntry(**updated_entry)

@api_router.put("/time-entries/{entry_id}", response_model=TimeEntry)
async def update_time_entry(entry_id: str, entry_update: TimeEntryUpdate, admin: str = Depends(verify_admin)):
    """Update time entry (Admin only)"""
    # Find the existing time entry
    existing_entry = await db.time_entries.find_one({"id": entry_id})
    if not existing_entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    
    # Prepare update dictionary
    update_dict = {}
    
    # Update allowed fields
    if entry_update.worker_id:
        update_dict["worker_id"] = entry_update.worker_id
    if entry_update.job_id:
        update_dict["job_id"] = entry_update.job_id
    if entry_update.clock_in:
        update_dict["clock_in"] = datetime.fromisoformat(entry_update.clock_in.replace('Z', '+00:00'))
    if entry_update.clock_out is not None:
        if entry_update.clock_out:
            update_dict["clock_out"] = datetime.fromisoformat(entry_update.clock_out.replace('Z', '+00:00'))
        else:
            update_dict["clock_out"] = None
            update_dict["duration_minutes"] = None
    if entry_update.notes is not None:
        update_dict["notes"] = entry_update.notes
    
    # Recalculate duration if both clock_in and clock_out are present
    if entry_update.duration_minutes is not None:
        update_dict["duration_minutes"] = entry_update.duration_minutes
    elif "clock_in" in update_dict and "clock_out" in update_dict and update_dict["clock_out"]:
        clock_in = update_dict["clock_in"] if "clock_in" in update_dict else existing_entry["clock_in"]
        clock_out = update_dict["clock_out"]
        update_dict["duration_minutes"] = calculate_duration(clock_in, clock_out)
    
    # Update the time entry
    result = await db.time_entries.update_one({"id": entry_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Time entry not found")
    
    # Return updated entry
    updated_entry = await db.time_entries.find_one({"id": entry_id})
    return TimeEntry(**updated_entry)

@api_router.get("/time-entries", response_model=List[TimeEntry])
async def get_time_entries(
    worker_id: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None)
):
    filter_dict = {}
    
    if worker_id:
        filter_dict["worker_id"] = worker_id
    if job_id:
        filter_dict["job_id"] = job_id
    
    if start_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        filter_dict["clock_in"] = {"$gte": start_dt}
    
    if end_date:
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if "clock_in" in filter_dict:
            filter_dict["clock_in"]["$lte"] = end_dt
        else:
            filter_dict["clock_in"] = {"$lte": end_dt}
    
    time_entries = await db.time_entries.find(filter_dict).to_list(1000)
    return [TimeEntry(**entry) for entry in time_entries]

@api_router.get("/workers/{worker_id}/active-entry")
async def get_active_time_entry(worker_id: str):
    active_entry = await db.time_entries.find_one({
        "worker_id": worker_id,
        "clock_out": None
    })
    
    if not active_entry:
        return {"active_entry": None}
    
    return {"active_entry": TimeEntry(**active_entry)}

# MATERIAL ENDPOINTS
@api_router.post("/materials", response_model=Material)
async def create_material(material: MaterialCreate):
    material_dict = material.dict()
    material_obj = Material(**material_dict)
    await db.materials.insert_one(material_obj.dict())
    return material_obj

@api_router.get("/materials", response_model=List[Material])
async def get_materials(job_id: Optional[str] = Query(None)):
    filter_dict = {"job_id": job_id} if job_id else {}
    materials = await db.materials.find(filter_dict).to_list(1000)
    return [Material(**material) for material in materials]

@api_router.put("/materials/{material_id}", response_model=Material)
async def update_material(material_id: str, material_update: MaterialUpdate, admin: str = Depends(verify_admin)):
    """Update material (Admin only)"""
    update_dict = {k: v for k, v in material_update.dict().items() if v is not None}
    
    result = await db.materials.update_one({"id": material_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    
    updated_material = await db.materials.find_one({"id": material_id})
    return Material(**updated_material)

@api_router.delete("/materials/{material_id}")
async def delete_material(material_id: str, admin: str = Depends(verify_admin)):
    """Delete material (Admin only)"""
    result = await db.materials.delete_one({"id": material_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"message": "Material deleted successfully"}

# REPORTING ENDPOINTS
@api_router.get("/reports/dashboard")
async def get_dashboard_stats(admin: str = Depends(verify_admin)):
    """Get dashboard statistics (Admin only)"""
    # Get basic counts
    total_workers = await db.workers.count_documents({"active": True, "archived": {"$ne": True}})
    total_jobs = await db.jobs.count_documents({"status": {"$ne": "cancelled"}, "archived": {"$ne": True}})
    active_jobs = await db.jobs.count_documents({"status": "active", "archived": {"$ne": True}})
    
    # Get total hours this week
    week_start = datetime.utcnow() - timedelta(days=7)
    week_entries = await db.time_entries.find({
        "clock_in": {"$gte": week_start},
        "duration_minutes": {"$exists": True}
    }).to_list(1000)
    
    total_minutes = sum(entry.get("duration_minutes", 0) or 0 for entry in week_entries)
    total_hours = round(total_minutes / 60, 1)
    
    # Get total materials cost this month
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_materials = await db.materials.find({
        "purchase_date": {"$gte": month_start}
    }).to_list(1000)
    
    total_materials_cost = sum(mat.get("cost", 0) * mat.get("quantity", 1) for mat in month_materials)
    
    # Get attendance alerts (workers who haven't logged in before 9am or out after 5pm) - last 7 days
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    nine_am_threshold = timedelta(hours=9)  # 9 AM
    five_pm_threshold = timedelta(hours=17)  # 5 PM
    
    # Get all non-admin workers
    non_admin_workers = await db.workers.find({
        "role": {"$ne": "admin"},
        "active": True,
        "archived": {"$ne": True}
    }).to_list(1000)
    
    attendance_alerts = []
    
    for worker in non_admin_workers:
        # Check each day for the last 7 days
        for i in range(7):
            day_start = (datetime.utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            nine_am = day_start + nine_am_threshold
            five_pm = day_start + five_pm_threshold
            
            # Skip future dates and today if it's before 9 AM
            if day_start.date() == datetime.utcnow().date() and datetime.utcnow().hour < 9:
                continue
            if day_start.date() > datetime.utcnow().date():
                continue
            
            # Get all time entries for this worker on this day
            day_entries = await db.time_entries.find({
                "worker_id": worker["id"],
                "clock_in": {"$gte": day_start, "$lt": day_end}
            }).to_list(100)
            
            if not day_entries:
                # No entries for this day (only alert if it's a weekday and not today)
                if day_start.weekday() < 5 and day_start.date() != datetime.utcnow().date():  # Monday=0, Friday=4
                    attendance_alerts.append({
                        "worker_id": worker["id"],
                        "worker_name": worker["name"],
                        "type": "no_clock_in",
                        "date": day_start.date(),
                        "time": None,
                        "message": f"No clock in recorded on {day_start.strftime('%A, %d %B %Y')}"
                    })
            else:
                # Check for late clock-ins
                for entry in day_entries:
                    clock_in_time = entry["clock_in"]
                    
                    # Late clock-in (after 9 AM)
                    if clock_in_time > nine_am:
                        attendance_alerts.append({
                            "worker_id": worker["id"],
                            "worker_name": worker["name"],
                            "type": "late_clock_in",
                            "date": day_start.date(),
                            "time": clock_in_time,
                            "message": f"Clocked in late at {clock_in_time.strftime('%H:%M')} on {day_start.strftime('%A, %d %B %Y')}"
                        })
                    
                    # Late clock-out (after 5 PM) - only check if clocked out
                    if entry.get("clock_out") and entry["clock_out"] > five_pm:
                        attendance_alerts.append({
                            "worker_id": worker["id"],
                            "worker_name": worker["name"],
                            "type": "late_clock_out",
                            "date": day_start.date(),
                            "time": entry["clock_out"],
                            "message": f"Clocked out late at {entry['clock_out'].strftime('%H:%M')} on {day_start.strftime('%A, %d %B %Y')}"
                        })
    
    # Sort alerts by date (most recent first)
    attendance_alerts.sort(key=lambda x: x["date"] if x["date"] else datetime.min.date(), reverse=True)
    
    return {
        "total_workers": total_workers,
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "total_hours_this_week": total_hours,
        "total_materials_cost_this_month": total_materials_cost,
        "attendance_alerts": attendance_alerts
    }

@api_router.get("/reports/job-costs/{job_id}")
async def get_job_cost_report(job_id: str, admin: str = Depends(verify_admin)):
    """Get detailed job cost report (Admin only)"""
    # Get job details
    job = await db.jobs.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Get time entries for this job
    time_entries = await db.time_entries.find({
        "job_id": job_id
    }).to_list(1000)
    
    total_minutes = sum((entry.get("duration_minutes", 0) or 0) for entry in time_entries)
    total_hours = round(total_minutes / 60, 1)
    
    # Get materials for this job
    materials = await db.materials.find({"job_id": job_id}).to_list(1000)
    total_materials_cost = sum(mat.get("cost", 0) * mat.get("quantity", 1) for mat in materials)
    
    # Calculate labor cost using worker hourly rates
    labor_cost = 0
    worker_ids = list(set(entry.get("worker_id") for entry in time_entries if entry.get("worker_id")))
    workers = await db.workers.find({"id": {"$in": worker_ids}}).to_list(1000) if worker_ids else []
    worker_rates = {worker["id"]: worker.get("hourly_rate", 15.0) for worker in workers}
    worker_names = {worker["id"]: worker["name"] for worker in workers}
    
    # Calculate labor cost per entry
    for entry in time_entries:
        if entry.get("duration_minutes"):
            worker_rate = worker_rates.get(entry.get("worker_id"), 15.0)
            entry_hours = entry.get("duration_minutes") / 60
            labor_cost += entry_hours * worker_rate
    
    total_cost = labor_cost + total_materials_cost
    quoted_cost = job.get("quoted_cost", 0)
    cost_variance = quoted_cost - total_cost
    
    # Clean time entries data
    clean_time_entries = []
    for entry in time_entries:
        clean_entry = {
            "id": entry.get("id"),
            "worker_id": entry.get("worker_id"),
            "worker_name": worker_names.get(entry.get("worker_id"), "Unknown"),
            "clock_in": entry.get("clock_in"),
            "clock_out": entry.get("clock_out"),
            "duration_minutes": entry.get("duration_minutes"),
            "notes": entry.get("notes", ""),
            "gps_location_in": entry.get("gps_location_in"),
            "gps_location_out": entry.get("gps_location_out"),
            "hourly_rate": worker_rates.get(entry.get("worker_id"), 15.0)
        }
        clean_time_entries.append(clean_entry)
    
    # Clean materials data
    clean_materials = []
    for material in materials:
        clean_material = {
            "id": material.get("id"),
            "name": material.get("name"),
            "cost": material.get("cost"),
            "quantity": material.get("quantity"),
            "supplier": material.get("supplier", ""),
            "reference": material.get("reference", ""),
            "purchase_date": material.get("purchase_date"),
            "notes": material.get("notes", "")
        }
        clean_materials.append(clean_material)
    
    return {
        "job": Job(**job),
        "total_hours": total_hours,
        "labor_cost": labor_cost,
        "materials_cost": total_materials_cost,
        "total_cost": total_cost,
        "quoted_cost": quoted_cost,
        "cost_variance": cost_variance,
        "time_entries": clean_time_entries,
        "materials": clean_materials,
        "time_entries_count": len(time_entries),
        "materials_count": len(materials)
    }

@api_router.get("/reports/export/job/{job_id}")
async def export_job_report(job_id: str, admin: str = Depends(verify_admin)):
    """Export comprehensive job report as CSV (Admin only)"""
    # Get job details
    job = await db.jobs.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Get time entries and materials
    time_entries = await db.time_entries.find({"job_id": job_id}).to_list(1000)
    materials = await db.materials.find({"job_id": job_id}).to_list(1000)
    
    # Get worker names
    worker_ids = list(set(entry.get("worker_id") for entry in time_entries))
    workers = await db.workers.find({"id": {"$in": worker_ids}}).to_list(1000)
    worker_names = {worker["id"]: worker["name"] for worker in workers}
    
    # Calculate totals
    total_minutes = sum((entry.get("duration_minutes", 0) or 0) for entry in time_entries)
    total_hours = round(total_minutes / 60, 1)
    labor_cost = total_hours * 15
    materials_cost = sum(mat.get("cost", 0) * mat.get("quantity", 1) for mat in materials)
    total_cost = labor_cost + materials_cost
    cost_variance = job.get("quoted_cost", 0) - total_cost
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Job summary
    writer.writerow(["JOB REPORT - " + job.get("name", "")])
    writer.writerow(["Client", job.get("client", "")])
    writer.writerow(["Location", job.get("location", "")])
    writer.writerow(["Quoted Cost", f"£{job.get('quoted_cost', 0):,.2f}"])
    writer.writerow(["Actual Cost", f"£{total_cost:,.2f}"])
    writer.writerow(["Variance", f"£{cost_variance:,.2f}"])
    writer.writerow([])
    
    # Time entries
    writer.writerow(["TIME ENTRIES"])
    writer.writerow(["Worker", "Clock In", "Clock Out", "Duration (hours)", "Labor Cost", "Notes"])
    
    for entry in time_entries:
        worker_name = worker_names.get(entry.get("worker_id"), "Unknown")
        clock_in = entry.get("clock_in", "")
        clock_out = entry.get("clock_out", "")
        duration_hours = round(entry.get("duration_minutes", 0) / 60, 2) if entry.get("duration_minutes") else 0
        entry_labor_cost = duration_hours * 15
        
        writer.writerow([
            worker_name,
            clock_in.strftime("%Y-%m-%d %H:%M:%S") if clock_in else "",
            clock_out.strftime("%Y-%m-%d %H:%M:%S") if clock_out else "Active",
            duration_hours,
            f"£{entry_labor_cost:.2f}",
            entry.get("notes", "")
        ])
    
    writer.writerow([])
    writer.writerow(["TOTAL LABOR", "", "", total_hours, f"£{labor_cost:.2f}", ""])
    writer.writerow([])
    
    # Materials
    writer.writerow(["MATERIALS"])
    writer.writerow(["Material", "Quantity", "Unit Cost", "Total Cost", "Purchase Date", "Notes"])
    
    for material in materials:
        total_material_cost = material.get("cost", 0) * material.get("quantity", 1)
        purchase_date = material.get("purchase_date", "")
        
        writer.writerow([
            material.get("name", ""),
            material.get("quantity", 1),
            f"£{material.get('cost', 0):.2f}",
            f"£{total_material_cost:.2f}",
            purchase_date.strftime("%Y-%m-%d") if purchase_date else "",
            material.get("notes", "")
        ])
    
    writer.writerow([])
    writer.writerow(["TOTAL MATERIALS", "", "", f"£{materials_cost:.2f}", "", ""])
    
    output.seek(0)
    
    filename = f"job_report_{job.get('name', 'unknown').replace(' ', '_')}.csv"
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@api_router.get("/reports/export/time-entries")
async def export_time_entries(
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Export time entries as CSV (Admin only)"""
    # Build filter
    filter_dict = {}
    if job_id:
        filter_dict["job_id"] = job_id
    
    if start_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        filter_dict["clock_in"] = {"$gte": start_dt}
    
    if end_date:
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if "clock_in" in filter_dict:
            filter_dict["clock_in"]["$lte"] = end_dt
        else:
            filter_dict["clock_in"] = {"$lte": end_dt}
    
    # Get data
    time_entries = await db.time_entries.find(filter_dict).to_list(1000)
    
    # Get worker and job names with hourly rates
    worker_names = {}
    worker_rates = {}
    job_names = {}
    
    for entry in time_entries:
        if entry["worker_id"] not in worker_names:
            worker = await db.workers.find_one({"id": entry["worker_id"]})
            if worker:
                worker_names[entry["worker_id"]] = worker.get("name", "Unknown")
                worker_rates[entry["worker_id"]] = worker.get("hourly_rate", 15.0)
            else:
                worker_names[entry["worker_id"]] = "Unknown"
                worker_rates[entry["worker_id"]] = 15.0
        
        if entry["job_id"] not in job_names:
            job = await db.jobs.find_one({"id": entry["job_id"]})
            job_names[entry["job_id"]] = job.get("name", "Unknown") if job else "Unknown"
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        "Worker Name", "Job Name", "Clock In", "Clock Out", 
        "Duration (hours)", "Hourly Rate", "Labor Cost", "Notes", 
        "GPS In Lat", "GPS In Lng", "GPS In Address",
        "GPS Out Lat", "GPS Out Lng", "GPS Out Address"
    ])
    
    # Data rows
    for entry in time_entries:
        clock_in = entry.get("clock_in", "")
        clock_out = entry.get("clock_out", "")
        duration_hours = round(entry.get("duration_minutes", 0) / 60, 2) if entry.get("duration_minutes") else ""
        hourly_rate = worker_rates.get(entry["worker_id"], 15.0)
        labor_cost = duration_hours * hourly_rate if duration_hours else 0
        
        # GPS In location
        gps_in_lat = ""
        gps_in_lng = ""
        gps_in_address = ""
        if entry.get("gps_location_in"):
            gps_in_lat = entry["gps_location_in"].get("latitude", "")
            gps_in_lng = entry["gps_location_in"].get("longitude", "")
            gps_in_address = entry["gps_location_in"].get("address", "")
        
        # GPS Out location
        gps_out_lat = ""
        gps_out_lng = ""
        gps_out_address = ""
        if entry.get("gps_location_out"):
            gps_out_lat = entry["gps_location_out"].get("latitude", "")
            gps_out_lng = entry["gps_location_out"].get("longitude", "")
            gps_out_address = entry["gps_location_out"].get("address", "")
        
        writer.writerow([
            worker_names.get(entry["worker_id"], "Unknown"),
            job_names.get(entry["job_id"], "Unknown"),
            clock_in.strftime("%Y-%m-%d %H:%M:%S") if clock_in else "",
            clock_out.strftime("%Y-%m-%d %H:%M:%S") if clock_out else "",
            duration_hours,
            f"£{hourly_rate:.2f}",
            f"£{labor_cost:.2f}",
            entry.get("notes", ""),
            gps_in_lat,
            gps_in_lng,
            gps_in_address,
            gps_out_lat,
            gps_out_lng,
            gps_out_address
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=time_entries.csv"}
    )

@api_router.get("/reports/materials", response_model=List[Dict[str, Any]])
async def get_materials_report(
    worker_id: Optional[str] = Query(None),
    supplier: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Get materials report with filters (Admin only)"""
    # Build filter query
    filter_query = {"archived": {"$ne": True}}
    
    if start_date and end_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        filter_query["purchase_date"] = {"$gte": start_dt, "$lte": end_dt}
    
    if supplier:
        filter_query["supplier"] = {"$regex": supplier, "$options": "i"}
    
    # Get materials
    materials = await db.materials.find(filter_query).to_list(1000)
    
    # Get all jobs and workers for lookup
    jobs = await db.jobs.find().to_list(1000)
    workers = await db.workers.find().to_list(1000)
    
    # Create lookup dictionaries
    job_lookup = {job["id"]: job for job in jobs}
    worker_lookup = {worker["id"]: worker for worker in workers}
    
    # Process materials with additional filters
    result = []
    for material in materials:
        job = job_lookup.get(material["job_id"])
        if not job:
            continue
            
        # Apply additional filters
        if client and client.lower() not in job.get("client", "").lower():
            continue
            
        if job_id and job["id"] != job_id:
            continue
            
        # If worker_id filter is provided, check if any time entries for this job match the worker
        if worker_id:
            job_time_entries = await db.time_entries.find({
                "job_id": material["job_id"],
                "worker_id": worker_id
            }).to_list(100)
            if not job_time_entries:
                continue
        
        # Format the material data for report
        result.append({
            "id": material["id"],
            "date": material["purchase_date"],
            "job_name": job["name"],
            "job_client": job.get("client", ""),
            "material_name": material["name"],
            "supplier": material.get("supplier", ""),
            "reference": material.get("reference", ""),
            "quantity": material["quantity"],
            "cost": material["cost"],
            "total_value": material["cost"] * material["quantity"],
            "notes": material.get("notes", ""),
            "archived": material.get("archived", False)
        })
    
    # Sort by date (most recent first)
    result.sort(key=lambda x: x["date"] if x["date"] else datetime.min, reverse=True)
    
    return result

@api_router.put("/materials/{material_id}", response_model=Dict[str, Any])
async def update_material(material_id: str, material_data: Dict[str, Any], admin: str = Depends(verify_admin)):
    """Update material (Admin only)"""
    # Find the existing material
    existing_material = await db.materials.find_one({"id": material_id})
    if not existing_material:
        raise HTTPException(status_code=404, detail="Material not found")
    
    # Prepare update dictionary
    update_dict = {}
    
    # Update allowed fields
    allowed_fields = ["name", "cost", "quantity", "supplier", "reference", "notes", "purchase_date"]
    for field in allowed_fields:
        if field in material_data:
            if field == "purchase_date" and material_data[field]:
                update_dict[field] = datetime.fromisoformat(material_data[field].replace('Z', '+00:00'))
            else:
                update_dict[field] = material_data[field]
    
    # Update the material
    result = await db.materials.update_one({"id": material_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    
    # Return updated material
    updated_material = await db.materials.find_one({"id": material_id})
    return updated_material

@api_router.delete("/materials/{material_id}")
async def delete_material(material_id: str, admin: str = Depends(verify_admin)):
    """Delete material (Admin only)"""
    result = await db.materials.delete_one({"id": material_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"message": "Material deleted successfully"}

@api_router.put("/materials/{material_id}/archive")
async def archive_material(material_id: str, admin: str = Depends(verify_admin)):
    """Archive material (Admin only)"""
    result = await db.materials.update_one(
        {"id": material_id},
        {"$set": {"archived": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"message": "Material archived successfully"}

@api_router.put("/materials/{material_id}/unarchive")
async def unarchive_material(material_id: str, admin: str = Depends(verify_admin)):
    """Unarchive material (Admin only)"""
    result = await db.materials.update_one(
        {"id": material_id},
        {"$set": {"archived": False}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"message": "Material unarchived successfully"}

@api_router.delete("/time-entries/{entry_id}")
async def delete_time_entry(entry_id: str, admin: str = Depends(verify_admin)):
    """Delete time entry (Admin only)"""
    result = await db.time_entries.delete_one({"id": entry_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return {"message": "Time entry deleted successfully"}

@api_router.put("/time-entries/{entry_id}/archive")
async def archive_time_entry(entry_id: str, admin: str = Depends(verify_admin)):
    """Archive time entry (Admin only)"""
    result = await db.time_entries.update_one(
        {"id": entry_id},
        {"$set": {"archived": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return {"message": "Time entry archived successfully"}

@api_router.get("/reports/export/materials")
async def export_materials_report(
    worker_id: Optional[str] = Query(None),
    supplier: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Export materials report as CSV (Admin only)"""
    # Get the same data as the materials report
    filter_query = {"archived": {"$ne": True}}
    
    if start_date and end_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        filter_query["purchase_date"] = {"$gte": start_dt, "$lte": end_dt}
    
    if supplier:
        filter_query["supplier"] = {"$regex": supplier, "$options": "i"}
    
    materials = await db.materials.find(filter_query).to_list(1000)
    jobs = await db.jobs.find().to_list(1000)
    job_lookup = {job["id"]: job for job in jobs}
    
    # Process materials for export
    export_data = []
    for material in materials:
        job = job_lookup.get(material["job_id"])
        if not job:
            continue
            
        # Apply filters
        if client and client.lower() not in job.get("client", "").lower():
            continue
        if job_id and job["id"] != job_id:
            continue
            
        # Convert to UK time for display
        purchase_date = utc_to_uk(material["purchase_date"]) if material.get("purchase_date") else None
        
        export_data.append({
            "Date": purchase_date.strftime('%Y-%m-%d %H:%M') if purchase_date else "N/A",
            "Job": job["name"],
            "Client": job.get("client", ""),
            "Material": material["name"],
            "Supplier": material.get("supplier", ""),
            "Receipt No": material.get("reference", ""),
            "Quantity": material["quantity"],
            "Unit Cost": f"£{material['cost']:.2f}",
            "Total Value": f"£{material['cost'] * material['quantity']:.2f}",
            "Notes": material.get("notes", "")
        })
    
    # Sort by date
    export_data.sort(key=lambda x: x["Date"], reverse=True)
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        "MATERIALS REPORT",
        f"Generated: {get_uk_time().strftime('%Y-%m-%d %H:%M:%S')} UK Time"
    ])
    writer.writerow([])
    
    if export_data:
        writer.writerow(list(export_data[0].keys()))
        for row in export_data:
            writer.writerow(list(row.values()))
    else:
        writer.writerow(["No materials found for the selected criteria"])
    
    # Summary
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow([])
    total_value = sum(material["cost"] * material["quantity"] for material in materials)
    writer.writerow(["Total Materials", len(export_data)])
    writer.writerow(["Total Value", f"£{total_value:.2f}"])
    
    output.seek(0)
    
    # Generate filename
    filename = f"materials_report_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@api_router.get("/reports/export/attendance-alerts")
async def export_attendance_alerts(admin: str = Depends(verify_admin)):
    """Export attendance alerts for the last 7 days as CSV (Admin only)"""
    
    # Get attendance alerts for the last 7 days (same logic as dashboard)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    nine_am_threshold = timedelta(hours=9)  # 9 AM
    five_pm_threshold = timedelta(hours=17)  # 5 PM
    
    # Get all non-admin workers
    non_admin_workers = await db.workers.find({
        "role": {"$ne": "admin"},
        "active": True,
        "archived": {"$ne": True}
    }).to_list(1000)
    
    attendance_alerts = []
    
    for worker in non_admin_workers:
        # Check each day for the last 7 days
        for i in range(7):
            day_start = (datetime.utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            nine_am = day_start + nine_am_threshold
            five_pm = day_start + five_pm_threshold
            
            # Skip future dates and today if it's before 9 AM
            if day_start.date() == datetime.utcnow().date() and datetime.utcnow().hour < 9:
                continue
            if day_start.date() > datetime.utcnow().date():
                continue
            
            # Get all time entries for this worker on this day
            day_entries = await db.time_entries.find({
                "worker_id": worker["id"],
                "clock_in": {"$gte": day_start, "$lt": day_end}
            }).to_list(100)
            
            if not day_entries:
                # No entries for this day (only alert if it's a weekday and not today)
                if day_start.weekday() < 5 and day_start.date() != datetime.utcnow().date():  # Monday=0, Friday=4
                    attendance_alerts.append({
                        "worker_name": worker["name"],
                        "worker_email": worker.get("email", ""),
                        "type": "No Clock In",
                        "date": day_start.strftime('%Y-%m-%d'),
                        "day_of_week": day_start.strftime('%A'),
                        "time": "N/A",
                        "details": f"No clock in recorded on {day_start.strftime('%A, %d %B %Y')}"
                    })
            else:
                # Check for late clock-ins
                for entry in day_entries:
                    clock_in_time = entry["clock_in"]
                    
                    # Late clock-in (after 9 AM)
                    if clock_in_time > nine_am:
                        # Convert to UK time for display
                        uk_time = utc_to_uk(clock_in_time)
                        attendance_alerts.append({
                            "worker_name": worker["name"],
                            "worker_email": worker.get("email", ""),
                            "type": "Late Clock In",
                            "date": day_start.strftime('%Y-%m-%d'),
                            "day_of_week": day_start.strftime('%A'),
                            "time": uk_time.strftime('%H:%M') if uk_time else "N/A",
                            "details": f"Clocked in late at {uk_time.strftime('%H:%M') if uk_time else 'Unknown'} on {day_start.strftime('%A, %d %B %Y')}"
                        })
                    
                    # Late clock-out (after 5 PM) - only check if clocked out
                    if entry.get("clock_out") and entry["clock_out"] > five_pm:
                        uk_time = utc_to_uk(entry["clock_out"])
                        attendance_alerts.append({
                            "worker_name": worker["name"],
                            "worker_email": worker.get("email", ""),
                            "type": "Late Clock Out",
                            "date": day_start.strftime('%Y-%m-%d'),
                            "day_of_week": day_start.strftime('%A'),
                            "time": uk_time.strftime('%H:%M') if uk_time else "N/A",
                            "details": f"Clocked out late at {uk_time.strftime('%H:%M') if uk_time else 'Unknown'} on {day_start.strftime('%A, %d %B %Y')}"
                        })
    
    # Sort alerts by date (most recent first), then by worker name
    attendance_alerts.sort(key=lambda x: (x["date"], x["worker_name"]), reverse=True)
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        "ATTENDANCE ALERTS - LAST 7 DAYS",
        f"Generated: {get_uk_time().strftime('%Y-%m-%d %H:%M:%S')} UK Time"
    ])
    writer.writerow([])
    writer.writerow([
        "Worker Name", "Worker Email", "Alert Type", "Date", "Day of Week", "Time", "Details"
    ])
    
    # Data rows
    for alert in attendance_alerts:
        writer.writerow([
            alert["worker_name"],
            alert["worker_email"],
            alert["type"],
            alert["date"],
            alert["day_of_week"],
            alert["time"],
            alert["details"]
        ])
    
    # Summary
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow([])
    
    # Count by type
    type_counts = {}
    for alert in attendance_alerts:
        alert_type = alert["type"]
        type_counts[alert_type] = type_counts.get(alert_type, 0) + 1
    
    for alert_type, count in type_counts.items():
        writer.writerow([alert_type, count])
    
    writer.writerow([])
    writer.writerow(["Total Alerts", len(attendance_alerts)])
    
    output.seek(0)
    
    # Generate filename with current date
    filename = f"attendance_alerts_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# Root endpoint
# Root endpoint for the main app (redirects to API)
@app.get("/")
async def root():
    return {
        "message": "LDA Group Time Tracking System", 
        "api_url": "/api/",
        "status": "running",
        "docs": "/docs"
    }

# Handle OPTIONS requests for CORS preflight
@app.options("/{path:path}")
async def options_handler(path: str):
    return {"message": "OK"}

@api_router.get("/")
async def root():
    return {"message": "LDA Group Time Tracking API", "version": "2.0.0"}

# Configure CORS before including routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Include the router in the main app
app.include_router(api_router)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
