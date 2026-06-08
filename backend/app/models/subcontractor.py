from datetime import datetime, date
from typing import List, Optional
from pydantic import BaseModel, Field
from uuid import uuid4


class SubcontractorCompanyBase(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    trades: List[str] = []
    cis_registered: bool = False
    utr_number: Optional[str] = None
    insurance_expiry: Optional[date] = None
    notes: Optional[str] = None
    active: bool = True


class SubcontractorCompanyCreate(SubcontractorCompanyBase):
    pass


class SubcontractorCompanyUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    trades: Optional[List[str]] = None
    cis_registered: Optional[bool] = None
    utr_number: Optional[str] = None
    insurance_expiry: Optional[date] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class SubcontractorCompany(SubcontractorCompanyBase):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SubcontractorResourceBase(BaseModel):
    subcontractor_id: str
    name: str
    trade: Optional[str] = None
    capacity: int = 1
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


class SubcontractorResourceCreate(SubcontractorResourceBase):
    pass


class SubcontractorResourceUpdate(BaseModel):
    subcontractor_id: Optional[str] = None
    name: Optional[str] = None
    trade: Optional[str] = None
    capacity: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class SubcontractorResource(SubcontractorResourceBase):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
