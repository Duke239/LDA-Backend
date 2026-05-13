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
import re
import smtplib
import requests
from email.message import EmailMessage

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
    gps_exempt: Optional[bool] = None

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
    commercial_markers: List[Dict[str, Any]] = []

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
    commercial_markers: List[Dict[str, Any]] = []
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
    commercial_markers: Optional[List[Dict[str, Any]]] = None

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
    job_id: Optional[str] = None
    scheduled_date: str  # YYYY-MM-DD
    notes: str = ""
    status: str = "scheduled"
    schedule_type: str = "job"  # job, holiday, sick, unavailable
    absence_type: Optional[str] = None
    created_date: datetime = Field(default_factory=datetime.utcnow)
    updated_date: Optional[datetime] = None

class ScheduleEntryCreate(BaseModel):
    worker_id: str
    job_id: Optional[str] = None
    scheduled_date: str  # YYYY-MM-DD
    notes: str = ""
    status: str = "scheduled"
    schedule_type: str = "job"
    absence_type: Optional[str] = None

class ScheduleEntryUpdate(BaseModel):
    worker_id: Optional[str] = None
    job_id: Optional[str] = None
    scheduled_date: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    schedule_type: Optional[str] = None
    absence_type: Optional[str] = None

class GanttPushToScheduleRequest(BaseModel):
    job_id: str
    section_id: str
    worker_ids: List[str]
    start_date: str
    end_date: str
    section_name: str = ""
    replace_existing_for_section: bool = True
    override_existing_allocations: bool = False

class GanttShiftProjectRequest(BaseModel):
    job_id: str
    planned_start_date: str
    planned_end_date: str
    delta_days: int
    shift_sections: bool = True
    shift_schedule: bool = True


class FinanceRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    application_marker_id: Optional[str] = None
    type: str = "application"  # application, invoice, payment, retention, adjustment
    label: str = ""
    submitted_date: Optional[str] = None
    submitted_value: float = 0.0
    certified_value: float = 0.0
    invoice_number: str = ""
    invoice_date: Optional[str] = None
    invoice_value: float = 0.0
    payment_due_date: Optional[str] = None
    paid_date: Optional[str] = None
    paid_value: float = 0.0
    retention_percent: float = 0.0
    retention_value: float = 0.0
    retention_due_date: Optional[str] = None
    retention_paid_date: Optional[str] = None
    status: str = "draft"  # draft, submitted, certified, invoiced, part_paid, paid, overdue, disputed
    notes: str = ""
    created_date: datetime = Field(default_factory=datetime.utcnow)
    updated_date: Optional[datetime] = None
    archived: bool = False

class FinanceRecordCreate(BaseModel):
    job_id: str
    application_marker_id: Optional[str] = None
    type: str = "application"
    label: str = ""
    submitted_date: Optional[str] = None
    submitted_value: float = 0.0
    certified_value: float = 0.0
    invoice_number: str = ""
    invoice_date: Optional[str] = None
    invoice_value: float = 0.0
    payment_due_date: Optional[str] = None
    paid_date: Optional[str] = None
    paid_value: float = 0.0
    retention_percent: float = 0.0
    retention_value: float = 0.0
    retention_due_date: Optional[str] = None
    retention_paid_date: Optional[str] = None
    status: str = "draft"
    notes: str = ""

class FinanceRecordUpdate(BaseModel):
    application_marker_id: Optional[str] = None
    type: Optional[str] = None
    label: Optional[str] = None
    submitted_date: Optional[str] = None
    submitted_value: Optional[float] = None
    certified_value: Optional[float] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    invoice_value: Optional[float] = None
    payment_due_date: Optional[str] = None
    paid_date: Optional[str] = None
    paid_value: Optional[float] = None
    retention_percent: Optional[float] = None
    retention_value: Optional[float] = None
    retention_due_date: Optional[str] = None
    retention_paid_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    archived: Optional[bool] = None


# ==================== PURCHASE ORDER SYSTEM MODELS ====================

class Supplier(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    contact_name: str = ""
    orders_email: str = ""
    accounts_email: str = ""
    phone: str = ""
    address: str = ""
    vat_number: str = ""
    payment_terms: str = "30 days"
    notes: str = ""
    active: bool = True
    archived: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

class SupplierCreate(BaseModel):
    name: str
    contact_name: str = ""
    orders_email: str = ""
    accounts_email: str = ""
    phone: str = ""
    address: str = ""
    vat_number: str = ""
    payment_terms: str = "30 days"
    notes: str = ""

class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    orders_email: Optional[str] = None
    accounts_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    vat_number: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None
    archived: Optional[bool] = None

class PurchaseOrderLine(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    quantity: float = 1.0
    unit_cost: float = 0.0
    vat_rate: float = 20.0
    net_total: float = 0.0
    vat_total: float = 0.0
    gross_total: float = 0.0
    job_section_id: str = ""
    job_section_name: str = ""
    cost_category: str = "Materials"
    received_quantity: float = 0.0
    material_status: str = "committed"
    material_id: Optional[str] = None

class PurchaseOrder(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    po_number: str = ""
    supplier_id: str
    supplier_name: str = ""
    supplier_email: str = ""
    job_id: str
    job_name: str = ""
    job_number: Optional[int] = None
    division: str = ""
    status: str = "draft"
    requested_by_user_id: str = ""
    requested_by_name: str = ""
    approved_by_user_id: Optional[str] = None
    approved_by_name: Optional[str] = None
    approved_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    sent_by_user_id: Optional[str] = None
    sent_by_name: Optional[str] = None
    email_subject: str = ""
    required_date: Optional[str] = None
    delivery_address: str = ""
    notes: str = ""
    supplier_quote_number: str = ""
    source_type: str = "manual"
    source_upload_id: Optional[str] = None
    source_file_name: str = ""
    extraction_status: str = "not_required"
    extraction_confidence: str = ""
    lines: List[PurchaseOrderLine] = []
    net_total: float = 0.0
    vat_total: float = 0.0
    gross_total: float = 0.0
    materials_assigned: bool = False
    materials_assigned_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    supplier_name: str = ""
    supplier_email: str = ""
    job_id: str
    job_name: str = ""
    job_number: Optional[int] = None
    division: str = ""
    required_date: Optional[str] = None
    delivery_address: str = ""
    notes: str = ""
    supplier_quote_number: str = ""
    source_type: str = "manual"
    source_upload_id: Optional[str] = None
    source_file_name: str = ""
    extraction_status: str = "not_required"
    extraction_confidence: str = ""
    lines: List[PurchaseOrderLine] = []
    net_total: float = 0.0
    vat_total: float = 0.0
    gross_total: float = 0.0

class PurchaseOrderUpdate(BaseModel):
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_email: Optional[str] = None
    job_id: Optional[str] = None
    job_name: Optional[str] = None
    job_number: Optional[int] = None
    division: Optional[str] = None
    status: Optional[str] = None
    required_date: Optional[str] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    supplier_quote_number: Optional[str] = None
    source_type: Optional[str] = None
    source_upload_id: Optional[str] = None
    source_file_name: Optional[str] = None
    extraction_status: Optional[str] = None
    extraction_confidence: Optional[str] = None
    lines: Optional[List[PurchaseOrderLine]] = None
    net_total: Optional[float] = None
    vat_total: Optional[float] = None
    gross_total: Optional[float] = None

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


VALID_SCHEDULE_TYPES = {"job", "holiday", "sick", "unavailable"}
ABSENCE_SCHEDULE_TYPES = {"holiday", "sick", "unavailable"}


def normalise_schedule_type(value: Optional[str]) -> str:
    """Return a safe schedule type for older and newer schedule records."""
    schedule_type = str(value or "job").strip().lower()
    return schedule_type if schedule_type in VALID_SCHEDULE_TYPES else "job"


def schedule_type_label(schedule_type: Optional[str]) -> str:
    schedule_type = normalise_schedule_type(schedule_type)
    if schedule_type == "holiday":
        return "Holiday"
    if schedule_type == "sick":
        return "Sick Day"
    if schedule_type == "unavailable":
        return "Unavailable"
    return "Scheduled job"


def is_absence_schedule_type(schedule_type: Optional[str]) -> bool:
    return normalise_schedule_type(schedule_type) in ABSENCE_SCHEDULE_TYPES

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
        schedule_type = normalise_schedule_type(entry.get("schedule_type"))
        entry["schedule_type"] = schedule_type
        entry["absence_type"] = entry.get("absence_type") or (schedule_type if is_absence_schedule_type(schedule_type) else None)
        entry["worker_name"] = worker.get("name", "Unknown")
        entry["worker_type"] = worker.get("worker_type", "worker")
        entry["worker_division"] = worker.get("division", "")
        entry["worker_trades"] = worker.get("trades", [worker.get("trade", "")] if worker.get("trade") else [])
        if is_absence_schedule_type(schedule_type):
            entry["job_name"] = schedule_type_label(schedule_type)
            entry["job_client"] = ""
            entry["job_location"] = ""
        else:
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
    """Create schedule entries from a Gantt section. Skips weekends and protects existing allocations unless override is requested."""
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

    expected_count = len(request.worker_ids) * len(dates)

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
    clashes = []
    overridden = []
    worker_lookup = {worker.get("id"): worker for worker in workers}
    job_lookup: Dict[str, Dict[str, Any]] = {request.job_id: job}

    async def get_job_name(job_id: Optional[str]) -> str:
        if not job_id:
            return "Unknown job"
        if job_id not in job_lookup:
            found_job = await db.jobs.find_one({"id": job_id}) or {}
            job_lookup[job_id] = found_job
        return job_lookup.get(job_id, {}).get("name", "Unknown job")

    for worker_id in request.worker_ids:
        worker = worker_lookup.get(worker_id, {})
        for scheduled_date in dates:
            existing = await db.schedule_entries.find_one({
                "worker_id": worker_id,
                "scheduled_date": scheduled_date,
                "archived": {"$ne": True},
            })
            if existing:
                existing_type = normalise_schedule_type(existing.get("schedule_type"))
                existing_name = schedule_type_label(existing_type) if is_absence_schedule_type(existing_type) else await get_job_name(existing.get("job_id"))
                clash_record = {
                    "worker_id": worker_id,
                    "worker_name": worker.get("name", "Unknown"),
                    "scheduled_date": scheduled_date,
                    "existing_entry_id": existing.get("id"),
                    "existing_job_id": existing.get("job_id"),
                    "existing_job_name": existing_name,
                    "existing_schedule_type": existing_type,
                    "existing_notes": existing.get("notes", ""),
                }

                # Holiday/sick/unavailable records are intentional absence blocks. Do not override them
                # from the Gantt, even when normal job clashes are being overridden.
                if request.override_existing_allocations and not is_absence_schedule_type(existing_type):
                    await db.schedule_entries.update_one(
                        {"id": existing.get("id")},
                        {"$set": {"archived": True, "updated_date": datetime.utcnow(), "overridden_by_gantt_section_id": request.section_id}},
                    )
                    overridden.append(clash_record)
                else:
                    clashes.append(clash_record)
                    continue

            entry_obj = ScheduleEntry(
                worker_id=worker_id,
                job_id=request.job_id,
                scheduled_date=scheduled_date,
                notes=section_note,
                status="scheduled",
                schedule_type="job",
            )
            await db.schedule_entries.insert_one(entry_obj.dict())
            created.append(entry_obj.dict())

    created_entry_ids = [entry.get("id") for entry in created if entry.get("id")]
    fully_scheduled = expected_count > 0 and len(created) >= expected_count and len(clashes) == 0
    schedule_status = "scheduled" if fully_scheduled else "partial_scheduled" if created else "not_scheduled"
    updated_section = None

    gantt_sections = job.get("gantt_sections") or []
    updated_sections = []
    for section in gantt_sections:
        if section.get("id") == request.section_id:
            existing_ids = section.get("schedule_entry_ids") or []
            merged_ids = list(dict.fromkeys([*existing_ids, *created_entry_ids]))
            section = {
                **section,
                "assigned_worker_ids": request.worker_ids,
                "sent_to_schedule": fully_scheduled,
                "schedule_status": schedule_status,
                "schedule_entry_ids": merged_ids,
                "scheduled_at": datetime.utcnow().isoformat() if created else section.get("scheduled_at", ""),
                "schedule_clashes": clashes,
                "last_schedule_push_at": datetime.utcnow().isoformat(),
            }
            updated_section = section
        updated_sections.append(section)

    await db.jobs.update_one(
        {"id": request.job_id},
        {"$set": {"gantt_sections": updated_sections}}
    )

    return {
        "message": "Gantt section pushed to schedule",
        "created_count": len(created),
        "expected_count": expected_count,
        "fully_scheduled": fully_scheduled,
        "skipped_weekend_count": max(0, ((end - start).days + 1) - len(dates)),
        "clash_count": len(clashes),
        "overridden_count": len(overridden),
        "created": created,
        "created_entry_ids": created_entry_ids,
        "clashes": clashes,
        "overridden": overridden,
        "updated_section": updated_section,
    }

@api_router.post("/gantt/push-to-schedule")
async def push_gantt_to_schedule(request: GanttPushToScheduleRequest, admin: str = Depends(verify_admin)):
    return await _push_gantt_section_to_schedule(request)

@api_router.post("/schedule/from-gantt")
async def schedule_from_gantt(request: GanttPushToScheduleRequest, admin: str = Depends(verify_admin)):
    return await _push_gantt_section_to_schedule(request)



def shift_iso_date(value: Optional[str], delta_days: int) -> Optional[str]:
    """Shift a YYYY-MM-DD date string by delta_days and return YYYY-MM-DD."""
    if not value:
        return value
    try:
        shifted = datetime.fromisoformat(str(value)).date() + timedelta(days=delta_days)
        return shifted.isoformat()
    except Exception:
        return value


@api_router.post("/gantt/shift-project")
async def shift_gantt_project(request: GanttShiftProjectRequest, admin: str = Depends(verify_admin)):
    """Move a project's planned dates, optionally moving its sections and linked schedule entries by the same day offset."""
    try:
        datetime.fromisoformat(request.planned_start_date)
        datetime.fromisoformat(request.planned_end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="planned_start_date and planned_end_date must be YYYY-MM-DD")

    if request.delta_days == 0:
        raise HTTPException(status_code=400, detail="delta_days must not be zero")

    job = await db.jobs.find_one({"id": request.job_id, "archived": {"$ne": True}})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    original_sections = job.get("gantt_sections") or []
    updated_sections = []
    linked_schedule_ids = []

    for section in original_sections:
        section_copy = dict(section)
        if request.shift_sections:
            section_copy["start_date"] = shift_iso_date(section_copy.get("start_date"), request.delta_days)
            section_copy["end_date"] = shift_iso_date(section_copy.get("end_date"), request.delta_days)
            if section_copy.get("schedule_status") == "scheduled":
                section_copy["last_programme_shift_at"] = datetime.utcnow().isoformat()
        for entry_id in section_copy.get("schedule_entry_ids") or []:
            if entry_id:
                linked_schedule_ids.append(entry_id)
        updated_sections.append(section_copy)

    shifted_schedule_count = 0
    clashes = []

    if request.shift_schedule and linked_schedule_ids:
        entries = await db.schedule_entries.find({
            "id": {"$in": list(dict.fromkeys(linked_schedule_ids))},
            "archived": {"$ne": True},
        }).to_list(5000)

        for entry in entries:
            old_date = entry.get("scheduled_date")
            new_date = shift_iso_date(old_date, request.delta_days)
            if not new_date or new_date == old_date:
                continue

            duplicate = await db.schedule_entries.find_one({
                "id": {"$ne": entry.get("id")},
                "worker_id": entry.get("worker_id"),
                "scheduled_date": new_date,
                "archived": {"$ne": True},
            })

            if duplicate:
                duplicate_type = normalise_schedule_type(duplicate.get("schedule_type"))
                clashes.append({
                    "entry_id": entry.get("id"),
                    "worker_id": entry.get("worker_id"),
                    "old_date": old_date,
                    "new_date": new_date,
                    "existing_entry_id": duplicate.get("id"),
                    "existing_job_id": duplicate.get("job_id"),
                    "existing_schedule_type": duplicate_type,
                    "existing_label": schedule_type_label(duplicate_type) if is_absence_schedule_type(duplicate_type) else "Existing scheduled job",
                })
                continue

            await db.schedule_entries.update_one(
                {"id": entry.get("id")},
                {"$set": {
                    "scheduled_date": new_date,
                    "updated_date": datetime.utcnow(),
                    "shifted_from_date": old_date,
                    "shifted_by_gantt_job_id": request.job_id,
                }},
            )
            shifted_schedule_count += 1

    # If some linked schedule entries could not be shifted, mark their sections as partial so the Gantt does not look fully safe.
    clash_entry_ids = {item.get("entry_id") for item in clashes if item.get("entry_id")}
    if clash_entry_ids:
        adjusted_sections = []
        for section in updated_sections:
            section_ids = set(section.get("schedule_entry_ids") or [])
            if section_ids.intersection(clash_entry_ids):
                section = {
                    **section,
                    "sent_to_schedule": False,
                    "schedule_status": "partial_scheduled",
                    "schedule_clashes": clashes,
                }
            adjusted_sections.append(section)
        updated_sections = adjusted_sections

    update_doc = {
        "planned_start_date": request.planned_start_date,
        "planned_end_date": request.planned_end_date,
        "gantt_sections": updated_sections if request.shift_sections else original_sections,
        "last_programme_shift_at": datetime.utcnow().isoformat(),
        "last_programme_shift_days": request.delta_days,
    }

    await db.jobs.update_one({"id": request.job_id}, {"$set": update_doc})
    updated_job = await db.jobs.find_one({"id": request.job_id}, {"_id": 0})

    return {
        "message": "Project programme shifted",
        "job": updated_job,
        "delta_days": request.delta_days,
        "sections_shifted": len(updated_sections) if request.shift_sections else 0,
        "shifted_schedule_count": shifted_schedule_count,
        "clash_count": len(clashes),
        "clashes": clashes,
    }

@api_router.post("/schedule", response_model=ScheduleEntry)
async def create_schedule_entry(schedule_entry: ScheduleEntryCreate, admin: str = Depends(verify_admin)):
    """Allocate a worker to a job or block a day as holiday/sick/unavailable (Admin only)."""
    try:
        datetime.fromisoformat(schedule_entry.scheduled_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="scheduled_date must be in YYYY-MM-DD format")

    schedule_type = normalise_schedule_type(schedule_entry.schedule_type)
    if schedule_type == "job" and not schedule_entry.job_id:
        raise HTTPException(status_code=400, detail="Select an active job first")

    worker = await db.workers.find_one({"id": schedule_entry.worker_id, "active": True, "archived": {"$ne": True}})
    if not worker:
        raise HTTPException(status_code=404, detail="Active worker not found")

    if schedule_type == "job":
        job = await db.jobs.find_one({"id": schedule_entry.job_id, "status": "active", "archived": {"$ne": True}})
        if not job:
            raise HTTPException(status_code=404, detail="Active job not found")
    else:
        schedule_entry.job_id = None
        schedule_entry.absence_type = schedule_type

    existing = await db.schedule_entries.find_one({"worker_id": schedule_entry.worker_id, "scheduled_date": schedule_entry.scheduled_date, "archived": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="This worker already has a schedule entry on this date")

    entry_dict = schedule_entry.dict()
    entry_dict["schedule_type"] = schedule_type
    if schedule_type != "job":
        entry_dict["job_id"] = None
        entry_dict["absence_type"] = schedule_type
    entry_obj = ScheduleEntry(**entry_dict)
    await db.schedule_entries.insert_one(entry_obj.dict())
    return entry_obj

@api_router.put("/schedule/{schedule_id}", response_model=ScheduleEntry)
async def update_schedule_entry(schedule_id: str, schedule_update: ScheduleEntryUpdate, admin: str = Depends(verify_admin)):
    """Update a schedule allocation or absence block (Admin only)."""
    existing_entry = await db.schedule_entries.find_one({"id": schedule_id, "archived": {"$ne": True}})
    if not existing_entry:
        raise HTTPException(status_code=404, detail="Schedule entry not found")

    update_dict = {k: v for k, v in schedule_update.dict().items() if v is not None}
    if not update_dict:
        existing_entry.pop("_id", None)
        return ScheduleEntry(**existing_entry)

    new_worker_id = update_dict.get("worker_id", existing_entry.get("worker_id"))
    new_date = update_dict.get("scheduled_date", existing_entry.get("scheduled_date"))
    new_schedule_type = normalise_schedule_type(update_dict.get("schedule_type", existing_entry.get("schedule_type")))
    new_job_id = update_dict.get("job_id", existing_entry.get("job_id"))

    if "scheduled_date" in update_dict:
        try:
            datetime.fromisoformat(update_dict["scheduled_date"])
        except ValueError:
            raise HTTPException(status_code=400, detail="scheduled_date must be in YYYY-MM-DD format")

    if "worker_id" in update_dict:
        worker = await db.workers.find_one({"id": new_worker_id, "active": True, "archived": {"$ne": True}})
        if not worker:
            raise HTTPException(status_code=404, detail="Active worker not found")

    if new_schedule_type == "job":
        if not new_job_id:
            raise HTTPException(status_code=400, detail="Select an active job first")
        job = await db.jobs.find_one({"id": new_job_id, "status": "active", "archived": {"$ne": True}})
        if not job:
            raise HTTPException(status_code=404, detail="Active job not found")
        update_dict["job_id"] = new_job_id
        update_dict["absence_type"] = None
    else:
        update_dict["job_id"] = None
        update_dict["absence_type"] = new_schedule_type

    update_dict["schedule_type"] = new_schedule_type

    duplicate = await db.schedule_entries.find_one({"id": {"$ne": schedule_id}, "worker_id": new_worker_id, "scheduled_date": new_date, "archived": {"$ne": True}})
    if duplicate:
        raise HTTPException(status_code=400, detail="This worker already has a schedule entry on this date")

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
    """Build schedule rows for CSV/PDF export and worker/job schedule views."""
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
    allowed_worker_ids = [worker.get("id") for worker in workers if worker.get("id")]

    schedule_filter = {
        "scheduled_date": {"$gte": start_date, "$lte": end_date},
        "archived": {"$ne": True},
    }

    # Important for job exports: when filters or selected workers are applied, only export
    # allocations for the workers that survived those filters.
    if allowed_worker_ids:
        schedule_filter["worker_id"] = {"$in": allowed_worker_ids}
    else:
        schedule_filter["worker_id"] = {"$in": []}

    entries = await db.schedule_entries.find(schedule_filter).to_list(1000)
    job_ids = list({entry.get("job_id") for entry in entries if entry.get("job_id")})
    jobs = await db.jobs.find({"id": {"$in": job_ids}}).to_list(1000) if job_ids else []
    job_lookup = {job["id"]: job for job in jobs if "id" in job}
    worker_lookup = {worker["id"]: worker for worker in workers if "id" in worker}

    entry_lookup = {}
    job_day_lookup = {}
    enriched_entries = []

    for entry in entries:
        entry.pop("_id", None)
        job = job_lookup.get(entry.get("job_id"), {})
        worker_match = worker_lookup.get(entry.get("worker_id"), {})

        schedule_type = normalise_schedule_type(entry.get("schedule_type"))
        entry["schedule_type"] = schedule_type
        entry["absence_type"] = entry.get("absence_type") or (schedule_type if is_absence_schedule_type(schedule_type) else None)
        if is_absence_schedule_type(schedule_type):
            entry["job_name"] = schedule_type_label(schedule_type)
            entry["job_client"] = ""
            entry["job_location"] = ""
        else:
            entry["job_name"] = job.get("name", "Unknown")
            entry["job_client"] = job.get("client", "")
            entry["job_location"] = job.get("location", "")
        entry["worker_name"] = worker_match.get("name", "Unknown")
        entry["worker_type"] = worker_match.get("worker_type", "worker")
        entry["worker_division"] = worker_match.get("division", "")
        entry["worker_trades"] = worker_match.get("trades", [worker_match.get("trade", "")] if worker_match.get("trade") else [])

        enriched_entries.append(entry)
        entry_lookup[(entry.get("worker_id"), entry.get("scheduled_date"))] = entry
        if not is_absence_schedule_type(schedule_type):
            job_day_lookup.setdefault((entry.get("job_id"), entry.get("scheduled_date")), []).append(entry)

    export_jobs = []
    seen_job_ids = set()
    for entry in enriched_entries:
        job_id_value = entry.get("job_id")
        if not job_id_value or job_id_value in seen_job_ids:
            continue
        job = job_lookup.get(job_id_value, {})
        export_jobs.append({
            "id": job_id_value,
            "name": job.get("name", entry.get("job_name", "Unknown")),
            "client": job.get("client", entry.get("job_client", "")),
            "location": job.get("location", entry.get("job_location", "")),
        })
        seen_job_ids.add(job_id_value)

    export_jobs.sort(key=lambda job: job.get("name", ""))

    return {
        "workers": workers,
        "jobs": export_jobs,
        "entries": enriched_entries,
        "entry_lookup": entry_lookup,
        "job_day_lookup": job_day_lookup,
    }

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
        schedule_type = normalise_schedule_type(entry.get("schedule_type"))
        entry["schedule_type"] = schedule_type
        entry["absence_type"] = entry.get("absence_type") or (schedule_type if is_absence_schedule_type(schedule_type) else None)
        entry["worker_name"] = worker.get("name", "")
        if is_absence_schedule_type(schedule_type):
            entry["job_name"] = schedule_type_label(schedule_type)
            entry["job_client"] = ""
            entry["job_location"] = ""
        else:
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
    group_by: str = Query("worker"),
    format: str = Query("csv"),
    admin: str = Depends(verify_admin)
):
    """Export the weekly schedule as CSV or PDF, grouped by worker or by job."""
    group_by = (group_by or "worker").lower().strip()
    if group_by not in ["worker", "job"]:
        group_by = "worker"

    export_data = await build_schedule_export_data(start_date, end_date, worker_ids, worker_type, division, trade)
    workers = export_data["workers"]
    jobs = export_data["jobs"]
    entry_lookup = export_data["entry_lookup"]
    job_day_lookup = export_data["job_day_lookup"]

    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)
    date_list = []
    cursor = start_dt
    while cursor <= end_dt:
        date_list.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)

    def worker_cell_text(worker_id: str, day: str) -> str:
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

    def job_cell_text(job_id: str, day: str) -> str:
        entries = job_day_lookup.get((job_id, day), [])
        if not entries:
            return "Unallocated"

        lines = []
        for entry in sorted(entries, key=lambda item: item.get("worker_name", "")):
            worker_line = entry.get("worker_name", "Unknown worker")
            extras = []
            if entry.get("worker_division"):
                extras.append(entry.get("worker_division"))
            if entry.get("notes"):
                extras.append(f"Notes: {entry.get('notes')}")
            if extras:
                worker_line += " (" + "; ".join(extras) + ")"
            lines.append(worker_line)
        return " | ".join(lines)

    export_title = "LDA Group - Weekly Job Schedule" if group_by == "job" else "LDA Group - Weekly Worker Schedule"
    first_column = "Job" if group_by == "job" else "Worker"

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
            Paragraph(export_title, styles["Title"]),
            Paragraph(f"{start_date} to {end_date}", styles["Normal"]),
            Spacer(1, 0.4*cm),
        ]

        headers = [first_column] + [datetime.fromisoformat(day).strftime("%a %d %b") for day in date_list]
        table_data = [headers]

        if group_by == "job":
            for job in jobs:
                row_title_parts = [job.get("name", "Unknown")]
                if job.get("client"):
                    row_title_parts.append(job.get("client"))
                if job.get("location"):
                    row_title_parts.append(job.get("location"))
                row = [Paragraph("<br/>".join(row_title_parts), styles["BodyText"])]
                for day in date_list:
                    row.append(Paragraph(job_cell_text(job.get("id"), day).replace(" | ", "<br/>"), styles["BodyText"]))
                table_data.append(row)
        else:
            for worker in workers:
                row = [worker.get("name", "Unknown")]
                for day in date_list:
                    text = worker_cell_text(worker.get("id"), day).replace(" | ", "<br/>")
                    row.append(Paragraph(text, styles["BodyText"]))
                table_data.append(row)

        if len(table_data) == 1:
            empty_label = "No scheduled jobs" if group_by == "job" else "No selected workers"
            table_data.append([empty_label] + ["" for _ in date_list])

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
        filename = f"{group_by}_schedule_{start_date}_to_{end_date}.pdf"
        return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([export_title])
    writer.writerow(["Date range", start_date, "to", end_date])
    writer.writerow([])
    writer.writerow([first_column] + [datetime.fromisoformat(day).strftime("%a %d %b %Y") for day in date_list])

    if group_by == "job":
        for job in jobs:
            job_label_parts = [job.get("name", "Unknown")]
            if job.get("client"):
                job_label_parts.append(job.get("client"))
            if job.get("location"):
                job_label_parts.append(job.get("location"))
            job_label = " | ".join(job_label_parts)
            writer.writerow([job_label] + [job_cell_text(job.get("id"), day) for day in date_list])
    else:
        for worker in workers:
            writer.writerow([worker.get("name", "Unknown")] + [worker_cell_text(worker.get("id"), day) for day in date_list])

    output.seek(0)
    filename = f"{group_by}_schedule_{start_date}_to_{end_date}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )



# ==================== FINANCE SECTION ENDPOINTS ====================

def finance_to_number(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def parse_iso_date_safe(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except Exception:
        return None


def section_finance_values(section: Dict[str, Any]) -> Dict[str, float]:
    labour = finance_to_number(section.get("labour_value"))
    material = finance_to_number(section.get("material_value"))
    subcontractor = finance_to_number(section.get("subcontractor_value"))
    other = finance_to_number(section.get("other_value"))
    calculated_total = labour + material + subcontractor + other
    stored_total = finance_to_number(section.get("section_value") or section.get("total_value") or section.get("value"))
    total = calculated_total if calculated_total > 0 else stored_total
    progress = max(0.0, min(100.0, finance_to_number(section.get("progress_percent"))))
    earned = total * (progress / 100.0)
    return {
        "labour_value": round(labour, 2),
        "material_value": round(material, 2),
        "subcontractor_value": round(subcontractor, 2),
        "other_value": round(other, 2),
        "section_value": round(total, 2),
        "progress_percent": round(progress, 2),
        "earned_value": round(earned, 2),
        "remaining_value": round(max(0.0, total - earned), 2),
    }


def section_planned_value_by_date(section: Dict[str, Any], marker_date: Optional[date]) -> float:
    if not marker_date:
        return 0.0
    values = section_finance_values(section)
    section_value = values["section_value"]
    if section_value <= 0:
        return 0.0
    start = parse_iso_date_safe(section.get("start_date"))
    end = parse_iso_date_safe(section.get("end_date")) or start
    if not start or not end:
        return 0.0
    if end < start:
        start, end = end, start
    if marker_date < start:
        return 0.0
    if marker_date >= end:
        return section_value
    total_days = max(1, (end - start).days + 1)
    days_to_marker = max(0, (marker_date - start).days + 1)
    ratio = max(0.0, min(1.0, days_to_marker / total_days))
    return round(section_value * ratio, 2)


def normalise_finance_marker(marker: Dict[str, Any]) -> Dict[str, Any]:
    marker_type = str(marker.get("type") or marker.get("marker_type") or "application").strip().lower()
    marker_id = marker.get("id") or str(uuid.uuid4())
    label = marker.get("label") or marker.get("name") or marker_type.replace("_", " ").title()
    return {
        **marker,
        "id": marker_id,
        "type": marker_type,
        "label": label,
        "date": marker.get("date") or marker.get("marker_date") or "",
        "value_mode": marker.get("value_mode") or "auto",
        "manual_value": finance_to_number(marker.get("manual_value")),
        "notes": marker.get("notes") or "",
    }


async def build_finance_project_summary(job_id: str) -> Dict[str, Any]:
    job = await db.jobs.find_one({"id": job_id, "archived": {"$ne": True}}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    sections = []
    for section in job.get("gantt_sections") or []:
        values = section_finance_values(section)
        sections.append({
            "id": section.get("id"),
            "name": section.get("name", "Section"),
            "start_date": section.get("start_date", ""),
            "end_date": section.get("end_date", ""),
            "status": section.get("status", ""),
            **values,
        })

    records = await db.finance_records.find({"job_id": job_id, "archived": {"$ne": True}}, {"_id": 0}).to_list(1000)
    total_value = round(sum(item["section_value"] for item in sections), 2)
    earned_value = round(sum(item["earned_value"] for item in sections), 2)
    remaining_value = round(max(0.0, total_value - earned_value), 2)
    submitted_to_date = round(sum(finance_to_number(item.get("submitted_value")) for item in records), 2)
    certified_to_date = round(sum(finance_to_number(item.get("certified_value")) for item in records), 2)
    invoiced_to_date = round(sum(finance_to_number(item.get("invoice_value")) for item in records), 2)
    paid_to_date = round(sum(finance_to_number(item.get("paid_value")) for item in records), 2)
    retention_held = round(sum(finance_to_number(item.get("retention_value")) for item in records if not item.get("retention_paid_date")), 2)
    outstanding = round(max(0.0, invoiced_to_date - paid_to_date), 2)

    markers = [normalise_finance_marker(marker) for marker in (job.get("commercial_markers") or [])]
    application_forecast = []
    for marker in markers:
        if marker.get("type") != "application":
            continue
        marker_date = parse_iso_date_safe(marker.get("date"))
        planned = round(sum(section_planned_value_by_date(section, marker_date) for section in (job.get("gantt_sections") or [])), 2)
        manual_value = finance_to_number(marker.get("manual_value"))
        value_mode = marker.get("value_mode") or "auto"
        forecast_value = manual_value if value_mode == "manual" and manual_value > 0 else planned
        linked_records = [record for record in records if record.get("application_marker_id") == marker.get("id")]
        submitted = round(sum(finance_to_number(item.get("submitted_value")) for item in linked_records), 2)
        certified = round(sum(finance_to_number(item.get("certified_value")) for item in linked_records), 2)
        invoiced = round(sum(finance_to_number(item.get("invoice_value")) for item in linked_records), 2)
        paid = round(sum(finance_to_number(item.get("paid_value")) for item in linked_records), 2)
        shortfall = round(max(0.0, forecast_value - earned_value), 2)
        application_forecast.append({
            "marker_id": marker.get("id"),
            "label": marker.get("label"),
            "date": marker.get("date"),
            "value_mode": value_mode,
            "planned_value": planned,
            "forecast_value": round(forecast_value, 2),
            "earned_value": earned_value,
            "shortfall": shortfall,
            "suggested_claim": round(min(earned_value, forecast_value), 2),
            "submitted_value": submitted,
            "certified_value": certified,
            "invoice_value": invoiced,
            "paid_value": paid,
            "status": "at_risk" if shortfall > 0 else "on_track",
        })
    application_forecast.sort(key=lambda item: item.get("date") or "")

    next_application = None
    today = datetime.utcnow().date()
    future_apps = [item for item in application_forecast if parse_iso_date_safe(item.get("date")) and parse_iso_date_safe(item.get("date")) >= today]
    if future_apps:
        next_application = future_apps[0]
    elif application_forecast:
        next_application = application_forecast[-1]

    return {
        "job": {
            "id": job.get("id"),
            "name": job.get("name"),
            "client": job.get("client", ""),
            "location": job.get("location", ""),
            "quoted_cost": job.get("quoted_cost", 0),
            "planned_start_date": job.get("planned_start_date"),
            "planned_end_date": job.get("planned_end_date"),
            "status": job.get("status", "active"),
        },
        "sections": sections,
        "markers": markers,
        "application_forecast": application_forecast,
        "next_application": next_application,
        "records": records,
        "summary": {
            "contract_value": total_value,
            "earned_value": earned_value,
            "remaining_value": remaining_value,
            "submitted_to_date": submitted_to_date,
            "certified_to_date": certified_to_date,
            "invoiced_to_date": invoiced_to_date,
            "paid_to_date": paid_to_date,
            "retention_held": retention_held,
            "outstanding": outstanding,
            "application_risk": next_application.get("shortfall", 0) if next_application else 0,
        },
    }


@api_router.get("/finance/projects")
async def get_finance_projects(admin: str = Depends(verify_admin)):
    """Return active projects that can be reviewed in the Finance section."""
    jobs = await db.jobs.find({"archived": {"$ne": True}}, {"_id": 0}).sort("name", 1).to_list(1000)
    result = []
    for job in jobs:
        sections = job.get("gantt_sections") or []
        section_value = round(sum(section_finance_values(section)["section_value"] for section in sections), 2)
        earned_value = round(sum(section_finance_values(section)["earned_value"] for section in sections), 2)
        result.append({
            "id": job.get("id"),
            "name": job.get("name"),
            "client": job.get("client", ""),
            "location": job.get("location", ""),
            "status": job.get("status", "active"),
            "include_in_gantt": job.get("include_in_gantt", False),
            "section_count": len(sections),
            "section_value": section_value,
            "earned_value": earned_value,
            "commercial_marker_count": len(job.get("commercial_markers") or []),
        })
    return result


@api_router.get("/finance/project/{job_id}/summary")
async def get_finance_project_summary(job_id: str, admin: str = Depends(verify_admin)):
    return await build_finance_project_summary(job_id)


@api_router.get("/finance/project/{job_id}/records")
async def get_finance_records(job_id: str, admin: str = Depends(verify_admin)):
    records = await db.finance_records.find({"job_id": job_id, "archived": {"$ne": True}}, {"_id": 0}).sort("created_date", -1).to_list(1000)
    return records


@api_router.post("/finance/records", response_model=FinanceRecord)
async def create_finance_record(record: FinanceRecordCreate, admin: str = Depends(verify_admin)):
    job = await db.jobs.find_one({"id": record.job_id, "archived": {"$ne": True}})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    record_dict = record.dict()
    if finance_to_number(record_dict.get("retention_value")) <= 0 and finance_to_number(record_dict.get("retention_percent")) > 0:
        base_value = finance_to_number(record_dict.get("invoice_value")) or finance_to_number(record_dict.get("certified_value")) or finance_to_number(record_dict.get("submitted_value"))
        record_dict["retention_value"] = round(base_value * (finance_to_number(record_dict.get("retention_percent")) / 100.0), 2)
    record_obj = FinanceRecord(**record_dict)
    await db.finance_records.insert_one(record_obj.dict())
    return record_obj


@api_router.put("/finance/records/{record_id}", response_model=FinanceRecord)
async def update_finance_record(record_id: str, record_update: FinanceRecordUpdate, admin: str = Depends(verify_admin)):
    existing = await db.finance_records.find_one({"id": record_id, "archived": {"$ne": True}})
    if not existing:
        raise HTTPException(status_code=404, detail="Finance record not found")
    update_dict = {k: v for k, v in record_update.dict().items() if v is not None}
    if update_dict:
        base_value = finance_to_number(update_dict.get("invoice_value", existing.get("invoice_value"))) or finance_to_number(update_dict.get("certified_value", existing.get("certified_value"))) or finance_to_number(update_dict.get("submitted_value", existing.get("submitted_value")))
        retention_percent = finance_to_number(update_dict.get("retention_percent", existing.get("retention_percent")))
        if "retention_value" not in update_dict and retention_percent > 0 and base_value > 0:
            update_dict["retention_value"] = round(base_value * (retention_percent / 100.0), 2)
        update_dict["updated_date"] = datetime.utcnow()
        result = await db.finance_records.update_one({"id": record_id}, {"$set": update_dict})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Finance record not found")
    updated = await db.finance_records.find_one({"id": record_id}, {"_id": 0})
    return FinanceRecord(**updated)


@api_router.delete("/finance/records/{record_id}")
async def delete_finance_record(record_id: str, admin: str = Depends(verify_admin)):
    result = await db.finance_records.update_one({"id": record_id}, {"$set": {"archived": True, "updated_date": datetime.utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Finance record not found")
    return {"message": "Finance record archived successfully"}


@api_router.get("/finance/project/{job_id}/export.csv")
async def export_finance_project_csv(job_id: str, admin: str = Depends(verify_admin)):
    data = await build_finance_project_summary(job_id)
    output = io.StringIO()
    writer = csv.writer(output)
    job = data["job"]
    summary = data["summary"]
    writer.writerow(["LDA Group - Finance Summary"])
    writer.writerow(["Project", job.get("name", "")])
    writer.writerow(["Client", job.get("client", "")])
    writer.writerow([])
    writer.writerow(["Contract Value", summary["contract_value"]])
    writer.writerow(["Earned Value", summary["earned_value"]])
    writer.writerow(["Remaining Value", summary["remaining_value"]])
    writer.writerow(["Submitted To Date", summary["submitted_to_date"]])
    writer.writerow(["Certified To Date", summary["certified_to_date"]])
    writer.writerow(["Invoiced To Date", summary["invoiced_to_date"]])
    writer.writerow(["Paid To Date", summary["paid_to_date"]])
    writer.writerow(["Outstanding", summary["outstanding"]])
    writer.writerow(["Retention Held", summary["retention_held"]])
    writer.writerow([])
    writer.writerow(["Section", "Start", "End", "Labour", "Materials", "Subcontractor", "Other", "Total", "Progress %", "Earned", "Remaining"])
    for section in data["sections"]:
        writer.writerow([section.get("name"), section.get("start_date"), section.get("end_date"), section.get("labour_value"), section.get("material_value"), section.get("subcontractor_value"), section.get("other_value"), section.get("section_value"), section.get("progress_percent"), section.get("earned_value"), section.get("remaining_value")])
    writer.writerow([])
    writer.writerow(["Application", "Date", "Planned", "Earned", "Shortfall", "Suggested Claim", "Submitted", "Certified", "Invoiced", "Paid", "Status"])
    for app in data["application_forecast"]:
        writer.writerow([app.get("label"), app.get("date"), app.get("forecast_value"), app.get("earned_value"), app.get("shortfall"), app.get("suggested_claim"), app.get("submitted_value"), app.get("certified_value"), app.get("invoice_value"), app.get("paid_value"), app.get("status")])
    output.seek(0)
    filename = f"finance_{str(job.get('name', 'project')).replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(io.BytesIO(output.getvalue().encode("utf-8-sig")), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})



# ==================== COMPANY FINANCE DASHBOARD ENDPOINTS ====================
# These routes power the new company-level finance dashboard.
# They intentionally use a separate MongoDB collection from the existing
# project application finance records so the older project finance workflow is preserved.

class DashboardFinanceRecordBase(BaseModel):
    project_id: Optional[str] = None
    project_name: Optional[str] = None

    # deposit, interim, final, retention, variation, other
    type: str = "interim"

    description: Optional[str] = None

    expected_date: Optional[str] = None
    expected_amount: float = 0.0

    anticipated_date: Optional[str] = None
    anticipated_amount: Optional[float] = None

    # expected, anticipated, at_risk, received, overdue
    status: str = "expected"

    received_date: Optional[str] = None
    received_amount: Optional[float] = None

    notes: Optional[str] = None

    # Links dashboard tracking records back to Gantt commercial markers so
    # the Finance page can supersede the original planned marker once tracked.
    linked_marker_id: Optional[str] = None
    source_marker_id: Optional[str] = None

    # Lightweight audit fields. The frontend sends the logged-in user details
    # where available, and the backend preserves them.
    created_by: Optional[str] = None
    created_by_role: Optional[str] = None
    updated_by: Optional[str] = None
    updated_by_role: Optional[str] = None


class DashboardFinanceRecordCreate(DashboardFinanceRecordBase):
    pass


class DashboardFinanceRecordUpdate(BaseModel):
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None

    expected_date: Optional[str] = None
    expected_amount: Optional[float] = None

    anticipated_date: Optional[str] = None
    anticipated_amount: Optional[float] = None

    status: Optional[str] = None

    received_date: Optional[str] = None
    received_amount: Optional[float] = None

    notes: Optional[str] = None
    linked_marker_id: Optional[str] = None
    source_marker_id: Optional[str] = None
    created_by: Optional[str] = None
    created_by_role: Optional[str] = None
    updated_by: Optional[str] = None
    updated_by_role: Optional[str] = None
    archived: Optional[bool] = None


def dashboard_finance_to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def serialize_dashboard_finance_record(record: Dict[str, Any]) -> Dict[str, Any]:
    if not record:
        return {}

    return {
        "id": record.get("id"),
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "type": record.get("type", "interim"),
        "description": record.get("description"),
        "expected_date": record.get("expected_date"),
        "expected_amount": dashboard_finance_to_float(record.get("expected_amount")),
        "anticipated_date": record.get("anticipated_date"),
        "anticipated_amount": (
            dashboard_finance_to_float(record.get("anticipated_amount"))
            if record.get("anticipated_amount") is not None
            else None
        ),
        "status": record.get("status", "expected"),
        "received_date": record.get("received_date"),
        "received_amount": (
            dashboard_finance_to_float(record.get("received_amount"))
            if record.get("received_amount") is not None
            else None
        ),
        "notes": record.get("notes"),
        "linked_marker_id": record.get("linked_marker_id"),
        "source_marker_id": record.get("source_marker_id"),
        "created_by": record.get("created_by"),
        "created_by_role": record.get("created_by_role"),
        "updated_by": record.get("updated_by"),
        "updated_by_role": record.get("updated_by_role"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "archived": record.get("archived", False),
    }


def calculate_dashboard_finance_status(record: Dict[str, Any]) -> str:
    status = record.get("status") or "expected"

    if status == "received":
        return "received"

    expected_date = parse_iso_date_safe(record.get("expected_date"))
    anticipated_date = parse_iso_date_safe(record.get("anticipated_date"))
    due_date = anticipated_date or expected_date
    today = datetime.utcnow().date()

    if due_date and due_date < today:
        return "overdue"

    return status


async def backfill_dashboard_project_name(data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("project_id") and not data.get("project_name"):
        job = await db.jobs.find_one({"id": data["project_id"]}, {"_id": 0})
        if job:
            data["project_name"] = (
                job.get("name")
                or job.get("job_name")
                or job.get("address")
                or job.get("location")
                or "Unnamed project"
            )
    return data


@api_router.get("/finance-records")
async def get_dashboard_finance_records(
    project_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    query: Dict[str, Any] = {"archived": {"$ne": True}}

    if project_id:
        query["project_id"] = project_id

    if status:
        query["status"] = status

    if type:
        query["type"] = type

    if start_date or end_date:
        date_query: Dict[str, Any] = {}

        if start_date:
            date_query["$gte"] = start_date

        if end_date:
            date_query["$lte"] = end_date

        query["expected_date"] = date_query

    records = await db.finance_dashboard_records.find(query, {"_id": 0}).sort("expected_date", 1).to_list(2000)

    output = []
    for record in records:
        serialized = serialize_dashboard_finance_record(record)
        serialized["status"] = calculate_dashboard_finance_status(serialized)
        output.append(serialized)

    return output


@api_router.post("/finance-records")
async def create_dashboard_finance_record(record: DashboardFinanceRecordCreate):
    now = datetime.utcnow().isoformat()

    data = record.dict()
    data["id"] = str(uuid.uuid4())
    data["created_at"] = now
    data["updated_at"] = now
    data["archived"] = False

    created_by = (data.get("created_by") or "").strip()
    created_by_role = (data.get("created_by_role") or "").strip()
    data["created_by"] = created_by or "Unknown user"
    data["created_by_role"] = created_by_role or "unknown"
    data["updated_by"] = (data.get("updated_by") or data["created_by"]).strip() or data["created_by"]
    data["updated_by_role"] = (data.get("updated_by_role") or data["created_by_role"]).strip() or data["created_by_role"]

    if data.get("anticipated_amount") is None:
        data["anticipated_amount"] = data.get("expected_amount", 0)

    if not data.get("anticipated_date"):
        data["anticipated_date"] = data.get("expected_date")

    data = await backfill_dashboard_project_name(data)

    await db.finance_dashboard_records.insert_one(data)

    serialized = serialize_dashboard_finance_record(data)
    serialized["status"] = calculate_dashboard_finance_status(serialized)
    return serialized


@api_router.put("/finance-records/{record_id}")
async def update_dashboard_finance_record(record_id: str, update: DashboardFinanceRecordUpdate):
    existing = await db.finance_dashboard_records.find_one({"id": record_id, "archived": {"$ne": True}})

    if not existing:
        raise HTTPException(status_code=404, detail="Finance record not found")

    update_data = {
        key: value
        for key, value in update.dict().items()
        if value is not None
    }

    update_data["updated_at"] = datetime.utcnow().isoformat()

    # Do not accidentally blank out audit fields when the frontend has no user context.
    for audit_key in ["created_by", "created_by_role", "updated_by", "updated_by_role"]:
        if audit_key in update_data and (update_data[audit_key] is None or str(update_data[audit_key]).strip() == ""):
            update_data.pop(audit_key, None)

    if not update_data.get("updated_by"):
        update_data["updated_by"] = "Unknown user"
    if not update_data.get("updated_by_role"):
        update_data["updated_by_role"] = "unknown"

    if update_data.get("project_id") and not update_data.get("project_name"):
        update_data = await backfill_dashboard_project_name(update_data)

    await db.finance_dashboard_records.update_one(
        {"id": record_id},
        {"$set": update_data}
    )

    updated = await db.finance_dashboard_records.find_one({"id": record_id}, {"_id": 0})
    serialized = serialize_dashboard_finance_record(updated)
    serialized["status"] = calculate_dashboard_finance_status(serialized)

    return serialized


@api_router.delete("/finance-records/{record_id}")
async def delete_dashboard_finance_record(record_id: str):
    result = await db.finance_dashboard_records.update_one(
        {"id": record_id, "archived": {"$ne": True}},
        {"$set": {"archived": True, "updated_at": datetime.utcnow().isoformat()}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Finance record not found")

    return {"success": True, "message": "Finance record deleted"}


@api_router.get("/finance-dashboard")
async def get_company_finance_dashboard():
    today = datetime.utcnow().date()
    lookahead_end = today + timedelta(days=28)

    # Include past unpaid records so overdue money is visible in the summary,
    # while the forecast grid itself remains a 4-week lookahead.
    records = await db.finance_dashboard_records.find({
        "archived": {"$ne": True},
        "expected_date": {"$lte": lookahead_end.isoformat()},
    }, {"_id": 0}).sort("expected_date", 1).to_list(2000)

    all_records = []

    for record in records:
        serialized = serialize_dashboard_finance_record(record)
        serialized["status"] = calculate_dashboard_finance_status(serialized)
        all_records.append(serialized)

    weeks = []

    for i in range(4):
        week_start = today + timedelta(days=i * 7)
        week_end = week_start + timedelta(days=6)

        week_records = []

        for record in all_records:
            record_date = parse_iso_date_safe(
                record.get("anticipated_date") or record.get("expected_date")
            )

            if record_date and week_start <= record_date <= week_end:
                week_records.append(record)

        expected_total = sum(
            dashboard_finance_to_float(r.get("expected_amount"))
            for r in week_records
        )

        anticipated_total = sum(
            dashboard_finance_to_float(r.get("anticipated_amount"), dashboard_finance_to_float(r.get("expected_amount")))
            for r in week_records
        )

        received_total = sum(
            dashboard_finance_to_float(r.get("received_amount"))
            for r in week_records
            if r.get("status") == "received"
        )

        at_risk_total = sum(
            dashboard_finance_to_float(r.get("anticipated_amount"), dashboard_finance_to_float(r.get("expected_amount")))
            for r in week_records
            if r.get("status") == "at_risk"
        )

        overdue_total = sum(
            dashboard_finance_to_float(r.get("anticipated_amount"), dashboard_finance_to_float(r.get("expected_amount")))
            for r in week_records
            if r.get("status") == "overdue"
        )

        weeks.append({
            "week_index": i + 1,
            "start_date": week_start.isoformat(),
            "end_date": week_end.isoformat(),
            "expected_total": round(expected_total, 2),
            "anticipated_total": round(anticipated_total, 2),
            "received_total": round(received_total, 2),
            "at_risk_total": round(at_risk_total, 2),
            "overdue_total": round(overdue_total, 2),
            "records": week_records,
        })

    overdue_records = [record for record in all_records if record.get("status") == "overdue"]
    received_records = [record for record in all_records if record.get("status") == "received"]
    at_risk_records = [record for record in all_records if record.get("status") == "at_risk"]

    future_records = []
    for record in all_records:
        record_date = parse_iso_date_safe(record.get("anticipated_date") or record.get("expected_date"))
        if record_date and today <= record_date <= lookahead_end:
            future_records.append(record)

    summary = {
        "expected_next_4_weeks": round(sum(dashboard_finance_to_float(r.get("expected_amount")) for r in future_records), 2),
        "anticipated_next_4_weeks": round(sum(dashboard_finance_to_float(r.get("anticipated_amount"), dashboard_finance_to_float(r.get("expected_amount"))) for r in future_records), 2),
        "received_next_4_weeks": round(sum(dashboard_finance_to_float(r.get("received_amount")) for r in received_records), 2),
        "at_risk_next_4_weeks": round(sum(dashboard_finance_to_float(r.get("anticipated_amount"), dashboard_finance_to_float(r.get("expected_amount"))) for r in at_risk_records), 2),
        "overdue_next_4_weeks": round(sum(dashboard_finance_to_float(r.get("anticipated_amount"), dashboard_finance_to_float(r.get("expected_amount"))) for r in overdue_records), 2),
        "record_count": len(all_records),
    }

    return {
        "summary": summary,
        "weeks": weeks,
        "records": all_records,
    }

# ==================== PURCHASE ORDER SYSTEM ====================

def clean_mongo_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


def calculate_po_line_totals(line: Dict[str, Any]) -> Dict[str, Any]:
    quantity = float(line.get("quantity") or 0)
    unit_cost = float(line.get("unit_cost") or 0)
    vat_rate = float(line.get("vat_rate") or 0)
    net_total = round(quantity * unit_cost, 2)
    vat_total = round(net_total * (vat_rate / 100), 2)
    gross_total = round(net_total + vat_total, 2)
    line["quantity"] = quantity
    line["unit_cost"] = unit_cost
    line["vat_rate"] = vat_rate
    line["net_total"] = net_total
    line["vat_total"] = vat_total
    line["gross_total"] = gross_total
    line.setdefault("id", str(uuid.uuid4()))
    line.setdefault("received_quantity", 0.0)
    line.setdefault("material_status", "committed")
    return line


def calculate_po_totals(po_dict: Dict[str, Any]) -> Dict[str, Any]:
    lines = [calculate_po_line_totals(dict(line)) for line in po_dict.get("lines", [])]
    po_dict["lines"] = lines
    po_dict["net_total"] = round(sum(line.get("net_total", 0) for line in lines), 2)
    po_dict["vat_total"] = round(sum(line.get("vat_total", 0) for line in lines), 2)
    po_dict["gross_total"] = round(sum(line.get("gross_total", 0) for line in lines), 2)
    return po_dict


async def next_po_number() -> str:
    year = datetime.utcnow().year
    prefix = f"PO-{year}-"
    latest = await db.purchase_orders.find_one({"po_number": {"$regex": f"^{prefix}"}}, sort=[("po_number", -1)])
    if latest and latest.get("po_number"):
        try:
            next_number = int(latest["po_number"].split("-")[-1]) + 1
        except Exception:
            next_number = 1
    else:
        next_number = 1
    return f"{prefix}{str(next_number).zfill(4)}"


def normalise_quote_text(text: str) -> str:
    """Clean extracted quote text while preserving useful line breaks."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\u00a0]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_money_value(value: Any) -> Optional[float]:
    """Parse UK money strings like £1,234.56 into floats."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip()
    cleaned = cleaned.replace("£", "").replace(",", "").replace(" ", "")
    cleaned = cleaned.replace("GBP", "").replace("gbp", "")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if cleaned in {"", ".", "-"}:
        return None
    try:
        return round(float(cleaned), 2)
    except Exception:
        return None


def extract_quote_number(text: str) -> str:
    cleaned_text = normalise_quote_text(text)
    patterns = [
        r"(?:quote|quotation|estimate)\s*(?:number|no\.?|ref|reference)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
        r"(?:quote|quotation|estimate)\s+([A-Z0-9][A-Z0-9\-/]{2,})",
        r"(?:ref|reference)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned_text, re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip(".,;:")
            if not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", value):
                return value
    return ""


def extract_first_date_for_patterns(text: str, labels: List[str]) -> str:
    cleaned_text = normalise_quote_text(text)
    date_pattern = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})"
    for label in labels:
        pattern = rf"{label}\s*[:#-]?\s*{date_pattern}"
        match = re.search(pattern, cleaned_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def extract_email_from_text(text: str) -> str:
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text or "", re.IGNORECASE)
    return match.group(0).strip() if match else ""


def extract_supplier_name_from_text(text: str) -> str:
    """Best-effort supplier name extraction from the first useful lines of a quote."""
    cleaned_text = normalise_quote_text(text)
    lines = [line.strip() for line in cleaned_text.splitlines() if line.strip()]
    skip_terms = [
        "quote", "quotation", "estimate", "invoice", "date", "page", "tel", "phone",
        "email", "vat", "company reg", "account", "delivery", "address", "customer",
        "subtotal", "total", "amount", "qty", "quantity", "unit", "price",
    ]
    for line in lines[:18]:
        lower = line.lower()
        if any(term in lower for term in skip_terms):
            continue
        if "@" in line or re.search(r"£|\d+\.\d{2}", line):
            continue
        if len(line) < 3 or len(line) > 90:
            continue
        # Prefer company-looking lines, but still allow a simple trading name.
        return line.strip(" -|,.")
    return ""


def extract_quote_totals(text: str) -> Dict[str, Optional[float]]:
    cleaned_text = normalise_quote_text(text)
    result = {"net_total": None, "vat_total": None, "gross_total": None}
    money = r"£?\s*([0-9]+(?:,[0-9]{3})*(?:\.\d{2})?)"
    patterns = {
        "net_total": [
            rf"(?:sub\s*total|subtotal|net\s*total|goods\s*total|total\s*net)\s*[:\-]?\s*{money}",
        ],
        "vat_total": [
            rf"(?:vat|v\.a\.t\.|tax)\s*(?:total|amount)?\s*[:\-]?\s*{money}",
        ],
        "gross_total": [
            rf"(?:grand\s*total|total\s*due|amount\s*due|gross\s*total|total\s*inc\.?\s*vat|total\s*including\s*vat)\s*[:\-]?\s*{money}",
            rf"(?:^|\n)\s*total\s*[:\-]?\s*{money}",
        ],
    }
    for key, key_patterns in patterns.items():
        for pattern in key_patterns:
            matches = re.findall(pattern, cleaned_text, flags=re.IGNORECASE | re.MULTILINE)
            if matches:
                # Use the final occurrence as totals often appear at the bottom.
                value = parse_money_value(matches[-1] if isinstance(matches[-1], str) else matches[-1][0])
                if value is not None:
                    result[key] = value
                    break
    if result["gross_total"] is None and result["net_total"] is not None and result["vat_total"] is not None:
        result["gross_total"] = round(result["net_total"] + result["vat_total"], 2)
    if result["vat_total"] is None and result["gross_total"] is not None and result["net_total"] is not None:
        result["vat_total"] = round(result["gross_total"] - result["net_total"], 2)
    return result


def parse_quote_lines_from_text(text: str) -> List[Dict[str, Any]]:
    """Best-effort quote line extraction. Always requires review before PO creation."""
    cleaned_text = normalise_quote_text(text)
    parsed_lines: List[Dict[str, Any]] = []
    money_value = r"£?\s*[0-9]+(?:,[0-9]{3})*(?:\.\d{2})?"
    skip_terms = [
        "subtotal", "sub total", "vat", "total", "balance", "amount due", "grand total",
        "quote", "quotation", "estimate", "invoice", "terms", "payment", "bank", "sort code",
        "account", "delivery", "address", "page", "email", "telephone", "phone",
    ]

    for raw_line in cleaned_text.splitlines():
        cleaned = " ".join(raw_line.strip().split())
        if len(cleaned) < 8:
            continue
        lower = cleaned.lower()
        if any(term in lower for term in skip_terms):
            continue
        if not re.search(r"\d", cleaned) or not re.search(money_value, cleaned):
            continue

        # Pattern: description qty unit-price line-total
        structured = re.match(
            rf"^(?P<description>.+?)\s+(?P<quantity>\d+(?:\.\d+)?)\s+(?P<unit>{money_value})\s+(?P<total>{money_value})$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if structured:
            description = structured.group("description").strip(" -|\t")
            quantity = parse_money_value(structured.group("quantity")) or 1
            unit_cost = parse_money_value(structured.group("unit")) or 0
            line_total = parse_money_value(structured.group("total")) or 0
            # If unit * qty differs significantly from final total, use total / qty as the safer unit cost.
            if quantity and abs((quantity * unit_cost) - line_total) > 0.05:
                unit_cost = round(line_total / quantity, 2)
            if description and unit_cost > 0:
                parsed_lines.append({
                    "description": description[:220],
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                    "vat_rate": 20,
                    "cost_category": "Materials",
                })
                if len(parsed_lines) >= 60:
                    break
                continue

        amounts = re.findall(money_value, cleaned, flags=re.IGNORECASE)
        if not amounts:
            continue
        line_total = parse_money_value(amounts[-1])
        if line_total is None or line_total <= 0:
            continue
        description = re.sub(money_value, " ", cleaned, flags=re.IGNORECASE)
        description = re.sub(r"\s{2,}", " ", description).strip(" -|\t")
        # Avoid creating lines that are just codes or column headers.
        if len(description) < 3 or description.lower() in {"qty", "quantity", "unit", "price"}:
            continue
        parsed_lines.append({
            "description": description[:220],
            "quantity": 1,
            "unit_cost": line_total,
            "vat_rate": 20,
            "cost_category": "Materials",
        })
        if len(parsed_lines) >= 60:
            break

    # De-duplicate identical description/value rows caused by PDF extraction artefacts.
    unique_lines = []
    seen = set()
    for line in parsed_lines:
        key = (line.get("description", "").lower(), float(line.get("quantity") or 0), float(line.get("unit_cost") or 0))
        if key in seen:
            continue
        seen.add(key)
        unique_lines.append(line)
    return unique_lines


async def extract_text_from_upload(file: UploadFile, content: bytes) -> str:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    if filename.endswith(".pdf") or "pdf" in content_type:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            return normalise_quote_text("\n".join(page.extract_text() or "" for page in reader.pages))
        except Exception as exc:
            logger.warning("PDF text extraction failed: %s", exc)
            return ""
    if filename.endswith(".docx") or "wordprocessingml" in content_type:
        try:
            from docx import Document
            document = Document(io.BytesIO(content))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
            for table in document.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells if cell.text.strip()))
            return normalise_quote_text("\n".join(parts))
        except Exception as exc:
            logger.warning("DOCX text extraction failed: %s", exc)
            return ""
    if filename.endswith((".txt", ".csv")) or "text" in content_type or "csv" in content_type:
        try:
            return normalise_quote_text(content.decode("utf-8", errors="ignore"))
        except Exception:
            return ""
    # JPG/PNG scanned quote OCR is deliberately not attempted in this patch.
    return ""


async def match_supplier_from_quote(supplier_name: str, supplier_email: str) -> Dict[str, Any]:
    suppliers = await db.suppliers.find({"archived": {"$ne": True}}, {"_id": 0}).to_list(1000)
    supplier_name_norm = (supplier_name or "").strip().lower()
    supplier_email_norm = (supplier_email or "").strip().lower()
    supplier_domain = supplier_email_norm.split("@")[-1] if "@" in supplier_email_norm else ""

    best_match = None
    best_score = 0
    for supplier in suppliers:
        score = 0
        saved_name = (supplier.get("name") or "").strip().lower()
        saved_emails = [
            (supplier.get("orders_email") or "").strip().lower(),
            (supplier.get("accounts_email") or "").strip().lower(),
        ]
        saved_domains = [email.split("@")[-1] for email in saved_emails if "@" in email]
        if supplier_email_norm and supplier_email_norm in saved_emails:
            score += 100
        if supplier_domain and supplier_domain in saved_domains:
            score += 60
        if supplier_name_norm and saved_name:
            if supplier_name_norm == saved_name:
                score += 90
            elif supplier_name_norm in saved_name or saved_name in supplier_name_norm:
                score += 55
        if score > best_score:
            best_score = score
            best_match = supplier
    if best_match and best_score >= 50:
        return {"matched_supplier_id": best_match.get("id"), "matched_supplier_name": best_match.get("name"), "match_score": best_score}
    return {"matched_supplier_id": None, "matched_supplier_name": "", "match_score": 0}


def generate_purchase_order_pdf_bytes(po: Dict[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except Exception as exc:
        logger.error("PO PDF dependency error: %s", exc)
        raise HTTPException(status_code=500, detail="PDF generation is not available on this server. Check reportlab is installed.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.2*cm, leftMargin=1.2*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("LDA Group - Purchase Order", styles["Title"]))
    story.append(Paragraph(f"<b>PO Number:</b> {po.get('po_number', '')}", styles["Normal"]))
    story.append(Paragraph(f"<b>Status:</b> {po.get('status', '').replace('_', ' ').title()}", styles["Normal"]))
    story.append(Paragraph(f"<b>Date:</b> {get_uk_time().strftime('%d/%m/%Y')}", styles["Normal"]))
    story.append(Spacer(1, 0.35*cm))

    detail_data = [
        [Paragraph("<b>Supplier</b>", styles["BodyText"]), Paragraph("<b>Job / Delivery</b>", styles["BodyText"])],
        [
            Paragraph(f"{po.get('supplier_name', '')}<br/>{po.get('supplier_email', '')}", styles["BodyText"]),
            Paragraph(f"{po.get('job_name', '')}<br/>{po.get('delivery_address') or ''}", styles["BodyText"]),
        ],
        [Paragraph(f"<b>Supplier Quote Ref:</b> {po.get('supplier_quote_number') or '-'}", styles["BodyText"]), Paragraph(f"<b>Required Date:</b> {po.get('required_date') or '-'}", styles["BodyText"])],
    ]
    detail_table = Table(detail_data, colWidths=[9*cm, 9*cm])
    detail_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(detail_table)
    story.append(Spacer(1, 0.45*cm))

    table_data = [["Description", "Qty", "Unit", "VAT %", "Net", "VAT", "Gross"]]
    for line in po.get("lines", []):
        table_data.append([
            Paragraph(str(line.get("description", "")), styles["BodyText"]),
            f"{line.get('quantity', 0):g}",
            f"£{line.get('unit_cost', 0):,.2f}",
            f"{line.get('vat_rate', 0):g}%",
            f"£{line.get('net_total', 0):,.2f}",
            f"£{line.get('vat_total', 0):,.2f}",
            f"£{line.get('gross_total', 0):,.2f}",
        ])
    table_data.extend([
        ["", "", "", "", "Net", "", f"£{po.get('net_total', 0):,.2f}"],
        ["", "", "", "", "VAT", "", f"£{po.get('vat_total', 0):,.2f}"],
        ["", "", "", "", "Gross", "", f"£{po.get('gross_total', 0):,.2f}"],
    ])
    line_table = Table(table_data, colWidths=[7*cm, 1.3*cm, 2*cm, 1.5*cm, 2*cm, 2*cm, 2.2*cm], repeatRows=1)
    line_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d01f2f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("BACKGROUND", (4, -3), (-1, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (4, -3), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(line_table)

    if po.get("notes"):
        story.append(Spacer(1, 0.45*cm))
        story.append(Paragraph("<b>Notes</b>", styles["Heading3"]))
        story.append(Paragraph(str(po.get("notes", "")).replace("\n", "<br/>"), styles["BodyText"]))

    story.append(Spacer(1, 0.45*cm))
    story.append(Paragraph("Please confirm receipt and advise expected delivery date.", styles["Normal"]))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


@api_router.get("/suppliers")
async def get_suppliers(include_archived: bool = Query(False), admin: str = Depends(verify_admin)):
    filter_dict = {} if include_archived else {"archived": {"$ne": True}}
    suppliers = await db.suppliers.find(filter_dict, {"_id": 0}).sort("name", 1).to_list(1000)
    return suppliers


@api_router.post("/suppliers", response_model=Supplier)
async def create_supplier(supplier: SupplierCreate, admin: str = Depends(verify_admin)):
    existing = await db.suppliers.find_one({"name": {"$regex": f"^{re.escape(supplier.name)}$", "$options": "i"}, "archived": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="A supplier with this name already exists")
    supplier_obj = Supplier(**supplier.dict())
    await db.suppliers.insert_one(supplier_obj.dict())
    return supplier_obj


@api_router.put("/suppliers/{supplier_id}", response_model=Supplier)
async def update_supplier(supplier_id: str, supplier_update: SupplierUpdate, admin: str = Depends(verify_admin)):
    update_dict = {k: v for k, v in supplier_update.dict().items() if v is not None}
    update_dict["updated_at"] = datetime.utcnow()
    result = await db.suppliers.update_one({"id": supplier_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Supplier not found")
    updated = await db.suppliers.find_one({"id": supplier_id})
    return Supplier(**updated)


@api_router.delete("/suppliers/{supplier_id}")
async def archive_supplier(supplier_id: str, admin: str = Depends(verify_admin)):
    result = await db.suppliers.update_one({"id": supplier_id}, {"$set": {"archived": True, "active": False, "updated_at": datetime.utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"message": "Supplier archived successfully"}


@api_router.get("/purchase-orders")
async def get_purchase_orders(
    status: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    supplier_id: Optional[str] = Query(None),
    include_cancelled: bool = Query(True),
    admin: str = Depends(verify_admin),
):
    filter_dict = {}
    if status:
        filter_dict["status"] = status
    elif not include_cancelled:
        filter_dict["status"] = {"$ne": "cancelled"}
    if job_id:
        filter_dict["job_id"] = job_id
    if supplier_id:
        filter_dict["supplier_id"] = supplier_id
    purchase_orders = await db.purchase_orders.find(filter_dict, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return purchase_orders


@api_router.get("/purchase-orders/{po_id}")
async def get_purchase_order(po_id: str, admin: str = Depends(verify_admin)):
    po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


@api_router.post("/purchase-orders", response_model=PurchaseOrder)
async def create_purchase_order(po_data: PurchaseOrderCreate, admin: str = Depends(verify_admin)):
    po_dict = po_data.dict()
    supplier = await db.suppliers.find_one({"id": po_data.supplier_id}) or {}
    job = await db.jobs.find_one({"id": po_data.job_id}) or {}
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    po_dict["po_number"] = await next_po_number()
    po_dict["supplier_name"] = po_dict.get("supplier_name") or supplier.get("name", "")
    po_dict["supplier_email"] = po_dict.get("supplier_email") or supplier.get("orders_email") or supplier.get("accounts_email") or ""
    po_dict["job_name"] = po_dict.get("job_name") or job.get("display_name") or job.get("name", "")
    po_dict["job_number"] = po_dict.get("job_number") or job.get("job_number")
    po_dict["division"] = po_dict.get("division") or job.get("division", "")
    po_dict["delivery_address"] = po_dict.get("delivery_address") or job.get("location", "")
    po_dict["requested_by_user_id"] = admin
    po_dict["requested_by_name"] = admin
    po_dict = calculate_po_totals(po_dict)

    po_obj = PurchaseOrder(**po_dict)
    await db.purchase_orders.insert_one(po_obj.dict())
    return po_obj


@api_router.put("/purchase-orders/{po_id}", response_model=PurchaseOrder)
async def update_purchase_order(po_id: str, po_update: PurchaseOrderUpdate, admin: str = Depends(verify_admin)):
    existing = await db.purchase_orders.find_one({"id": po_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    update_dict = {k: v for k, v in po_update.dict().items() if v is not None}
    if "lines" in update_dict:
        temp = calculate_po_totals({"lines": update_dict["lines"]})
        update_dict["lines"] = temp["lines"]
        update_dict["net_total"] = temp["net_total"]
        update_dict["vat_total"] = temp["vat_total"]
        update_dict["gross_total"] = temp["gross_total"]
    update_dict["updated_at"] = datetime.utcnow()
    result = await db.purchase_orders.update_one({"id": po_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    updated = await db.purchase_orders.find_one({"id": po_id})
    return PurchaseOrder(**updated)


@api_router.delete("/purchase-orders/{po_id}")
async def delete_purchase_order(po_id: str, admin: str = Depends(verify_admin)):
    result = await db.purchase_orders.delete_one({"id": po_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return {"message": "Purchase order deleted successfully"}


@api_router.post("/purchase-orders/{po_id}/approve")
async def approve_purchase_order(po_id: str, admin: str = Depends(verify_admin)):
    update = {
        "status": "approved",
        "approved_by_user_id": admin,
        "approved_by_name": admin,
        "approved_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = await db.purchase_orders.update_one({"id": po_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return {"message": "Purchase order approved"}


@api_router.post("/purchase-orders/{po_id}/mark-sent")
async def mark_purchase_order_sent(po_id: str, admin: str = Depends(verify_admin)):
    result = await db.purchase_orders.update_one({"id": po_id}, {"$set": {"status": "sent", "sent_at": datetime.utcnow(), "sent_by_user_id": admin, "sent_by_name": admin, "updated_at": datetime.utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return {"message": "Purchase order marked as sent"}


@api_router.get("/purchase-orders/{po_id}/pdf")
async def download_purchase_order_pdf(po_id: str, admin: str = Depends(verify_admin)):
    po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    pdf_bytes = generate_purchase_order_pdf_bytes(po)
    filename = f"{po.get('po_number', 'purchase_order')}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})


@api_router.post("/purchase-orders/{po_id}/send-email")
async def send_purchase_order_email(po_id: str, admin: str = Depends(verify_admin)):
    po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    supplier_email = (po.get("supplier_email") or "").strip()
    if not supplier_email:
        raise HTTPException(status_code=400, detail="No supplier email address is saved against this purchase order")

    pdf_bytes = generate_purchase_order_pdf_bytes(po)
    po_number = po.get("po_number", "purchase_order")
    subject = f"Purchase Order {po_number} - LDA Group"
    filename = f"{po_number}.pdf"

    body_text = f"""Hi,\n\nPlease find attached purchase order {po_number} for the following job:\n\nJob: {po.get('job_name', '')}\nRequired date: {po.get('required_date') or 'TBC'}\nDelivery address: {po.get('delivery_address') or 'TBC'}\n\nPlease confirm receipt and advise expected delivery date.\n\nKind regards,\nLDA Group\n"""

    body_html = f"""
    <p>Hi,</p>
    <p>Please find attached purchase order <strong>{po_number}</strong> for the following job:</p>
    <table style="border-collapse:collapse; font-family:Arial, sans-serif; font-size:14px;">
      <tr><td style="padding:4px 12px 4px 0;"><strong>Job:</strong></td><td>{po.get('job_name', '')}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;"><strong>Required date:</strong></td><td>{po.get('required_date') or 'TBC'}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;"><strong>Delivery address:</strong></td><td>{po.get('delivery_address') or 'TBC'}</td></tr>
    </table>
    <p>Please confirm receipt and advise expected delivery date.</p>
    <p>Kind regards,<br>LDA Group</p>
    """.strip()

    # Preferred route: Power Automate webhook over HTTPS.
    # This avoids Render free-tier SMTP port restrictions on 25/465/587.
    power_automate_url = os.environ.get("POWER_AUTOMATE_PO_EMAIL_URL", "").strip()
    power_automate_secret = os.environ.get("POWER_AUTOMATE_PO_EMAIL_SECRET", "").strip()

    if power_automate_url:
        payload = {
            "secret": power_automate_secret,
            "po_id": po.get("id"),
            "po_number": po_number,
            "supplier_name": po.get("supplier_name", ""),
            "supplier_email": supplier_email,
            "reply_to": os.environ.get("PO_REPLY_TO_EMAIL", os.environ.get("SMTP_FROM_EMAIL", "info@ldagroup.co.uk")).strip(),
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "pdf_filename": filename,
            "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
            "job_id": po.get("job_id"),
            "job_name": po.get("job_name", ""),
            "required_date": po.get("required_date") or "",
            "delivery_address": po.get("delivery_address") or "",
            "net_total": po.get("net_total", 0),
            "vat_total": po.get("vat_total", 0),
            "gross_total": po.get("gross_total", 0),
        }

        try:
            response = requests.post(power_automate_url, json=payload, timeout=60)
        except Exception as exc:
            logger.exception("Failed to call Power Automate PO email flow: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to call Power Automate PO email flow: {exc}")

        if response.status_code < 200 or response.status_code >= 300:
            response_text = response.text[:1000] if response.text else "No response body"
            logger.error("Power Automate PO email flow failed: %s %s", response.status_code, response_text)
            raise HTTPException(status_code=500, detail=f"Power Automate PO email flow failed: {response.status_code} - {response_text}")

        await db.purchase_orders.update_one(
            {"id": po_id},
            {"$set": {
                "status": "sent",
                "sent_at": datetime.utcnow(),
                "sent_by_user_id": admin,
                "sent_by_name": admin,
                "sent_to": supplier_email,
                "email_subject": subject,
                "email_method": "power_automate",
                "updated_at": datetime.utcnow(),
            }}
        )
        return {"message": "Purchase order email sent via Power Automate", "sent_to": supplier_email, "method": "power_automate"}

    # Fallback route: SMTP. This is retained for paid Render instances or other hosts.
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ.get("SMTP_USERNAME", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_from = os.environ.get("SMTP_FROM_EMAIL", smtp_username).strip()
    smtp_from_name = os.environ.get("SMTP_FROM_NAME", "LDA Group").strip()
    smtp_reply_to = os.environ.get("SMTP_REPLY_TO", os.environ.get("PO_REPLY_TO_EMAIL", "")).strip()
    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() != "false"
    if not smtp_host or not smtp_from:
        raise HTTPException(status_code=500, detail="Email is not configured. Add POWER_AUTOMATE_PO_EMAIL_URL and POWER_AUTOMATE_PO_EMAIL_SECRET in Render, or configure SMTP settings.")

    message = EmailMessage()
    message["From"] = f"{smtp_from_name} <{smtp_from}>"
    message["To"] = supplier_email
    message["Subject"] = subject
    if smtp_reply_to:
        message["Reply-To"] = smtp_reply_to
    message.set_content(body_text)
    message.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            if smtp_use_tls:
                smtp.starttls()
            if smtp_username and smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        logger.exception("Failed to send PO email: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to send PO email: {exc}")

    await db.purchase_orders.update_one(
        {"id": po_id},
        {"$set": {
            "status": "sent",
            "sent_at": datetime.utcnow(),
            "sent_by_user_id": admin,
            "sent_by_name": admin,
            "sent_to": supplier_email,
            "email_subject": subject,
            "email_method": "smtp",
            "updated_at": datetime.utcnow(),
        }}
    )
    return {"message": "Purchase order email sent", "sent_to": supplier_email, "method": "smtp"}


@api_router.post("/purchase-orders/{po_id}/assign-materials")
async def assign_purchase_order_materials(po_id: str, admin: str = Depends(verify_admin)):
    po = await db.purchase_orders.find_one({"id": po_id})
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.get("materials_assigned"):
        raise HTTPException(status_code=400, detail="Materials have already been assigned for this PO")
    materials_to_insert = []
    updated_lines = []
    for line in po.get("lines", []):
        material_id = str(uuid.uuid4())
        material = {
            "id": material_id,
            "job_id": po.get("job_id"),
            "name": line.get("description", "PO material"),
            "cost": float(line.get("unit_cost") or 0),
            "quantity": int(float(line.get("quantity") or 0)) if float(line.get("quantity") or 0).is_integer() else float(line.get("quantity") or 0),
            "supplier": po.get("supplier_name", ""),
            "reference": po.get("po_number", ""),
            "purchase_date": datetime.utcnow(),
            "notes": f"Assigned from purchase order {po.get('po_number', '')}",
            "created_date": datetime.utcnow(),
            "source_type": "purchase_order",
            "purchase_order_id": po_id,
            "purchase_order_line_id": line.get("id"),
            "status": "committed",
        }
        materials_to_insert.append(material)
        line["material_id"] = material_id
        line["material_status"] = "committed"
        updated_lines.append(line)
    if materials_to_insert:
        await db.materials.insert_many(materials_to_insert)
    await db.purchase_orders.update_one({"id": po_id}, {"$set": {"lines": updated_lines, "materials_assigned": True, "materials_assigned_at": datetime.utcnow(), "status": "materials_assigned", "updated_at": datetime.utcnow()}})
    return {"message": "PO materials assigned to job", "materials_created": len(materials_to_insert)}


@api_router.post("/purchase-orders/import-quote")
async def import_purchase_order_quote(
    file: UploadFile = File(...),
    job_id: Optional[str] = Query(None),
    admin: str = Depends(verify_admin),
):
    """Upload a supplier quote and return structured data for PO review.

    Patch 2 improves digital PDF/DOCX/TXT extraction, supplier matching, totals detection,
    and line-item parsing. Scanned image OCR is still deliberately left for a later patch.
    """
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Quote file is too large. Maximum size is 10MB.")

    filename = file.filename or "uploaded_quote"
    content_type = file.content_type or "application/octet-stream"
    extracted_text = await extract_text_from_upload(file, content)
    lines = parse_quote_lines_from_text(extracted_text) if extracted_text else []
    quote_number = extract_quote_number(extracted_text) if extracted_text else ""
    supplier_name = extract_supplier_name_from_text(extracted_text) if extracted_text else ""
    supplier_email = extract_email_from_text(extracted_text) if extracted_text else ""
    quote_date = extract_first_date_for_patterns(extracted_text, [r"quote\s*date", r"quotation\s*date", r"date"]) if extracted_text else ""
    expiry_date = extract_first_date_for_patterns(extracted_text, [r"valid\s*until", r"expiry\s*date", r"expires", r"quote\s*valid\s*until"]) if extracted_text else ""
    totals = extract_quote_totals(extracted_text) if extracted_text else {"net_total": None, "vat_total": None, "gross_total": None}
    supplier_match = await match_supplier_from_quote(supplier_name, supplier_email) if extracted_text else {"matched_supplier_id": None, "matched_supplier_name": "", "match_score": 0}

    warnings = []
    if not extracted_text:
        warnings.append("No readable text could be extracted. Scanned PDFs/images need the later OCR upgrade, but the file has been stored.")
    if extracted_text and not lines:
        warnings.append("Text was extracted, but line items could not be confidently detected. Please enter the PO lines manually.")
    if extracted_text and not supplier_match.get("matched_supplier_id"):
        if supplier_name:
            warnings.append("Supplier was detected but not matched to an existing supplier. Check or create the supplier before making the PO.")
        else:
            warnings.append("Supplier name could not be confidently detected.")
    if extracted_text and not quote_number:
        warnings.append("Quote reference could not be confidently detected.")

    line_net_total = round(sum((float(line.get("quantity") or 0) * float(line.get("unit_cost") or 0)) for line in lines), 2)
    extracted_net = totals.get("net_total")
    extracted_gross = totals.get("gross_total")
    totals_match = None
    if lines and extracted_net is not None:
        totals_match = abs(line_net_total - extracted_net) <= max(1.0, extracted_net * 0.03)
        if not totals_match:
            warnings.append("Extracted line total does not match the quote net total. Review quantities and prices before creating the PO.")

    confidence_score = 0
    if extracted_text:
        confidence_score += 20
    if lines:
        confidence_score += 30
    if supplier_match.get("matched_supplier_id"):
        confidence_score += 20
    elif supplier_name:
        confidence_score += 10
    if quote_number:
        confidence_score += 10
    if extracted_net is not None or extracted_gross is not None:
        confidence_score += 15
    if totals_match is True:
        confidence_score += 5

    if confidence_score >= 75:
        confidence = "high"
    elif confidence_score >= 45:
        confidence = "medium"
    else:
        confidence = "low"

    upload_id = str(uuid.uuid4())
    upload_doc = {
        "id": upload_id,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(content),
        "job_id": job_id,
        "uploaded_by": admin,
        "uploaded_at": datetime.utcnow(),
        "extracted_text": extracted_text[:40000],
        "quote_number": quote_number,
        "quote_date": quote_date,
        "expiry_date": expiry_date,
        "supplier_name": supplier_name,
        "supplier_email": supplier_email,
        "totals": totals,
        "lines": lines,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "warnings": warnings,
    }
    # Store content only for small files to avoid hitting MongoDB document limits.
    if len(content) <= 2 * 1024 * 1024:
        upload_doc["content_base64"] = base64.b64encode(content).decode("utf-8")
    await db.purchase_order_quote_uploads.insert_one(upload_doc)

    return {
        "upload_id": upload_id,
        "filename": filename,
        "content_type": content_type,
        "quote_number": quote_number,
        "quote_date": quote_date,
        "expiry_date": expiry_date,
        "supplier_name": supplier_name,
        "supplier_email": supplier_email,
        "matched_supplier_id": supplier_match.get("matched_supplier_id"),
        "matched_supplier_name": supplier_match.get("matched_supplier_name"),
        "supplier_match_score": supplier_match.get("match_score", 0),
        "lines": lines,
        "line_net_total": line_net_total,
        "quote_net_total": totals.get("net_total"),
        "quote_vat_total": totals.get("vat_total"),
        "quote_gross_total": totals.get("gross_total"),
        "totals_match": totals_match,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "warnings": warnings,
        "warning": " ".join(warnings) if warnings else "Quote imported. Please review extracted details before creating the PO.",
        "extracted_text_preview": extracted_text[:1800] if extracted_text else "",
        "extracted_text_length": len(extracted_text or ""),
    }


@api_router.get("/jobs/{job_id}/purchase-orders")
async def get_job_purchase_orders(job_id: str, admin: str = Depends(verify_admin)):
    purchase_orders = await db.purchase_orders.find({"job_id": job_id}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    committed_statuses = {"approved", "sent", "materials_assigned", "part_received"}
    committed_value = sum(po.get("net_total", 0) for po in purchase_orders if po.get("status") in committed_statuses)
    actual_value = sum(po.get("net_total", 0) for po in purchase_orders if po.get("status") in {"received", "invoiced", "closed"})
    return {"purchase_orders": purchase_orders, "committed_value": committed_value, "actual_value": actual_value}


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
