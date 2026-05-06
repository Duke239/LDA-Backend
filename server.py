from fastapi import FastAPI, APIRouter, HTTPException, Query, Depends, File, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, date
from decimal import Decimal
import os
import uuid
import json
import io
import csv
import secrets
import pytz
import logging
import hashlib
import base64
import math

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
except Exception:
    service_account = None
    build = None
    MediaIoBaseDownload = None
    MediaIoBaseUpload = None

try:
    from google_drive_service import get_google_drive_service, GoogleDriveService
except Exception as drive_import_error:
    logger = logging.getLogger(__name__)
    logger.warning(f"Google Drive service import failed: {drive_import_error}")
    get_google_drive_service = None
    GoogleDriveService = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
MONGO_URL = os.environ.get('MONGO_URL')
DB_NAME = os.environ.get('DB_NAME', 'lda_timetracking')
PORT = int(os.environ.get('PORT', 8001))

# Google Drive job folder automation settings
GOOGLE_DRIVE_PARENT_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_PARENT_FOLDER_ID', '').strip()
GOOGLE_DRIVE_TEMPLATE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_TEMPLATE_FOLDER_ID', '').strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
GOOGLE_DRIVE_START_JOB_NUMBER = int(os.environ.get('GOOGLE_DRIVE_START_JOB_NUMBER', '34'))
GOOGLE_DRIVE_JOB_NUMBER_PADDING = int(os.environ.get('GOOGLE_DRIVE_JOB_NUMBER_PADDING', '3'))

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


def format_uk_datetime_for_export(value):
    """Format datetimes for CSV exports in UK local time (handles BST/GMT)."""
    if not value:
        return ""

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

    if value.tzinfo is None:
        value = pytz.utc.localize(value)

    return value.astimezone(UK_TZ).strftime("%d/%m/%Y %H:%M")

# MongoDB connection with retry logic
async def get_database():
    """Get database connection with retry logic"""
    try:
        client = AsyncIOMotorClient(
            MONGO_URL,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000,
            maxPoolSize=10,
            retryWrites=True,
            retryReads=True,
            tlsInsecure=True  # Keep this for MongoDB Atlas compatibility
        )

        # Test connection
        await client.admin.command('ping')
        logger.info("MongoDB connection successful")

        return client[DB_NAME]
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise HTTPException(status_code=503, detail="Database connection failed")

# Global database instance
db = None

# Security
security = HTTPBasic()
bearer_scheme = HTTPBearer()

# Admin credentials (in production, store securely)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ldagroup2024"

# Create the main app
app = FastAPI(title="LDA Group Time Tracking API - Production")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/ping")
@app.post("/ping")
@app.head("/ping")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")
# Define Models
class Worker(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: str
    phone: str
    role: str = "worker"  # worker, admin, supervisor
    worker_type: str = "worker"  # worker or contractor
    division: str = ""  # LDA FM, LDA Building Services, LDA Construction, etc.
    trades: List[str] = []  # Multiple trades: Roofer, Plasterer, Plumber, Builder, etc.
    hourly_rate: float = 15.0  # Default £15/hour
    password: Optional[str] = None  # For admin users
    active: bool = True
    archived: bool = False
    gps_exempt: bool = False
    created_date: datetime = Field(default_factory=datetime.utcnow)

class WorkerCreate(BaseModel):
    name: str
    email: str
    phone: str
    role: str = "worker"
    worker_type: str = "worker"
    division: str = ""
    trades: List[str] = []
    hourly_rate: float = 15.0
    gps_exempt: bool = False
    password: Optional[str] = None

class WorkerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    worker_type: Optional[str] = None
    division: Optional[str] = None
    trades: Optional[List[str]] = None
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
    gps_required: bool = False  # If true, location is mandatory for clock in/out
    created_date: datetime = Field(default_factory=datetime.utcnow)
    job_number: Optional[int] = None
    display_name: Optional[str] = None
    include_in_gantt: bool = False
    planned_start_date: Optional[str] = None
    planned_end_date: Optional[str] = None
    gantt_sections: List[Dict[str, Any]] = []
    drive_folder_id: Optional[str] = None
    drive_folder_link: Optional[str] = None
    drive_folder_url: Optional[str] = None
    google_drive_link: Optional[str] = None
    drive_folder_status: Optional[str] = None
    drive_folder_error: Optional[str] = None
    drive_folder_copy_stats: Optional[Dict[str, Any]] = None
    post_work_photos: List[Dict[str, Any]] = []

class JobCreate(BaseModel):
    name: str
    description: str
    location: str
    client: str
    quoted_cost: float
    gps_required: bool = True
    include_in_gantt: bool = False
    planned_start_date: Optional[str] = None
    planned_end_date: Optional[str] = None
    gantt_sections: List[Dict[str, Any]] = []
    drive_folder_id: Optional[str] = None
    drive_folder_link: Optional[str] = None
    drive_folder_url: Optional[str] = None
    google_drive_link: Optional[str] = None
    drive_folder_status: Optional[str] = None

class JobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    client: Optional[str] = None
    quoted_cost: Optional[float] = None
    status: Optional[str] = None
    archived: Optional[bool] = None
    gps_required: Optional[bool] = None
    include_in_gantt: Optional[bool] = None
    planned_start_date: Optional[str] = None
    planned_end_date: Optional[str] = None
    gantt_sections: Optional[List[Dict[str, Any]]] = None
    drive_folder_id: Optional[str] = None
    drive_folder_link: Optional[str] = None
    drive_folder_url: Optional[str] = None
    google_drive_link: Optional[str] = None
    drive_folder_status: Optional[str] = None
    drive_folder_error: Optional[str] = None

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
    device_id_in: Optional[str] = None
    device_id_out: Optional[str] = None
    suspicious_flags: List[str] = []
    notes: str = ""
    created_date: datetime = Field(default_factory=datetime.utcnow)
    worker_name: Optional[str] = None
    job_name: Optional[str] = None
    job_client: Optional[str] = None
    cost: Optional[float] = 0

class TimeEntryClockIn(BaseModel):
    worker_id: str
    job_id: str
    gps_location: Optional[GPSLocation] = None
    device_id: Optional[str] = None
    notes: str = ""

class TimeEntryClockOut(BaseModel):
    gps_location: Optional[GPSLocation] = None
    device_id: Optional[str] = None
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

class ScheduleEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    worker_id: str
    job_id: str
    scheduled_date: str  # YYYY-MM-DD
    notes: str = ""
    status: str = "scheduled"
    created_date: datetime = Field(default_factory=datetime.utcnow)
    updated_date: Optional[datetime] = None

class ScheduleEntryCreate(BaseModel):
    worker_id: str
    job_id: str
    scheduled_date: str  # YYYY-MM-DD
    notes: str = ""
    status: str = "scheduled"

class ScheduleEntryUpdate(BaseModel):
    worker_id: Optional[str] = None
    job_id: Optional[str] = None
    scheduled_date: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None

class GanttPushToScheduleRequest(BaseModel):
    job_id: str
    section_id: str
    worker_ids: List[str]
    start_date: str
    end_date: str
    section_name: str = ""
    replace_existing_for_section: bool = True


class AdminLogin(BaseModel):
    username: str
    password: str

class WorkerLogin(BaseModel):
    worker_id: str
    password: Optional[str] = None  # For admin workers

# Quote System Models
class QuoteMaterial(BaseModel):
    name: str
    description: str = ""
    quantity: int
    unit_price: Decimal
    total_price: Decimal

class QuoteLabor(BaseModel):
    description: str
    estimated_hours: float
    hourly_rate: Decimal
    total_cost: Decimal

class Quote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    quote_number: str
    surveyor_id: str
    surveyor_name: str
    client_name: str
    client_email: str
    client_phone: str = ""
    client_address: str = ""
    job_description: str
    materials: List[QuoteMaterial] = []
    labor: List[QuoteLabor] = []
    total_materials_cost: Decimal = Decimal('0.00')
    total_labor_cost: Decimal = Decimal('0.00')
    total_quote_amount: Decimal = Decimal('0.00')
    vat_rate: Decimal = Decimal('0.20')  # 20% VAT
    vat_amount: Decimal = Decimal('0.00')
    final_amount: Decimal = Decimal('0.00')
    status: str = "draft"  # draft, sent, accepted, declined, expired
    valid_until: date = Field(default_factory=lambda: (datetime.utcnow() + timedelta(days=30)).date())
    photos: List[Dict[str, Any]] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    client_response: Optional[str] = None  # accepted, declined
    client_response_date: Optional[datetime] = None
    client_message: str = ""

class QuoteCreate(BaseModel):
    client_name: str
    client_email: str
    client_phone: str = ""
    client_address: str = ""
    job_description: str
    materials: List[QuoteMaterial] = []
    labor: List[QuoteLabor] = []
    vat_rate: Decimal = Decimal('0.20')

class QuoteUpdate(BaseModel):
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    client_address: Optional[str] = None
    job_description: Optional[str] = None
    materials: Optional[List[QuoteMaterial]] = None
    labor: Optional[List[QuoteLabor]] = None
    vat_rate: Optional[Decimal] = None
    status: Optional[str] = None

class SurveyorCreate(BaseModel):
    name: str
    email: str
    phone: str
    password: str

class SurveyorLogin(BaseModel):
    email: str
    password: str

class ClientResponse(BaseModel):
    response: str  # "accepted" or "declined"
    message: str = ""

# Helper functions for quote services (placeholders)
EmailService = None
QuotePDFGenerator = None

def convert_decimals_to_float(obj):
    """Convert Decimal objects to float and date objects to datetime for MongoDB serialization"""
    if isinstance(obj, dict):
        return {key: convert_decimals_to_float(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(item) for item in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, date) and not isinstance(obj, datetime):
        # Convert date to datetime for MongoDB compatibility
        return datetime.combine(obj, datetime.min.time())
    else:
        return obj

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

# Surveyor authentication functions
def hash_password(password: str) -> str:
    """Hash password for storage"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_surveyor_token(token: str) -> str:
    """Verify surveyor JWT token and return surveyor_id"""
    try:
        decoded = base64.b64decode(token).decode()
        return decoded.split(':')[0]  # Extract surveyor_id
    except:
        raise HTTPException(status_code=401, detail="Invalid surveyor token")

async def get_current_surveyor(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    """Dependency to get current surveyor from token"""
    if not credentials:
        # For testing, allow access without token
        return "test_surveyor_id"

    if credentials.scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")

    return verify_surveyor_token(credentials.credentials)

# Helper functions
def calculate_duration(clock_in: datetime, clock_out: datetime) -> int:
    """Calculate duration in minutes between two datetime objects"""
    delta = clock_out - clock_in
    return int(delta.total_seconds() / 60)


def haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two GPS co-ordinates in metres."""
    radius = 6371000
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def is_gps_exempt_job(job: Dict[str, Any]) -> bool:
    """Jobs like Runner/mobile jobs are allowed to clock anywhere."""
    if not job:
        return False
    if job.get("gps_exempt") or job.get("location_exempt") or job.get("allow_remote_clocking"):
        return True
    searchable = " ".join([str(job.get("name", "")), str(job.get("location", "")), str(job.get("description", ""))]).lower()
    exempt_terms = ["runner", "mobile", "roaming", "anywhere", "various", "multiple sites"]
    return any(term in searchable for term in exempt_terms)

def job_requires_gps(job: Dict[str, Any]) -> bool:
    """Return True only when the job has GPS explicitly required and is not exempt."""
    if not job or is_gps_exempt_job(job):
        return False
    return bool(
        job.get("gps_required") is True
        or job.get("require_gps") is True
        or job.get("requires_gps") is True
        or job.get("location_required") is True
    )

def get_job_coordinates(job: Dict[str, Any]):
    """Return job GPS co-ordinates if the job record has them stored."""
    if not job:
        return None
    pairs = [(job.get("latitude"), job.get("longitude")), (job.get("lat"), job.get("lng")), (job.get("job_latitude"), job.get("job_longitude"))]
    gps = job.get("gps_location") or job.get("location_gps") or {}
    if isinstance(gps, dict):
        pairs.append((gps.get("latitude"), gps.get("longitude")))
        pairs.append((gps.get("lat"), gps.get("lng")))
    for lat, lng in pairs:
        try:
            if lat is not None and lng is not None:
                return float(lat), float(lng)
        except (TypeError, ValueError):
            continue
    return None

async def build_suspicious_flags(worker_id: Optional[str], job_id: Optional[str], device_id: Optional[str], gps_location: Optional[GPSLocation], existing_flags: Optional[List[str]] = None) -> List[str]:
    """Build fraud/protection flags without blocking clock in/out."""
    flags = set(existing_flags or [])

    worker = await db.workers.find_one({"id": worker_id}) if worker_id else None
    if worker and worker.get("gps_exempt", False):
        flags.add("WORKER_GPS_EXEMPT")

    if not gps_location:
        flags.add("MISSING_GPS")
    elif gps_location.accuracy is not None and gps_location.accuracy > 100:
        flags.add("POOR_GPS_ACCURACY")

    if device_id:
        since = datetime.utcnow() - timedelta(days=60)
        shared_device = await db.time_entries.find_one({
            "worker_id": {"$ne": worker_id},
            "clock_in": {"$gte": since},
            "$or": [{"device_id_in": device_id}, {"device_id_out": device_id}],
        })
        if shared_device:
            flags.add("SHARED_DEVICE_MULTIPLE_WORKERS")
    else:
        flags.add("MISSING_DEVICE_ID")

    if gps_location:
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        same_position = await db.time_entries.find_one({
            "worker_id": {"$ne": worker_id},
            "clock_in": {"$gte": day_start, "$lt": day_end},
            "$or": [
                {"gps_location_in.latitude": gps_location.latitude, "gps_location_in.longitude": gps_location.longitude},
                {"gps_location_out.latitude": gps_location.latitude, "gps_location_out.longitude": gps_location.longitude},
            ],
        })
        if same_position:
            flags.add("IDENTICAL_GPS_MULTIPLE_WORKERS")

    if gps_location and job_id:
        job = await db.jobs.find_one({"id": job_id}) or {}
        if not is_gps_exempt_job(job):
            job_coords = get_job_coordinates(job)
            if job_coords:
                distance = haversine_metres(gps_location.latitude, gps_location.longitude, job_coords[0], job_coords[1])
                if distance > 1609:
                    flags.add("FAR_FROM_JOB_LOCATION")

    if worker_id:
        recent_cutoff = datetime.utcnow() - timedelta(minutes=5)
        recent_count = await db.time_entries.count_documents({"worker_id": worker_id, "clock_in": {"$gte": recent_cutoff}})
        if recent_count >= 2:
            flags.add("UNUSUAL_RAPID_CLOCK_ACTIVITY")

    return sorted(flags)

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

# SURVEYOR AUTHENTICATION ENDPOINTS
@api_router.post("/surveyors/register")
async def register_surveyor(surveyor_data: SurveyorCreate):
    """Register a new surveyor"""
    # Check if surveyor already exists
    existing_surveyor = await db.surveyors.find_one({"email": surveyor_data.email})
    if existing_surveyor:
        raise HTTPException(status_code=400, detail="Surveyor already exists")

    # Create new surveyor
    surveyor = {
        "id": str(uuid.uuid4()),
        "name": surveyor_data.name,
        "email": surveyor_data.email,
        "phone": surveyor_data.phone,
        "password": hash_password(surveyor_data.password),
        "created_at": datetime.utcnow(),
        "active": True
    }

    await db.surveyors.insert_one(surveyor)

    # Return surveyor without password
    surveyor.pop("password")
    return surveyor

@api_router.post("/surveyors/login")
async def login_surveyor(login_data: SurveyorLogin):
    """Authenticate surveyor and return token"""
    # Find surveyor
    surveyor = await db.surveyors.find_one({"email": login_data.email})
    if not surveyor or not surveyor.get("active"):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password
    if surveyor["password"] != hash_password(login_data.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Generate token (simple base64 encoding for now)
    token_data = f"{surveyor['id']}:{login_data.email}"
    token = base64.b64encode(token_data.encode()).decode()

    return {
        "token": token,
        "surveyor_id": surveyor["id"],
        "surveyor": {
            "id": surveyor["id"],
            "name": surveyor["name"],
            "email": surveyor["email"],
            "phone": surveyor["phone"]
        }
    }

# QUOTE ENDPOINTS
@api_router.get("/quotes")
async def get_quotes(
    surveyor_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_surveyor_id: str = Depends(get_current_surveyor)
):
    """Get quotes, filtered by surveyor if not admin"""
    filter_query = {}

    # If surveyor_id is provided and it's different from current surveyor, only allow admins
    if surveyor_id and surveyor_id != current_surveyor_id:
        # Check if current user is admin (basic check)
        if current_surveyor_id == "test_surveyor_id":
            # Allow test surveyor to see all quotes
            pass
        else:
            # In production, add proper admin check here
            filter_query["surveyor_id"] = current_surveyor_id
    elif not surveyor_id:
        # If no surveyor_id specified, filter by current surveyor
        filter_query["surveyor_id"] = current_surveyor_id
    else:
        filter_query["surveyor_id"] = surveyor_id

    if status:
        filter_query["status"] = status

    quotes = await db.quotes.find(filter_query).to_list(1000)

    # Remove MongoDB ObjectId fields and handle any serialization issues
    clean_quotes = []
    for quote in quotes:
        # Remove MongoDB ObjectId
        quote.pop("_id", None)

        # Convert any Decimal objects to float
        clean_quote = convert_decimals_to_float(quote)
        clean_quotes.append(clean_quote)

    return clean_quotes

@api_router.post("/quotes")
async def create_quote(
    quote_data: QuoteCreate,
    surveyor_id: str = Depends(get_current_surveyor)
):
    """Create a new quote"""
    # Get surveyor info
    surveyor = await db.surveyors.find_one({"id": surveyor_id})
    if not surveyor:
        raise HTTPException(status_code=404, detail="Surveyor not found")

    # Generate quote number
    quote_number = f"Q-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

    # Calculate totals
    total_materials = sum(item.total_price for item in quote_data.materials)
    total_labor = sum(item.total_cost for item in quote_data.labor)
    subtotal = total_materials + total_labor
    vat_amount = subtotal * quote_data.vat_rate
    final_amount = subtotal + vat_amount

    # Create quote
    quote = Quote(
        quote_number=quote_number,
        surveyor_id=surveyor_id,
        surveyor_name=surveyor["name"],
        total_materials_cost=total_materials,
        total_labor_cost=total_labor,
        total_quote_amount=subtotal,
        vat_amount=vat_amount,
        final_amount=final_amount,
        **quote_data.dict()
    )

    # Convert to dict for MongoDB and handle Decimal serialization
    quote_dict = quote.dict()
    quote_dict["created_at"] = datetime.utcnow()

    # Convert Decimal objects to float for MongoDB
    quote_dict = convert_decimals_to_float(quote_dict)

    # Insert into MongoDB
    result = await db.quotes.insert_one(quote_dict)

    # Return the quote without the MongoDB ObjectId
    quote_dict.pop("_id", None)  # Remove _id if it exists
    return quote_dict

@api_router.get("/quotes/{quote_id}")
async def get_quote(quote_id: str):
    """Get a specific quote"""
    quote = await db.quotes.find_one({"id": quote_id})
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    
    # Remove MongoDB ObjectId and convert Decimals
    quote.pop("_id", None)
    return convert_decimals_to_float(quote)

@api_router.put("/quotes/{quote_id}")
async def update_quote(
    quote_id: str,
    quote_update: QuoteUpdate,
    surveyor_id: str = Depends(get_current_surveyor)
):
    """Update a quote"""
    # Check if quote exists and belongs to surveyor
    existing_quote = await db.quotes.find_one({"id": quote_id})
    if not existing_quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    # For non-admin users, verify ownership
    if existing_quote["surveyor_id"] != surveyor_id:
        # Check if user is admin
        try:
            verify_admin(None)  # This will fail if not admin
        except:
            raise HTTPException(status_code=403, detail="Not authorized to update this quote")

    # Update quote
    update_dict = {k: v for k, v in quote_update.dict().items() if v is not None}
    update_dict["updated_at"] = datetime.utcnow()

    # Convert decimals for MongoDB storage
    update_dict = convert_decimals_to_float(update_dict)

    result = await db.quotes.update_one({"id": quote_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Quote not found")

    # Return updated quote
    updated_quote = await db.quotes.find_one({"id": quote_id})
    updated_quote.pop("_id", None)
    return convert_decimals_to_float(updated_quote)

# WORKER ENDPOINTS
@api_router.post("/workers", response_model=Worker)
async def create_worker(worker: WorkerCreate, admin: str = Depends(verify_admin)):
    """Create a new worker (Admin only)"""
    worker_dict = worker.dict()
    if worker_dict.get("role") == "contractor":
        worker_dict["role"] = "worker"
        worker_dict["worker_type"] = "contractor"
    elif worker_dict.get("role") == "worker":
        worker_dict.setdefault("worker_type", "worker")
    worker_obj = Worker(**worker_dict)
    await db.workers.insert_one(worker_obj.dict())
    return worker_obj

@api_router.get("/workers", response_model=List[Worker])
async def get_workers(
    active_only: bool = Query(True),
    include_archived: bool = Query(False),
    worker_type: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    include_admins: bool = Query(True)
):
    filter_dict = {"active": True} if active_only else {}

    if not include_archived:
        filter_dict["archived"] = {"$ne": True}

    if worker_type and worker_type != "all":
        filter_dict["worker_type"] = worker_type

    if division and division != "all":
        filter_dict["division"] = division

    if trade and trade != "all":
        filter_dict["$or"] = [{"trades": trade}, {"trade": trade}]

    if not include_admins:
        filter_dict["role"] = {"$ne": "admin"}

    workers = await db.workers.find(filter_dict).to_list(1000)

    # Backfill defaults for older workers that were created before these fields existed.
    for worker in workers:
        if worker.get("role") == "contractor":
            worker["role"] = "worker"
            worker["worker_type"] = "contractor"
        worker.setdefault("worker_type", "worker")
        worker.setdefault("division", "")
        worker.setdefault("gps_exempt", False)
        if "trades" not in worker:
            old_trade = worker.get("trade", "")
            worker["trades"] = [item.strip() for item in old_trade.split(",") if item.strip()] if old_trade else []

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
    if update_dict.get("role") == "contractor":
        update_dict["role"] = "worker"
        update_dict["worker_type"] = "contractor"
    elif update_dict.get("role") == "worker" and update_dict.get("worker_type") is None:
        update_dict["worker_type"] = "worker"

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

# ==================== GOOGLE DRIVE JOB FOLDER AUTOMATION ====================

def google_drive_config_missing() -> List[str]:
    """Return missing Google Drive env variable names without exposing secret values."""
    missing = []
    if not GOOGLE_DRIVE_PARENT_FOLDER_ID:
        missing.append("GOOGLE_DRIVE_PARENT_FOLDER_ID")
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    return missing


def get_google_drive_api_service():
    """Build a Google Drive API client from the service account JSON in Render env vars."""
    missing = google_drive_config_missing()
    if missing:
        logger.warning("Google Drive automation not configured. Missing: %s", ", ".join(missing))
        return None
    if service_account is None or build is None:
        logger.error("Google Drive API packages are not installed. Check requirements.txt")
        return None

    try:
        account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            account_info,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except Exception as exc:
        logger.exception("Failed to initialise Google Drive API service: %s", exc)
        return None


def drive_safe_name(value: str) -> str:
    """Keep folder names readable while removing characters Drive/Windows dislike."""
    value = (value or "Untitled Job").strip()
    for char in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        value = value.replace(char, '-')
    return " ".join(value.split()) or "Untitled Job"


async def get_next_job_number() -> int:
    """Find the next job number using existing job_number values in MongoDB."""
    latest = await db.jobs.find_one(
        {"job_number": {"$exists": True, "$ne": None}},
        sort=[("job_number", -1)]
    )
    if latest and isinstance(latest.get("job_number"), int):
        return latest["job_number"] + 1
    return GOOGLE_DRIVE_START_JOB_NUMBER


def build_job_display_name(job_number: int, job_name: str) -> str:
    padded = str(job_number).zfill(GOOGLE_DRIVE_JOB_NUMBER_PADDING)
    return f"{padded}: {drive_safe_name(job_name)}"


def create_drive_folder(service, name: str, parent_id: str) -> Dict[str, Any]:
    """Create one folder in Drive and return id/webViewLink."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    return service.files().create(
        body=metadata,
        fields="id,name,webViewLink",
        supportsAllDrives=True,
    ).execute()


def list_drive_folder_children(service, folder_id: str) -> List[Dict[str, Any]]:
    """List all non-trashed children of a Drive folder, including shared drives."""
    children = []
    page_token = None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id,name,mimeType,shortcutDetails,exportLinks)",
            pageSize=1000,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        children.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    children.sort(key=lambda item: item.get("name", "").lower())
    return children


def copy_drive_file_with_download_fallback(
    service,
    item_id: str,
    item_name: str,
    destination_folder_id: str,
    mime_type: str,
) -> None:
    """Copy one Drive file. If Drive copy is blocked for a binary file, download and re-upload it."""
    metadata = {"name": item_name, "parents": [destination_folder_id]}

    try:
        service.files().copy(
            fileId=item_id,
            body=metadata,
            fields="id,name",
            supportsAllDrives=True,
        ).execute()
        return
    except Exception as copy_exc:
        # Google Docs/Sheets/Slides must use files.copy. Binary files can be downloaded and re-uploaded.
        if mime_type.startswith("application/vnd.google-apps"):
            raise copy_exc
        if MediaIoBaseDownload is None or MediaIoBaseUpload is None:
            raise copy_exc

        logger.warning("Drive files.copy failed for %s; trying download/upload fallback: %s", item_name, copy_exc)
        buffer = io.BytesIO()
        request = service.files().get_media(fileId=item_id, supportsAllDrives=True)
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)

        media = MediaIoBaseUpload(buffer, mimetype=mime_type or "application/octet-stream", resumable=False)
        service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name",
            supportsAllDrives=True,
        ).execute()


def copy_drive_template_contents_recursive(
    service,
    source_folder_id: str,
    destination_folder_id: str,
    current_path: str = "template",
    stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recursively copy every folder/file from the template folder into the new job folder."""
    if stats is None:
        stats = {
            "folders_created": 0,
            "files_copied": 0,
            "shortcuts_created": 0,
            "skipped": [],
            "paths_seen": [],
        }

    children = list_drive_folder_children(service, source_folder_id)
    logger.info("Copying %s Drive item(s) from %s", len(children), current_path)

    for item in children:
        item_id = item.get("id")
        item_name = item.get("name", "Untitled")
        mime_type = item.get("mimeType", "")
        item_path = f"{current_path}/{item_name}"
        stats["paths_seen"].append(item_path)

        try:
            if mime_type == "application/vnd.google-apps.folder":
                new_folder = create_drive_folder(service, item_name, destination_folder_id)
                stats["folders_created"] += 1
                copy_drive_template_contents_recursive(
                    service,
                    item_id,
                    new_folder["id"],
                    current_path=item_path,
                    stats=stats,
                )
            elif mime_type == "application/vnd.google-apps.shortcut":
                shortcut_details = item.get("shortcutDetails") or {}
                target_id = shortcut_details.get("targetId")
                target_mime_type = shortcut_details.get("targetMimeType")
                if not target_id:
                    raise ValueError("Shortcut has no targetId")
                metadata = {
                    "name": item_name,
                    "mimeType": "application/vnd.google-apps.shortcut",
                    "parents": [destination_folder_id],
                    "shortcutDetails": {"targetId": target_id},
                }
                if target_mime_type:
                    metadata["shortcutDetails"]["targetMimeType"] = target_mime_type
                service.files().create(
                    body=metadata,
                    fields="id,name",
                    supportsAllDrives=True,
                ).execute()
                stats["shortcuts_created"] += 1
            else:
                copy_drive_file_with_download_fallback(
                    service,
                    item_id=item_id,
                    item_name=item_name,
                    destination_folder_id=destination_folder_id,
                    mime_type=mime_type,
                )
                stats["files_copied"] += 1
        except Exception as exc:
            error_message = f"{item_path}: {exc}"
            stats["skipped"].append(error_message)
            logger.warning("Skipped Drive template item during recursive copy: %s", error_message)

    return stats


async def create_google_drive_job_folder(job_number: int, job_name: str) -> Dict[str, Any]:
    """Create the new numbered job folder and recursively copy the template into it."""
    missing = google_drive_config_missing()
    if missing:
        return {
            "drive_folder_status": "not_configured",
            "drive_folder_error": "Missing env var(s): " + ", ".join(missing),
        }

    service = get_google_drive_api_service()
    if not service:
        return {
            "drive_folder_status": "failed",
            "drive_folder_error": "Google Drive API service could not be initialised. Check Render env vars and requirements.txt.",
        }

    display_name = build_job_display_name(job_number, job_name)
    try:
        folder = create_drive_folder(service, display_name, GOOGLE_DRIVE_PARENT_FOLDER_ID)
        result = {
            "drive_folder_status": "created",
            "drive_folder_id": folder.get("id"),
            "drive_folder_link": folder.get("webViewLink"),
            "drive_folder_url": folder.get("webViewLink"),
            "google_drive_link": folder.get("webViewLink"),
        }

        if GOOGLE_DRIVE_TEMPLATE_FOLDER_ID:
            stats = copy_drive_template_contents_recursive(
                service,
                GOOGLE_DRIVE_TEMPLATE_FOLDER_ID,
                folder["id"],
                current_path="template",
            )
            result["drive_folder_copy_stats"] = stats
            if stats.get("skipped"):
                result["drive_folder_status"] = "created_with_copy_warnings"
                result["drive_folder_error"] = "; ".join(stats.get("skipped", [])[:5])
            logger.info("Google Drive template copy complete for %s: %s", display_name, stats)
        else:
            result["drive_folder_error"] = "No GOOGLE_DRIVE_TEMPLATE_FOLDER_ID set, so only the main job folder was created."

        return result
    except Exception as exc:
        logger.exception("Google Drive job folder creation failed for %s: %s", display_name, exc)
        return {
            "drive_folder_status": "failed",
            "drive_folder_error": str(exc),
        }


# JOB ENDPOINTS
@api_router.post("/jobs", response_model=Job)
async def create_job(job: JobCreate, admin: str = Depends(verify_admin)):
    """Create a new job, assign a job number, and create/copy its Google Drive folder."""
    job_dict = job.dict()

    job_number = await get_next_job_number()
    display_name = build_job_display_name(job_number, job.name)

    job_dict["job_number"] = job_number
    job_dict["display_name"] = display_name

    drive_result = await create_google_drive_job_folder(job_number, job.name)
    for key in [
        "drive_folder_id",
        "drive_folder_link",
        "drive_folder_url",
        "google_drive_link",
        "drive_folder_status",
        "drive_folder_error",
        "drive_folder_copy_stats",
    ]:
        if key in drive_result:
            job_dict[key] = drive_result[key]

    job_obj = Job(**job_dict)
    mongo_doc = job_obj.dict()
    await db.jobs.insert_one(mongo_doc)
    return job_obj

@api_router.get("/jobs", response_model=List[Job])
async def get_jobs(active_only: bool = Query(False), include_archived: bool = Query(False)):
    filter_dict = {}

    if active_only:
        filter_dict["status"] = {"$ne": "cancelled"}
        filter_dict["archived"] = {"$ne": True}
    elif not include_archived:
        filter_dict["archived"] = {"$ne": True}

    jobs = await db.jobs.find(filter_dict).sort("name", 1).to_list(1000)
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


def get_job_drive_folder_id(job: Dict[str, Any]) -> Optional[str]:
    """Return the Google Drive folder ID stored against a job."""
    if not job:
        return None

    possible_values = [
        job.get("drive_folder_id"),
        job.get("drive_folder_link"),
        job.get("drive_folder_url"),
        job.get("google_drive_link"),
    ]

    for value in possible_values:
        if not value:
            continue
        if GoogleDriveService and hasattr(GoogleDriveService, "extract_folder_id"):
            folder_id = GoogleDriveService.extract_folder_id(value)
        else:
            folder_id = str(value).strip()
        if folder_id:
            return folder_id
    return None


@api_router.post("/jobs/{job_id}/post-work-photos")
async def upload_job_post_work_photos(
    job_id: str,
    files: List[UploadFile] = File(...),
    worker_id: Optional[str] = Query(None),
):
    """Upload worker post-works photos into the job Google Drive folder.

    Target folder inside the job folder:
    007: Site Deliverables / 04: Site Images Pre & Post / 02: Post Works Images
    """
    job = await db.jobs.find_one({"id": job_id, "archived": {"$ne": True}})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not files:
        raise HTTPException(status_code=400, detail="Please select at least one photo")

    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 photos can be uploaded at once")

    job_folder_id = get_job_drive_folder_id(job)
    if not job_folder_id:
        raise HTTPException(
            status_code=400,
            detail="This job does not have a Google Drive folder link/id saved against it yet",
        )

    if not get_google_drive_service:
        raise HTTPException(status_code=500, detail="Google Drive service is not configured on the backend")

    drive_service = get_google_drive_service()
    if not drive_service:
        raise HTTPException(status_code=500, detail="Google Drive service could not be initialised")

    worker = None
    if worker_id:
        worker = await db.workers.find_one({"id": worker_id})

    uploaded_photos = []
    errors = []

    for file in files:
        try:
            if not file.content_type or not file.content_type.startswith("image/"):
                errors.append({"filename": file.filename, "error": "Only image files are allowed"})
                continue

            content = await file.read()
            if len(content) > 15 * 1024 * 1024:
                errors.append({"filename": file.filename, "error": "Photo is larger than 15MB"})
                continue

            uploaded = drive_service.upload_post_work_image(
                job_folder_id=job_folder_id,
                file_content=content,
                filename=file.filename,
                content_type=file.content_type,
                worker_name=(worker or {}).get("name", ""),
                job_name=job.get("name", ""),
            )

            photo_record = {
                "id": str(uuid.uuid4()),
                "job_id": job_id,
                "job_name": job.get("name", ""),
                "worker_id": worker_id,
                "worker_name": (worker or {}).get("name", ""),
                "original_filename": file.filename,
                "file_id": uploaded.get("file_id"),
                "filename": uploaded.get("filename"),
                "mime_type": uploaded.get("mime_type"),
                "share_url": uploaded.get("share_url"),
                "direct_url": uploaded.get("direct_url", ""),
                "folder_id": uploaded.get("folder_id"),
                "folder_name": uploaded.get("folder_name"),
                "folder_link": uploaded.get("folder_link"),
                "category": "post_works",
                "uploaded_at": datetime.utcnow(),
            }
            uploaded_photos.append(photo_record)

        except Exception as exc:
            logger.error(f"Error uploading post work photo {file.filename}: {exc}")
            errors.append({"filename": file.filename, "error": str(exc)})

    if not uploaded_photos and errors:
        raise HTTPException(status_code=500, detail={"message": "No photos were uploaded", "errors": errors})

    if uploaded_photos:
        await db.job_photo_uploads.insert_many(uploaded_photos)
        await db.jobs.update_one(
            {"id": job_id},
            {
                "$push": {"post_work_photos": {"$each": uploaded_photos}},
                "$set": {"updated_date": datetime.utcnow()},
            },
        )

    return {
        "message": f"Successfully uploaded {len(uploaded_photos)} photo(s)",
        "photos": uploaded_photos,
        "errors": errors,
    }
# TIME ENTRY ENDPOINTS
@api_router.post("/time-entries/clock-in", response_model=TimeEntry)
async def clock_in(entry: TimeEntryClockIn):
    """Clock a worker into a job. GPS is mandatory only when the job has gps_required=true."""
    worker = await db.workers.find_one({"id": entry.worker_id, "active": True, "archived": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found or inactive")

    job = await db.jobs.find_one({"id": entry.job_id, "archived": {"$ne": True}})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_requires_gps(job) and not worker.get("gps_exempt", False) and entry.gps_location is None:
        raise HTTPException(
            status_code=400,
            detail="Location is required for this job. Please allow location access and try again."
        )

    active_entry = await db.time_entries.find_one({
        "worker_id": entry.worker_id,
        "clock_out": None
    })

    if active_entry:
        raise HTTPException(status_code=400, detail="Worker already clocked in. Must clock out first.")

    time_entry_dict = entry.dict()
    time_entry_dict["clock_in"] = datetime.utcnow()
    time_entry_dict["gps_location_in"] = entry.gps_location.dict() if entry.gps_location else None
    time_entry_dict["device_id_in"] = entry.device_id
    time_entry_dict["suspicious_flags"] = await build_suspicious_flags(entry.worker_id, entry.job_id, entry.device_id, entry.gps_location)
    time_entry_dict.pop("gps_location", None)
    time_entry_dict.pop("device_id", None)

    time_entry_obj = TimeEntry(**time_entry_dict)
    await db.time_entries.insert_one(time_entry_obj.dict())
    return time_entry_obj

@api_router.get("/time-entries")
async def get_time_entries(
    worker_id: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None)
):
    """Return time entries, enriched defensively so missing worker/job records do not crash the app."""
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

    entries = await db.time_entries.find(filter_dict, {"_id": 0}).sort("clock_in", -1).to_list(1000)
    workers = await db.workers.find({}, {"_id": 0}).to_list(1000)
    jobs = await db.jobs.find({}, {"_id": 0}).to_list(1000)

    worker_lookup = {w.get("id"): w for w in workers if w.get("id")}
    job_lookup = {j.get("id"): j for j in jobs if j.get("id")}

    result = []
    for entry_doc in entries:
        worker = worker_lookup.get(entry_doc.get("worker_id"), {})
        job = job_lookup.get(entry_doc.get("job_id"), {})

        if entry_doc.get("clock_in"):
            entry_doc["clock_in"] = utc_to_uk(entry_doc["clock_in"])
        if entry_doc.get("clock_out"):
            entry_doc["clock_out"] = utc_to_uk(entry_doc["clock_out"])

        duration_hours = (entry_doc.get("duration_minutes", 0) or 0) / 60
        hourly_rate = worker.get("hourly_rate", 15.0) or 15.0

        result.append({
            **entry_doc,
            "worker_name": worker.get("name", "Unknown Worker"),
            "worker_type": worker.get("worker_type") or worker.get("role") or "worker",
            "job_name": job.get("name", "Unknown Job"),
            "job_client": job.get("client", ""),
            "job_location": job.get("location", ""),
            "cost": round(duration_hours * hourly_rate, 2),
        })

    return result

@api_router.put("/time-entries/{entry_id}/clock-out", response_model=TimeEntry)
async def clock_out(entry_id: str, clock_out_data: TimeEntryClockOut):
    # Find the active time entry
    time_entry = await db.time_entries.find_one({"id": entry_id, "clock_out": None})
    if not time_entry:
        raise HTTPException(status_code=404, detail="Active time entry not found")

    job = await db.jobs.find_one({"id": time_entry.get("job_id"), "archived": {"$ne": True}}) or {}
    worker = await db.workers.find_one({"id": time_entry.get("worker_id")}) or {}
    if job_requires_gps(job) and not worker.get("gps_exempt", False) and clock_out_data.gps_location is None:
        raise HTTPException(
            status_code=400,
            detail="Location is required to clock out for this job. Please allow location access and try again."
        )

    clock_out_time = datetime.utcnow()
    clock_in_time = time_entry["clock_in"]
    duration = calculate_duration(clock_in_time, clock_out_time)

    update_dict = {
        "clock_out": clock_out_time,
        "duration_minutes": duration,
        "gps_location_out": clock_out_data.gps_location.dict() if clock_out_data.gps_location else None,
        "device_id_out": clock_out_data.device_id,
        "suspicious_flags": await build_suspicious_flags(
            time_entry.get("worker_id"),
            time_entry.get("job_id"),
            clock_out_data.device_id,
            clock_out_data.gps_location,
            time_entry.get("suspicious_flags", [])
        ),
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
@api_router.get("/reports/time-entries", response_model=List[Dict[str, Any]])
async def get_time_entries_report(
    worker_id: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Get time entries report with filters (Admin only)"""
    # Build filter query
    filter_query = {"archived": {"$ne": True}}

    if worker_id:
        filter_query["worker_id"] = worker_id
    if job_id:
        filter_query["job_id"] = job_id

    if start_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        filter_query["clock_in"] = {"$gte": start_dt}

    if end_date:
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if "clock_in" in filter_query:
            filter_query["clock_in"]["$lte"] = end_dt
        else:
            filter_query["clock_in"] = {"$lte": end_dt}

    # Get time entries
    time_entries = await db.time_entries.find(filter_query).to_list(1000)

    # Get all jobs and workers for lookup
    jobs = await db.jobs.find().to_list(1000)
    workers = await db.workers.find().to_list(1000)

    # Create lookup dictionaries
    job_lookup = {job["id"]: job for job in jobs if "id" in job}
    worker_lookup = {worker["id"]: worker for worker in workers if "id" in worker}

    # Process time entries for report
    result = []
    for entry in time_entries:
        worker = worker_lookup.get(entry["worker_id"])
        job = job_lookup.get(entry["job_id"])

        if not worker or not job:
            continue

        # Calculate labor cost
        duration_hours = (entry.get("duration_minutes", 0) or 0) / 60
        hourly_rate = worker.get("hourly_rate", 15.0)
        labor_cost = duration_hours * hourly_rate

        # Convert times to UK timezone for consistent display
        clock_in_uk = utc_to_uk(entry["clock_in"]) if entry.get("clock_in") else None
        clock_out_uk = utc_to_uk(entry["clock_out"]) if entry.get("clock_out") else None

        # Format the time entry data for report
        result.append({
            "id": entry["id"],
            "worker_id": entry["worker_id"],
            "worker_name": worker["name"],
            "job_id": entry["job_id"],
            "job_name": job["name"],
            "job_client": job.get("client", ""),
            "clock_in": clock_in_uk.isoformat() if clock_in_uk else None,
            "clock_out": clock_out_uk.isoformat() if clock_out_uk else None,
            "duration_minutes": entry.get("duration_minutes", 0),
            "hourly_rate": hourly_rate,
            "labor_cost": labor_cost,
            "notes": entry.get("notes", ""),
            "gps_address_in": entry.get("gps_location_in", {}).get("address", "") if entry.get("gps_location_in") else "",
            "gps_address_out": entry.get("gps_location_out", {}).get("address", "") if entry.get("gps_location_out") else "",
            "archived": entry.get("archived", False)
        })

    # Sort by clock_in date (most recent first)
    result.sort(key=lambda x: x["clock_in"] if x["clock_in"] else "1900-01-01", reverse=True)

    return result

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

    # Get total materials cost this month (UK timezone)
    uk_now = get_uk_time()
    month_start_uk = uk_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_utc = uk_to_utc(month_start_uk)

    month_materials = await db.materials.find({
        "purchase_date": {"$gte": month_start_utc}
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
@api_router.get("/reports/live-map")
async def get_live_worker_map(admin: str = Depends(verify_admin)):
    """Return currently clocked-in workers with captured GPS locations for the dashboard map."""
    return await get_activity_map(active_only=True, admin=admin)

@api_router.get("/reports/activity-map")
async def get_activity_map(
    active_only: bool = Query(False),
    worker_id: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Return clock-in/out map markers with date, worker and job filters."""
    filter_dict = {}
    if active_only:
        filter_dict["clock_out"] = None
    if worker_id:
        filter_dict["worker_id"] = worker_id
    if job_id:
        filter_dict["job_id"] = job_id

    if date:
        start_dt = datetime.fromisoformat(date).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=1)
        filter_dict["clock_in"] = {"$gte": start_dt, "$lt": end_dt}
    else:
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            filter_dict["clock_in"] = {"$gte": start_dt}
        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            if "clock_in" in filter_dict:
                filter_dict["clock_in"]["$lte"] = end_dt
            else:
                filter_dict["clock_in"] = {"$lte": end_dt}

    entries = await db.time_entries.find(filter_dict).to_list(1000)
    markers = []

    for entry in entries:
        worker = await db.workers.find_one({"id": entry.get("worker_id")}) or {}
        job = await db.jobs.find_one({"id": entry.get("job_id")}) or {}

        def append_marker(gps, marker_type):
            if not gps:
                return
            latitude = gps.get("latitude")
            longitude = gps.get("longitude")
            if latitude is None or longitude is None:
                return
            markers.append({
                "entry_id": entry.get("id"),
                "worker_id": entry.get("worker_id"),
                "worker_name": worker.get("name", "Unknown worker"),
                "worker_type": worker.get("worker_type", worker.get("role", "worker")),
                "worker_gps_exempt": worker.get("gps_exempt", False),
                "job_id": entry.get("job_id"),
                "job_name": job.get("name", "Unknown job"),
                "job_client": job.get("client", ""),
                "job_location": job.get("location", ""),
                "clock_in": entry.get("clock_in"),
                "clock_out": entry.get("clock_out"),
                "marker_type": marker_type,
                "latitude": latitude,
                "longitude": longitude,
                "accuracy": gps.get("accuracy"),
                "address": gps.get("address", ""),
                "device_id_in": entry.get("device_id_in"),
                "device_id_out": entry.get("device_id_out"),
                "suspicious_flags": entry.get("suspicious_flags", []) or [],
            })

        before_count = len(markers)
        append_marker(entry.get("gps_location_in") or entry.get("gps_location"), "clock_in")
        if not active_only:
            append_marker(entry.get("gps_location_out"), "clock_out")

        # Still return a list record when no GPS exists so the dashboard can show
        # "No GPS recorded" rather than appearing empty. These records are not mapped as pins.
        if len(markers) == before_count:
            markers.append({
                "entry_id": entry.get("id"),
                "worker_id": entry.get("worker_id"),
                "worker_name": worker.get("name", "Unknown worker"),
                "worker_type": worker.get("worker_type", worker.get("role", "worker")),
                "worker_gps_exempt": worker.get("gps_exempt", False),
                "job_id": entry.get("job_id"),
                "job_name": job.get("name", "Unknown job"),
                "job_client": job.get("client", ""),
                "job_location": job.get("location", ""),
                "clock_in": entry.get("clock_in"),
                "clock_out": entry.get("clock_out"),
                "marker_type": "no_gps",
                "latitude": None,
                "longitude": None,
                "accuracy": None,
                "address": "",
                "device_id_in": entry.get("device_id_in"),
                "device_id_out": entry.get("device_id_out"),
                "suspicious_flags": entry.get("suspicious_flags", []) or [],
            })

    markers.sort(key=lambda item: (item.get("worker_name", "").lower(), item.get("marker_type", "")))
    return markers

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


# Initialize services
email_service = None
pdf_generator = None

def get_quote_services():
    """Initialize quote services if available"""
    global email_service, pdf_generator
    if EmailService and QuotePDFGenerator:
        if not email_service:
            email_service = EmailService()
        if not pdf_generator:
            pdf_generator = QuotePDFGenerator()
        return email_service, pdf_generator
    return None, None

# ==================== QUOTE SYSTEM ENDPOINTS ====================

@api_router.post("/quotes/{quote_id}/photos")
async def upload_quote_photos(
    quote_id: str,
    files: List[UploadFile] = File(...),
    surveyor_id: str = Depends(get_current_surveyor)
):
    """Upload multiple photos for a quote using Google Drive"""
    if not get_google_drive_service:
        raise HTTPException(status_code=500, detail="Google Drive service not available")

    # Check if quote exists and belongs to surveyor
    quote = await db.quotes.find_one({"id": quote_id})
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if quote["surveyor_id"] != surveyor_id:
        try:
            verify_admin(None)
        except:
            raise HTTPException(status_code=403, detail="Not authorized to modify this quote")

    # Validate files
    if len(files) > 12:
        raise HTTPException(status_code=400, detail="Maximum 12 photos allowed")

    # Initialize Google Drive service
    drive_service = get_google_drive_service()
    if not drive_service:
        raise HTTPException(status_code=500, detail="Google Drive service initialization failed")

    uploaded_photos = []

    try:
        for file in files:
            # Validate file type
            if not file.content_type or not file.content_type.startswith('image/'):
                raise HTTPException(status_code=400, detail=f"File {file.filename} is not a valid image")

            # Read file content
            file_content = await file.read()

            # Upload to Google Drive
            folder_name = f"Quote_{quote_id}"
            photo_info = drive_service.upload_photo(
                file_content=file_content,
                filename=file.filename,
                folder_name=folder_name
            )

            uploaded_photos.append(photo_info)

    except Exception as e:
        logger.error(f"Error uploading photos: {e}")
        raise HTTPException(status_code=500, detail=f"Error uploading photos: {str(e)}")

    # Update quote with photo information
    await db.quotes.update_one(
        {"id": quote_id},
        {
            "$set": {
                "photos": uploaded_photos,
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": f"Successfully uploaded {len(uploaded_photos)} photos", "photos": uploaded_photos}

@api_router.get("/quotes/{quote_id}/download-pdf")
async def download_quote_pdf(
    quote_id: str,
    surveyor_id: str = Depends(get_current_surveyor)
):
    """Generate and download PDF for a quote"""
    if not QuotePDFGenerator:
        raise HTTPException(status_code=500, detail="PDF generation service not available")

    # Get quote
    quote = await db.quotes.find_one({"id": quote_id})
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    # Check authorization
    if quote["surveyor_id"] != surveyor_id:
        try:
            verify_admin(None)
        except:
            raise HTTPException(status_code=403, detail="Not authorized to access this quote")

    try:
        # Generate PDF
        pdf_generator = QuotePDFGenerator()
        pdf_buffer = pdf_generator.generate_quote_pdf(quote)

        # Return PDF as streaming response
        filename = f"Quote_{quote['quote_number']}.pdf"

        return StreamingResponse(
            io.BytesIO(pdf_buffer.getvalue()),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating PDF: {str(e)}")

@api_router.post("/quotes/{quote_id}/mark-sent")
async def mark_quote_sent(
    quote_id: str,
    surveyor_id: str = Depends(get_current_surveyor)
):
    """Mark quote as sent to client (for manual sending workflow)"""
    # Get quote
    quote = await db.quotes.find_one({"id": quote_id})
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    # Check authorization
    if quote["surveyor_id"] != surveyor_id:
        try:
            verify_admin(None)
        except:
            raise HTTPException(status_code=403, detail="Not authorized to modify this quote")

    # Update quote status
    await db.quotes.update_one(
        {"id": quote_id},
        {
            "$set": {
                "status": "sent",
                "sent_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": "Quote marked as sent successfully"}

@api_router.post("/quotes/{quote_id}/client-response")
async def handle_client_response(quote_id: str, response_data: ClientResponse):
    """Handle client response to quote (accept/decline)"""
    # Get quote
    quote = await db.quotes.find_one({"id": quote_id})
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    # Update quote with client response
    update_data = {
        "client_response": response_data.response,
        "client_response_date": datetime.utcnow(),
        "client_message": response_data.message,
        "updated_at": datetime.utcnow()
    }

    # Update status based on response
    if response_data.response == "accepted":
        update_data["status"] = "accepted"
    else:
        update_data["status"] = "declined"

    await db.quotes.update_one({"id": quote_id}, {"$set": update_data})

    # Send notification email to info@ldagroup.co.uk
    try:
        email_service, _ = get_quote_services()
        if email_service:
            email_service.send_client_response_notification(quote, response_data)
    except Exception as e:
        logger.warning(f"Failed to send notification email: {e}")

    return {"message": f"Quote {response_data.response} successfully"}

# Startup event
@app.on_event("startup")
async def startup_db_client():
    """Initialize database connection on startup"""
    global db
    try:
        db = await get_database()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

# Shutdown event
@app.on_event("shutdown")
async def shutdown_db_client():
    """Close database connection on shutdown"""
    try:
        if db and hasattr(db, 'client'):
            db.client.close()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error closing database connection: {e}")

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
    """Get materials report with job/client details and filters (Admin only)"""
    filter_query = {"archived": {"$ne": True}}

    if job_id:
        filter_query["job_id"] = job_id
    if supplier:
        filter_query["supplier"] = {"$regex": supplier, "$options": "i"}
    if worker_id:
        filter_query["worker_id"] = worker_id
    if start_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        filter_query["purchase_date"] = {"$gte": start_dt}
    if end_date:
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if "purchase_date" in filter_query:
            filter_query["purchase_date"]["$lte"] = end_dt
        else:
            filter_query["purchase_date"] = {"$lte": end_dt}

    materials = await db.materials.find(filter_query).to_list(1000)
    jobs = await db.jobs.find().to_list(1000)
    job_lookup = {job["id"]: job for job in jobs if "id" in job}

    result = []
    for material in materials:
        job = job_lookup.get(material.get("job_id"))
        if not job:
            continue
        if client and client.lower() not in job.get("client", "").lower():
            continue

        purchase_date = utc_to_uk(material.get("purchase_date")) if material.get("purchase_date") else None
        cost = material.get("cost", 0) or 0
        quantity = material.get("quantity", 1) or 1

        result.append({
            "id": material.get("id"),
            "job_id": material.get("job_id"),
            "job_name": job.get("name", "Unknown"),
            "job_client": job.get("client", ""),
            "material_name": material.get("name", ""),
            "name": material.get("name", ""),
            "cost": cost,
            "quantity": quantity,
            "supplier": material.get("supplier", ""),
            "reference": material.get("reference", ""),
            "date": purchase_date.isoformat() if purchase_date else None,
            "purchase_date": purchase_date.isoformat() if purchase_date else None,
            "notes": material.get("notes", ""),
            "total_value": cost * quantity,
            "archived": material.get("archived", False)
        })

    result.sort(key=lambda x: x["date"] if x["date"] else "1900-01-01", reverse=True)
    return result

@api_router.get("/reports/job-costs/{job_id}")
async def get_job_cost_report(job_id: str, admin: str = Depends(verify_admin)):
    """Get detailed job cost report (Admin only)"""
    # Get job details
    job = await db.jobs.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get time entries for this job
    time_entries = await db.time_entries.find({"job_id": job_id}).to_list(1000)
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

    # Clean data for response
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
            "hourly_rate": worker_rates.get(entry.get("worker_id"), 15.0)
        }
        clean_time_entries.append(clean_entry)

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

# ==================== CSV EXPORT SYSTEM ====================

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

    # Time entries section
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
            format_uk_datetime_for_export(clock_in),
            format_uk_datetime_for_export(clock_out) if clock_out else "Active",
            duration_hours,
            f"£{entry_labor_cost:.2f}",
            entry.get("notes", "")
        ])

    writer.writerow([])
    writer.writerow(["TOTAL LABOR", "", "", total_hours, f"£{labor_cost:.2f}", ""])
    writer.writerow([])

    # Materials section
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
        io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@api_router.get("/reports/export/time-entries")
async def export_time_entries_csv(
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
        "GPS In Lat", "GPS In Lng", "GPS In Accuracy", "GPS In Address",
        "GPS Out Lat", "GPS Out Lng", "GPS Out Accuracy", "GPS Out Address",
        "Device ID In", "Device ID Out", "Suspicious Flags"
    ])

    # Data rows
    for entry in time_entries:
        clock_in = entry.get("clock_in", "")
        clock_out = entry.get("clock_out", "")
        duration_hours = round(entry.get("duration_minutes", 0) / 60, 2) if entry.get("duration_minutes") else ""
        hourly_rate = worker_rates.get(entry["worker_id"], 15.0)
        labor_cost = duration_hours * hourly_rate if duration_hours else 0

        # GPS locations
        gps_in_lat = gps_in_lng = gps_in_accuracy = gps_in_address = ""
        if entry.get("gps_location_in"):
            gps_in_lat = entry["gps_location_in"].get("latitude", "")
            gps_in_lng = entry["gps_location_in"].get("longitude", "")
            gps_in_accuracy = entry["gps_location_in"].get("accuracy", "")
            gps_in_address = entry["gps_location_in"].get("address", "")

        gps_out_lat = gps_out_lng = gps_out_accuracy = gps_out_address = ""
        if entry.get("gps_location_out"):
            gps_out_lat = entry["gps_location_out"].get("latitude", "")
            gps_out_lng = entry["gps_location_out"].get("longitude", "")
            gps_out_accuracy = entry["gps_location_out"].get("accuracy", "")
            gps_out_address = entry["gps_location_out"].get("address", "")

        writer.writerow([
            worker_names.get(entry["worker_id"], "Unknown"),
            job_names.get(entry["job_id"], "Unknown"),
            format_uk_datetime_for_export(clock_in),
            format_uk_datetime_for_export(clock_out),
            duration_hours,
            f"£{hourly_rate:.2f}",
            f"£{labor_cost:.2f}",
            entry.get("notes", ""),
            gps_in_lat, gps_in_lng, gps_in_accuracy, gps_in_address,
            gps_out_lat, gps_out_lng, gps_out_accuracy, gps_out_address,
            entry.get("device_id_in", ""),
            entry.get("device_id_out", ""),
            "; ".join(entry.get("suspicious_flags", []) or [])
        ])

    output.seek(0)

    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=time_entries.csv"}
    )



async def build_time_entries_export_rows(
    worker_id: Optional[str] = None,
    job_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    worker_type: Optional[str] = None,
    division: Optional[str] = None,
    trade: Optional[str] = None,
):
    """Shared row builder for PDF timesheet exports."""
    filter_dict = {"archived": {"$ne": True}}
    if worker_id and worker_id != "all":
        filter_dict["worker_id"] = worker_id
    if job_id and job_id != "all":
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

    time_entries = await db.time_entries.find(filter_dict).sort("clock_in", 1).to_list(5000)
    worker_ids = list({entry.get("worker_id") for entry in time_entries if entry.get("worker_id")})
    job_ids = list({entry.get("job_id") for entry in time_entries if entry.get("job_id")})

    workers = await db.workers.find({"id": {"$in": worker_ids}}, {"_id": 0}).to_list(1000) if worker_ids else []
    jobs = await db.jobs.find({"id": {"$in": job_ids}}, {"_id": 0}).to_list(1000) if job_ids else []
    worker_lookup = {worker.get("id"): worker for worker in workers}
    job_lookup = {job.get("id"): job for job in jobs}

    rows = []
    for entry in time_entries:
        worker = worker_lookup.get(entry.get("worker_id"), {})
        job = job_lookup.get(entry.get("job_id"), {})

        if worker_type and worker_type != "all" and worker.get("worker_type", "worker") != worker_type:
            continue
        if division and division != "all" and worker.get("division", "") != division:
            continue
        if trade and trade != "all":
            worker_trades = worker.get("trades") or ([worker.get("trade")] if worker.get("trade") else [])
            if trade not in worker_trades:
                continue

        duration_hours = round((entry.get("duration_minutes", 0) or 0) / 60, 2)
        rows.append({
            "worker_name": worker.get("name", "Unknown Worker"),
            "worker_type": worker.get("worker_type", "worker"),
            "division": worker.get("division", ""),
            "job_name": job.get("name", "Unknown Job"),
            "job_client": job.get("client", ""),
            "clock_in": format_uk_datetime_for_export(entry.get("clock_in")),
            "clock_out": format_uk_datetime_for_export(entry.get("clock_out")) if entry.get("clock_out") else "Active",
            "duration_hours": duration_hours,
            "notes": entry.get("notes", ""),
        })
    return rows


@api_router.get("/reports/export/time-entries-pdf")
@api_router.get("/reports/export/time-entries/pdf")
@api_router.get("/reports/export/time-entries.pdf")
async def export_time_entries_pdf(
    worker_id: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    worker_type: Optional[str] = Query(None),
    worker_division: Optional[str] = Query(None),
    job_division: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    group_by: str = Query("worker"),
    admin: str = Depends(verify_admin)
):
    """Export time entries as a PDF timesheet. Supports the frontend route and legacy route aliases."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except Exception as exc:
        logger.error("PDF export dependency error: %s", exc)
        raise HTTPException(status_code=500, detail="PDF export is not available on this server. Check reportlab is installed.")

    # The frontend currently sends worker_division. The backend row builder expects division.
    effective_division = worker_division or division
    rows = await build_time_entries_export_rows(worker_id, job_id, start_date, end_date, worker_type, effective_division, trade)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=0.8*cm, leftMargin=0.8*cm, topMargin=0.8*cm, bottomMargin=0.8*cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("LDA Group - Time Sheet Export", styles["Title"]),
        Paragraph(f"Date range: {start_date or 'All'} to {end_date or 'All'}", styles["Normal"]),
        Paragraph(f"Generated: {get_uk_time().strftime('%d/%m/%Y %H:%M')} UK time", styles["Normal"]),
        Spacer(1, 0.35*cm),
    ]

    if not rows:
        story.append(Paragraph("No time entries found for the selected filters.", styles["Normal"]))
    else:
        if group_by == "job":
            rows.sort(key=lambda row: (row["job_name"].lower(), row["worker_name"].lower(), row["clock_in"]))
        else:
            rows.sort(key=lambda row: (row["worker_name"].lower(), row["job_name"].lower(), row["clock_in"]))

        table_data = [["Worker", "Division", "Job", "Client", "Clock In", "Clock Out", "Hours", "Notes"]]
        total_hours = 0
        for row in rows:
            total_hours += row["duration_hours"] or 0
            table_data.append([
                Paragraph(row["worker_name"], styles["BodyText"]),
                Paragraph(row["division"] or "-", styles["BodyText"]),
                Paragraph(row["job_name"], styles["BodyText"]),
                Paragraph(row["job_client"] or "-", styles["BodyText"]),
                row["clock_in"],
                row["clock_out"],
                f"{row['duration_hours']:.2f}",
                Paragraph(row["notes"] or "", styles["BodyText"]),
            ])
        table_data.append(["TOTAL", "", "", "", "", "", f"{total_hours:.2f}", ""])

        table = Table(table_data, colWidths=[3.2*cm, 2.6*cm, 4.0*cm, 3.0*cm, 3.0*cm, 3.0*cm, 1.5*cm, 6.0*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d01f2f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eeeeee")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f7f7f7")]),
        ]))
        story.append(table)

    doc.build(story)
    buffer.seek(0)
    filename = f"time_sheet_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@api_router.get("/reports/export/materials")
async def export_materials_csv(
    worker_id: Optional[str] = Query(None),
    supplier: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Export materials report as CSV (Admin only)"""
    filter_query = {"archived": {"$ne": True}}

    if start_date and end_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        filter_query["purchase_date"] = {"$gte": start_dt, "$lte": end_dt}

    if supplier:
        filter_query["supplier"] = {"$regex": supplier, "$options": "i"}

    materials = await db.materials.find(filter_query).to_list(1000)
    jobs = await db.jobs.find().to_list(1000)
    job_lookup = {job["id"]: job for job in jobs if "id" in job}

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
    filename = f"materials_report_{datetime.utcnow().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@api_router.get("/reports/export/attendance-alerts")
async def export_attendance_alerts_csv(admin: str = Depends(verify_admin)):
    """Export attendance alerts for the last 7 days as CSV (Admin only)"""
    # Get attendance alerts (same logic as dashboard)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    nine_am_threshold = timedelta(hours=9)
    five_pm_threshold = timedelta(hours=17)

    non_admin_workers = await db.workers.find({
        "role": {"$ne": "admin"},
        "active": True,
        "archived": {"$ne": True}
    }).to_list(1000)

    attendance_alerts = []

    for worker in non_admin_workers:
        for i in range(7):
            day_start = (datetime.utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            nine_am = day_start + nine_am_threshold
            five_pm = day_start + five_pm_threshold

            if day_start.date() == datetime.utcnow().date() and datetime.utcnow().hour < 9:
                continue
            if day_start.date() > datetime.utcnow().date():
                continue

            day_entries = await db.time_entries.find({
                "worker_id": worker["id"],
                "clock_in": {"$gte": day_start, "$lt": day_end}
            }).to_list(100)

            if not day_entries:
                if day_start.weekday() < 5 and day_start.date() != datetime.utcnow().date():
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
                for entry in day_entries:
                    clock_in_time = entry["clock_in"]
                    if clock_in_time > nine_am:
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

    # Sort and create CSV
    attendance_alerts.sort(key=lambda x: (x["date"], x["worker_name"]), reverse=True)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ATTENDANCE ALERTS - LAST 7 DAYS",
        f"Generated: {get_uk_time().strftime('%Y-%m-%d %H:%M:%S')} UK Time"
    ])
    writer.writerow([])
    writer.writerow(["Worker Name", "Worker Email", "Alert Type", "Date", "Day of Week", "Time", "Details"])

    for alert in attendance_alerts:
        writer.writerow([
            alert["worker_name"], alert["worker_email"], alert["type"],
            alert["date"], alert["day_of_week"], alert["time"], alert["details"]
        ])

    # Summary
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow([])

    type_counts = {}
    for alert in attendance_alerts:
        alert_type = alert["type"]
        type_counts[alert_type] = type_counts.get(alert_type, 0) + 1

    for alert_type, count in type_counts.items():
        writer.writerow([alert_type, count])

    writer.writerow([])
    writer.writerow(["Total Alerts", len(attendance_alerts)])

    output.seek(0)
    filename = f"attendance_alerts_{datetime.utcnow().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ==================== ENHANCED MATERIAL & TIME ENTRY MANAGEMENT ====================

@api_router.put("/materials/{material_id}/archive")
async def archive_material_endpoint(material_id: str, admin: str = Depends(verify_admin)):
    """Archive material (Admin only)"""
    result = await db.materials.update_one(
        {"id": material_id},
        {"$set": {"archived": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"message": "Material archived successfully"}

@api_router.put("/materials/{material_id}/unarchive")
async def unarchive_material_endpoint(material_id: str, admin: str = Depends(verify_admin)):
    """Unarchive material (Admin only)"""
    result = await db.materials.update_one(
        {"id": material_id},
        {"$set": {"archived": False}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"message": "Material unarchived successfully"}

@api_router.delete("/time-entries/{entry_id}")
async def delete_time_entry_endpoint(entry_id: str, admin: str = Depends(verify_admin)):
    """Delete time entry (Admin only)"""
    result = await db.time_entries.delete_one({"id": entry_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return {"message": "Time entry deleted successfully"}

@api_router.put("/time-entries/{entry_id}/archive")
async def archive_time_entry_endpoint(entry_id: str, admin: str = Depends(verify_admin)):
    """Archive time entry (Admin only)"""
    result = await db.time_entries.update_one(
        {"id": entry_id},
        {"$set": {"archived": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return {"message": "Time entry archived successfully"}

# ==================== SCHEDULING ENDPOINTS ====================

@api_router.get("/schedule", response_model=List[Dict[str, Any]])
async def get_schedule_entries(
    start_date: str = Query(...),
    end_date: str = Query(...),
    worker_type: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Get schedule entries between two dates inclusive (Admin only), with optional worker filters."""
    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    filter_query = {
        "scheduled_date": {"$gte": start_date, "$lte": end_date},
        "archived": {"$ne": True}
    }

    if job_id and job_id != "all":
        filter_query["job_id"] = job_id

    worker_filter = {"active": True, "archived": {"$ne": True}}
    if worker_type and worker_type != "all":
        worker_filter["worker_type"] = worker_type
    if division and division != "all":
        worker_filter["division"] = division
    if trade and trade != "all":
        worker_filter["$or"] = [{"trades": trade}, {"trade": trade}]

    worker_filters_applied = any([
        worker_type and worker_type != "all",
        division and division != "all",
        trade and trade != "all"
    ])

    filtered_workers = []
    if worker_filters_applied:
        filtered_workers = await db.workers.find(worker_filter).to_list(1000)
        filtered_worker_ids = [worker["id"] for worker in filtered_workers if "id" in worker]
        filter_query["worker_id"] = {"$in": filtered_worker_ids}

    entries = await db.schedule_entries.find(filter_query).to_list(1000)

    worker_ids = list({entry.get("worker_id") for entry in entries if entry.get("worker_id")})
    job_ids = list({entry.get("job_id") for entry in entries if entry.get("job_id")})

    workers = await db.workers.find({"id": {"$in": worker_ids}}).to_list(1000) if worker_ids else []
    jobs = await db.jobs.find({"id": {"$in": job_ids}}).to_list(1000) if job_ids else []

    worker_lookup = {worker["id"]: worker for worker in workers if "id" in worker}
    job_lookup = {job["id"]: job for job in jobs if "id" in job}

    result = []
    for entry in entries:
        entry.pop("_id", None)
        worker = worker_lookup.get(entry.get("worker_id"), {})
        job = job_lookup.get(entry.get("job_id"), {})
        entry["worker_name"] = worker.get("name", "Unknown")
        entry["worker_type"] = worker.get("worker_type", "worker")
        entry["worker_division"] = worker.get("division", "")
        entry["worker_trades"] = worker.get("trades", [worker.get("trade", "")] if worker.get("trade") else [])
        entry["job_name"] = job.get("name", "Unknown")
        entry["job_client"] = job.get("client", "")
        entry["job_location"] = job.get("location", "")
        result.append(entry)

    result.sort(key=lambda x: (x.get("scheduled_date", ""), x.get("worker_name", "")))
    return result

@api_router.get("/schedule/by-job", response_model=List[Dict[str, Any]])
async def get_schedule_by_job(
    start_date: str = Query(...),
    end_date: str = Query(...),
    worker_type: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    admin: str = Depends(verify_admin)
):
    """Return schedule entries grouped by job for the admin job-view planner."""
    entries = await get_schedule_entries(
        start_date=start_date,
        end_date=end_date,
        worker_type=worker_type,
        division=division,
        trade=trade,
        job_id=None,
        admin=admin
    )

    grouped = {}
    for entry in entries:
        job_id_value = entry.get("job_id")
        if job_id_value not in grouped:
            grouped[job_id_value] = {
                "job_id": job_id_value,
                "job_name": entry.get("job_name", "Unknown"),
                "job_client": entry.get("job_client", ""),
                "job_location": entry.get("job_location", ""),
                "entries": []
            }
        grouped[job_id_value]["entries"].append(entry)

    result = list(grouped.values())
    result.sort(key=lambda item: item.get("job_name", ""))
    return result

async def _push_gantt_section_to_schedule(request: GanttPushToScheduleRequest):
    """Create schedule entries from a Gantt section. Skips weekends and protects existing allocations."""
    if not request.worker_ids:
        raise HTTPException(status_code=400, detail="Select at least one worker")

    try:
        start = datetime.fromisoformat(request.start_date).date()
        end = datetime.fromisoformat(request.end_date).date()
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date and end_date must be YYYY-MM-DD")

    if end < start:
        raise HTTPException(status_code=400, detail="End date cannot be before start date")

    job = await db.jobs.find_one({"id": request.job_id, "archived": {"$ne": True}})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    workers = await db.workers.find({"id": {"$in": request.worker_ids}, "active": True, "archived": {"$ne": True}}).to_list(1000)
    found_worker_ids = {worker.get("id") for worker in workers}
    missing_worker_ids = [worker_id for worker_id in request.worker_ids if worker_id not in found_worker_ids]
    if missing_worker_ids:
        raise HTTPException(status_code=404, detail=f"Worker(s) not found or inactive: {', '.join(missing_worker_ids)}")

    section_note = request.section_name or "Section"

    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current = current + timedelta(days=1)

    if request.replace_existing_for_section and dates:
        await db.schedule_entries.update_many(
            {
                "job_id": request.job_id,
                "worker_id": {"$in": request.worker_ids},
                "scheduled_date": {"$in": dates},
                "notes": section_note,
                "archived": {"$ne": True},
            },
            {"$set": {"archived": True, "updated_date": datetime.utcnow()}},
        )

    created = []
    skipped = []
    clashes = []
    worker_lookup = {worker.get("id"): worker for worker in workers}

    for worker_id in request.worker_ids:
        worker = worker_lookup.get(worker_id, {})
        for scheduled_date in dates:
            existing = await db.schedule_entries.find_one({
                "worker_id": worker_id,
                "scheduled_date": scheduled_date,
                "archived": {"$ne": True},
            })
            if existing:
                clashes.append({
                    "worker_id": worker_id,
                    "worker_name": worker.get("name", "Unknown"),
                    "scheduled_date": scheduled_date,
                    "existing_job_id": existing.get("job_id"),
                })
                continue

            entry_obj = ScheduleEntry(
                worker_id=worker_id,
                job_id=request.job_id,
                scheduled_date=scheduled_date,
                notes=section_note,
                status="scheduled",
            )
            await db.schedule_entries.insert_one(entry_obj.dict())
            created.append(entry_obj.dict())

    return {
        "message": "Gantt section pushed to schedule",
        "created_count": len(created),
        "skipped_weekend_count": max(0, ((end - start).days + 1) - len(dates)),
        "clash_count": len(clashes),
        "created": created,
        "clashes": clashes,
    }

@api_router.post("/gantt/push-to-schedule")
async def push_gantt_to_schedule(request: GanttPushToScheduleRequest, admin: str = Depends(verify_admin)):
    return await _push_gantt_section_to_schedule(request)

@api_router.post("/schedule/from-gantt")
async def schedule_from_gantt(request: GanttPushToScheduleRequest, admin: str = Depends(verify_admin)):
    return await _push_gantt_section_to_schedule(request)

@api_router.post("/schedule", response_model=ScheduleEntry)
async def create_schedule_entry(schedule_entry: ScheduleEntryCreate, admin: str = Depends(verify_admin)):
    """Allocate a worker to an active job on a specific date (Admin only)."""
    try:
        datetime.fromisoformat(schedule_entry.scheduled_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="scheduled_date must be in YYYY-MM-DD format")

    worker = await db.workers.find_one({"id": schedule_entry.worker_id, "active": True, "archived": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Active worker not found")

    job = await db.jobs.find_one({"id": schedule_entry.job_id, "status": "active", "archived": {"$ne": True}})
    if not job:
        raise HTTPException(status_code=404, detail="Active job not found")

    existing = await db.schedule_entries.find_one({"worker_id": schedule_entry.worker_id, "scheduled_date": schedule_entry.scheduled_date, "archived": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="This worker already has a scheduled job on this date")

    entry_obj = ScheduleEntry(**schedule_entry.dict())
    await db.schedule_entries.insert_one(entry_obj.dict())
    return entry_obj

@api_router.put("/schedule/{schedule_id}", response_model=ScheduleEntry)
async def update_schedule_entry(schedule_id: str, schedule_update: ScheduleEntryUpdate, admin: str = Depends(verify_admin)):
    """Update a schedule allocation (Admin only)."""
    existing_entry = await db.schedule_entries.find_one({"id": schedule_id, "archived": {"$ne": True}})
    if not existing_entry:
        raise HTTPException(status_code=404, detail="Schedule entry not found")

    update_dict = {k: v for k, v in schedule_update.dict().items() if v is not None}
    if not update_dict:
        existing_entry.pop("_id", None)
        return ScheduleEntry(**existing_entry)

    new_worker_id = update_dict.get("worker_id", existing_entry.get("worker_id"))
    new_job_id = update_dict.get("job_id", existing_entry.get("job_id"))
    new_date = update_dict.get("scheduled_date", existing_entry.get("scheduled_date"))

    if "scheduled_date" in update_dict:
        try:
            datetime.fromisoformat(update_dict["scheduled_date"])
        except ValueError:
            raise HTTPException(status_code=400, detail="scheduled_date must be in YYYY-MM-DD format")

    if "worker_id" in update_dict:
        worker = await db.workers.find_one({"id": new_worker_id, "active": True, "archived": {"$ne": True}})
        if not worker:
            raise HTTPException(status_code=404, detail="Active worker not found")

    if "job_id" in update_dict:
        job = await db.jobs.find_one({"id": new_job_id, "status": "active", "archived": {"$ne": True}})
        if not job:
            raise HTTPException(status_code=404, detail="Active job not found")

    duplicate = await db.schedule_entries.find_one({"id": {"$ne": schedule_id}, "worker_id": new_worker_id, "scheduled_date": new_date, "archived": {"$ne": True}})
    if duplicate:
        raise HTTPException(status_code=400, detail="This worker already has a scheduled job on this date")

    update_dict["updated_date"] = datetime.utcnow()
    result = await db.schedule_entries.update_one({"id": schedule_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Schedule entry not found")

    updated_entry = await db.schedule_entries.find_one({"id": schedule_id})
    updated_entry.pop("_id", None)
    return ScheduleEntry(**updated_entry)

@api_router.delete("/schedule/{schedule_id}")
async def delete_schedule_entry(schedule_id: str, admin: str = Depends(verify_admin)):
    """Delete a schedule allocation (Admin only)."""
    result = await db.schedule_entries.delete_one({"id": schedule_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Schedule entry not found")
    return {"message": "Schedule entry deleted successfully"}



async def build_schedule_export_data(
    start_date: str,
    end_date: str,
    worker_ids: Optional[str] = None,
    worker_type: Optional[str] = None,
    division: Optional[str] = None,
    trade: Optional[str] = None
):
    """Build schedule rows for CSV/PDF export and worker schedule views."""
    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    worker_filter = {"active": True, "archived": {"$ne": True}, "role": {"$ne": "admin"}}
    if worker_type and worker_type != "all":
        worker_filter["worker_type"] = worker_type
    if division and division != "all":
        worker_filter["division"] = division
    if trade and trade != "all":
        worker_filter["$or"] = [{"trades": trade}, {"trade": trade}]

    selected_worker_ids = []
    if worker_ids:
        selected_worker_ids = [worker_id.strip() for worker_id in worker_ids.split(",") if worker_id.strip()]
        if selected_worker_ids:
            worker_filter["id"] = {"$in": selected_worker_ids}

    workers = await db.workers.find(worker_filter).to_list(1000)
    workers.sort(key=lambda worker: worker.get("name", ""))

    schedule_filter = {"scheduled_date": {"$gte": start_date, "$lte": end_date}, "archived": {"$ne": True}}
    if selected_worker_ids:
        schedule_filter["worker_id"] = {"$in": selected_worker_ids}

    entries = await db.schedule_entries.find(schedule_filter).to_list(1000)
    job_ids = list({entry.get("job_id") for entry in entries if entry.get("job_id")})
    jobs = await db.jobs.find({"id": {"$in": job_ids}}).to_list(1000) if job_ids else []
    job_lookup = {job["id"]: job for job in jobs if "id" in job}

    entry_lookup = {}
    enriched_entries = []
    for entry in entries:
        entry.pop("_id", None)
        job = job_lookup.get(entry.get("job_id"), {})
        entry["job_name"] = job.get("name", "Unknown")
        entry["job_client"] = job.get("client", "")
        worker_match = next((worker for worker in workers if worker.get("id") == entry.get("worker_id")), {})
        entry["job_location"] = job.get("location", "")
        entry["worker_name"] = worker_match.get("name", "")
        entry["worker_type"] = worker_match.get("worker_type", "worker")
        entry["worker_division"] = worker_match.get("division", "")
        entry["worker_trades"] = worker_match.get("trades", [worker_match.get("trade", "")] if worker_match.get("trade") else [])
        enriched_entries.append(entry)
        entry_lookup[(entry.get("worker_id"), entry.get("scheduled_date"))] = entry

    return {"workers": workers, "entries": enriched_entries, "entry_lookup": entry_lookup}

@api_router.get("/schedule/worker/{worker_id}", response_model=List[Dict[str, Any]])
async def get_worker_schedule_entries(
    worker_id: str,
    start_date: str = Query(...),
    end_date: str = Query(...)
):
    """Get one worker's schedule between two dates. Used by the worker frontend."""
    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    worker = await db.workers.find_one({"id": worker_id, "active": True, "archived": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    entries = await db.schedule_entries.find({
        "worker_id": worker_id,
        "scheduled_date": {"$gte": start_date, "$lte": end_date},
        "archived": {"$ne": True}
    }).to_list(1000)

    job_ids = list({entry.get("job_id") for entry in entries if entry.get("job_id")})
    jobs = await db.jobs.find({"id": {"$in": job_ids}}).to_list(1000) if job_ids else []
    job_lookup = {job["id"]: job for job in jobs if "id" in job}

    result = []
    for entry in entries:
        entry.pop("_id", None)
        job = job_lookup.get(entry.get("job_id"), {})
        entry["worker_name"] = worker.get("name", "")
        entry["job_name"] = job.get("name", "Unknown")
        entry["job_client"] = job.get("client", "")
        entry["job_location"] = job.get("location", "")
        result.append(entry)

    result.sort(key=lambda item: item.get("scheduled_date", ""))
    return result

@api_router.get("/schedule/export")
async def export_schedule(
    start_date: str = Query(...),
    end_date: str = Query(...),
    worker_ids: Optional[str] = Query(None),
    worker_type: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    format: str = Query("csv"),
    admin: str = Depends(verify_admin)
):
    """Export selected workers' schedule as CSV or PDF."""
    export_data = await build_schedule_export_data(start_date, end_date, worker_ids, worker_type, division, trade)
    workers = export_data["workers"]
    entry_lookup = export_data["entry_lookup"]

    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)
    date_list = []
    cursor = start_dt
    while cursor <= end_dt:
        date_list.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)

    def cell_text(worker_id: str, day: str) -> str:
        entry = entry_lookup.get((worker_id, day))
        if not entry:
            return "Unallocated"
        lines = [entry.get("job_name", "Scheduled job")]
        if entry.get("job_client"):
            lines.append(entry.get("job_client"))
        if entry.get("job_location"):
            lines.append(entry.get("job_location"))
        if entry.get("notes"):
            lines.append(f"Notes: {entry.get('notes')}")
        return " | ".join(lines)

    if format.lower() == "pdf":
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        except Exception as e:
            logger.error(f"PDF export dependency error: {e}")
            raise HTTPException(status_code=500, detail="PDF export is not available on this server")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1*cm, leftMargin=1*cm, topMargin=1*cm, bottomMargin=1*cm)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("LDA Group - Weekly Worker Schedule", styles["Title"]),
            Paragraph(f"{start_date} to {end_date}", styles["Normal"]),
            Spacer(1, 0.4*cm),
        ]

        headers = ["Worker"] + [datetime.fromisoformat(day).strftime("%a %d %b") for day in date_list]
        table_data = [headers]
        for worker in workers:
            row = [worker.get("name", "Unknown")]
            for day in date_list:
                text = cell_text(worker.get("id"), day).replace(" | ", "<br/>")
                row.append(Paragraph(text, styles["BodyText"]))
            table_data.append(row)

        if len(table_data) == 1:
            table_data.append(["No selected workers"] + ["" for _ in date_list])

        col_widths = [3.2*cm] + [3.1*cm for _ in date_list]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d01f2f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ]))
        story.append(table)
        doc.build(story)
        buffer.seek(0)
        filename = f"worker_schedule_{start_date}_to_{end_date}.pdf"
        return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["LDA Group - Weekly Worker Schedule"])
    writer.writerow(["Date range", start_date, "to", end_date])
    writer.writerow([])
    writer.writerow(["Worker"] + [datetime.fromisoformat(day).strftime("%a %d %b %Y") for day in date_list])

    for worker in workers:
        writer.writerow([worker.get("name", "Unknown")] + [cell_text(worker.get("id"), day) for day in date_list])

    output.seek(0)
    filename = f"worker_schedule_{start_date}_to_{end_date}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ==================== SYSTEM STATUS & API INFO ====================

@api_router.get("/system/status")
async def get_system_status_endpoint():
    """Get system and service status"""
    # Check database connection
    db_status = False
    try:
        if db:
            await db.command("ping")
            db_status = True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")

    # Check quote services
    services_status = {
        "email_service": EmailService is not None,
        "pdf_generator": QuotePDFGenerator is not None,
        "google_drive": get_google_drive_service is not None and callable(get_google_drive_service)
    }

    return {
        "system": "operational",
        "database": db_status,
        "services": services_status,
        "timestamp": datetime.utcnow().isoformat(),
        "uk_time": get_uk_time().strftime('%Y-%m-%d %H:%M:%S %Z')
    }

@api_router.get("/api-info")
async def api_info_endpoint():
    """Get comprehensive API information"""
    return {
        "message": "LDA Group Time Tracking API",
        "version": "2.0.0",
        "features": [
            "Worker Management & Authentication",
            "Time Tracking with GPS",
            "Material Management",
            "Job Management & Costing",
            "Advanced Reporting & Analytics",
            "Comprehensive CSV Exports",
            "Quote System with PDF Generation",
            "Surveyor Authentication",
            "UK Timezone Support",
            "Real-time Dashboard Statistics",
            "Worker Scheduling Board"
        ],
        "main_endpoints": {
            "authentication": ["/api/admin/login", "/api/surveyors/login", "/api/surveyors/register"],
            "workers": ["/api/workers", "/api/workers/{id}", "/api/workers/{id}/archive"],
            "jobs": ["/api/jobs", "/api/jobs/{id}", "/api/jobs/{id}/archive", "/api/jobs/{id}/post-work-photos"],
            "time_tracking": ["/api/time-entries", "/api/time-entries/clock-in", "/api/time-entries/{id}/clock-out"],
            "materials": ["/api/materials", "/api/materials/{id}", "/api/materials/{id}/archive"],
            "quotes": ["/api/quotes", "/api/quotes/{id}", "/api/quotes/{id}/photos", "/api/quotes/{id}/download-pdf"],
            "reports": ["/api/reports/dashboard", "/api/reports/time-entries", "/api/reports/materials", "/api/reports/job-costs/{id}"],
            "schedule": ["/api/schedule", "/api/schedule/{id}", "/api/schedule/worker/{worker_id}", "/api/schedule/export"],
            "exports": ["/api/reports/export/job/{id}", "/api/reports/export/time-entries", "/api/reports/export/materials", "/api/reports/export/attendance-alerts"],
            "system": ["/api/system/status", "/api/api-info"]
        },
        "total_endpoints": 50
    }

# Include the router in the main app after all routes have been registered.
# Important: FastAPI copies the APIRouter routes at include time, so this must stay at the end.
app.include_router(api_router)

# Run the application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        access_log=True
    )
