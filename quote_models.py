from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from decimal import Decimal
import uuid

class QuoteItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    quantity: float = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    total: Optional[Decimal] = None
    
    def __init__(self, **data):
        super().__init__(**data)
        if self.total is None:
            self.total = Decimal(str(self.quantity)) * self.unit_price

class QuoteClient(BaseModel):
    name: str
    email: str
    phone: str
    address: str
    company: Optional[str] = None

class QuotePhoto(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    content_type: str
    size: int
    base64_data: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

class Quote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    quote_number: str
    surveyor_id: str
    surveyor_name: str
    
    # Client information
    client: QuoteClient
    
    # Quote details
    job_description: str
    estimated_hours: float = Field(gt=0)
    hourly_rate: Decimal = Field(gt=0, default=Decimal("25.00"))
    
    # Materials and items
    materials: List[QuoteItem] = []
    labor_items: List[QuoteItem] = []
    
    # Photos
    photos: List[QuotePhoto] = []
    
    # Quote status and dates
    status: str = Field(default="draft")  # draft, sent, accepted, declined, expired, converted
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    valid_until: date
    
    # Client response
    client_response: Optional[str] = None  # "accepted" or "declined"
    client_comments: Optional[str] = None
    
    # Quote totals
    materials_total: Optional[Decimal] = None
    labor_total: Optional[Decimal] = None
    subtotal: Optional[Decimal] = None
    tax_rate: Decimal = Field(default=Decimal("0.20"))  # 20% VAT
    tax_amount: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None
    
    # Conversion tracking
    converted_job_id: Optional[str] = None
    converted_at: Optional[datetime] = None
    
    # Notes
    notes: Optional[str] = None
    terms_conditions: Optional[str] = Field(default="Quote valid for 30 days. Payment terms: Net 30 days.")
    
    def __init__(self, **data):
        super().__init__(**data)
        self.calculate_totals()
    
    def calculate_totals(self):
        """Calculate quote totals"""
        # Calculate materials total
        self.materials_total = sum(item.total for item in self.materials)
        
        # Calculate labor total (hourly rate * estimated hours + labor items)
        labor_cost = Decimal(str(self.estimated_hours)) * self.hourly_rate
        labor_items_total = sum(item.total for item in self.labor_items)
        self.labor_total = labor_cost + labor_items_total
        
        # Calculate subtotal
        self.subtotal = self.materials_total + self.labor_total
        
        # Calculate tax
        self.tax_amount = self.subtotal * self.tax_rate
        
        # Calculate total
        self.total_amount = self.subtotal + self.tax_amount

class QuoteCreate(BaseModel):
    client: QuoteClient
    job_description: str
    estimated_hours: float = Field(gt=0)
    hourly_rate: Decimal = Field(gt=0, default=Decimal("25.00"))
    materials: List[QuoteItem] = []
    labor_items: List[QuoteItem] = []
    valid_until: date
    notes: Optional[str] = None

class QuoteUpdate(BaseModel):
    client: Optional[QuoteClient] = None
    job_description: Optional[str] = None
    estimated_hours: Optional[float] = Field(None, gt=0)
    hourly_rate: Optional[Decimal] = Field(None, gt=0)
    materials: Optional[List[QuoteItem]] = None
    labor_items: Optional[List[QuoteItem]] = None
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    status: Optional[str] = None

class ClientResponse(BaseModel):
    response: str = Field(..., pattern="^(accepted|declined)$")
    comments: Optional[str] = None

class SurveyorCreate(BaseModel):
    name: str
    email: str
    phone: str
    password: str
    
    @validator('email')
    def validate_email(cls, v):
        if '@' not in v:
            raise ValueError('Invalid email format')
        return v

class SurveyorLogin(BaseModel):
    email: str
    password: str