from datetime import datetime
from fastapi import APIRouter, HTTPException

from app.database import db
from app.models.subcontractor import (
    SubcontractorCompany,
    SubcontractorCompanyCreate,
    SubcontractorCompanyUpdate,
    SubcontractorResource,
    SubcontractorResourceCreate,
    SubcontractorResourceUpdate,
)

router = APIRouter(prefix="/api/subcontractors", tags=["Subcontractors"])


def clean_mongo_doc(doc):
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_subcontractors(active_only: bool = False):
    query = {}
    if active_only:
        query["active"] = True

    companies = await db.subcontractors.find(query).sort("company_name", 1).to_list(length=1000)
    companies = [clean_mongo_doc(c) for c in companies]

    resources = await db.subcontractor_resources.find({}).sort("name", 1).to_list(length=5000)
    resources = [clean_mongo_doc(r) for r in resources]

    by_company = {}
    for resource in resources:
        by_company.setdefault(resource.get("subcontractor_id"), []).append(resource)

    for company in companies:
        company["resources"] = by_company.get(company["id"], [])

    return companies


@router.post("")
async def create_subcontractor(payload: SubcontractorCompanyCreate):
    item = SubcontractorCompany(**payload.dict())
    data = item.dict()

    if data.get("insurance_expiry"):
        data["insurance_expiry"] = data["insurance_expiry"].isoformat()

    await db.subcontractors.insert_one(data)
    return data


@router.get("/{subcontractor_id}")
async def get_subcontractor(subcontractor_id: str):
    company = await db.subcontractors.find_one({"id": subcontractor_id})
    if not company:
        raise HTTPException(status_code=404, detail="Subcontractor not found")

    company = clean_mongo_doc(company)

    resources = await db.subcontractor_resources.find(
        {"subcontractor_id": subcontractor_id}
    ).sort("name", 1).to_list(length=1000)

    company["resources"] = [clean_mongo_doc(r) for r in resources]
    return company


@router.put("/{subcontractor_id}")
async def update_subcontractor(subcontractor_id: str, payload: SubcontractorCompanyUpdate):
    existing = await db.subcontractors.find_one({"id": subcontractor_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Subcontractor not found")

    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()

    if update_data.get("insurance_expiry"):
        update_data["insurance_expiry"] = update_data["insurance_expiry"].isoformat()

    await db.subcontractors.update_one(
        {"id": subcontractor_id},
        {"$set": update_data}
    )

    updated = await db.subcontractors.find_one({"id": subcontractor_id})
    return clean_mongo_doc(updated)


@router.delete("/{subcontractor_id}")
async def delete_subcontractor(subcontractor_id: str):
    existing = await db.subcontractors.find_one({"id": subcontractor_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Subcontractor not found")

    await db.subcontractors.update_one(
        {"id": subcontractor_id},
        {"$set": {"active": False, "updated_at": datetime.utcnow()}}
    )

    await db.subcontractor_resources.update_many(
        {"subcontractor_id": subcontractor_id},
        {"$set": {"active": False, "updated_at": datetime.utcnow()}}
    )

    return {"success": True, "message": "Subcontractor marked inactive"}


@router.get("/{subcontractor_id}/resources")
async def list_subcontractor_resources(subcontractor_id: str, active_only: bool = False):
    query = {"subcontractor_id": subcontractor_id}
    if active_only:
        query["active"] = True

    resources = await db.subcontractor_resources.find(query).sort("name", 1).to_list(length=1000)
    return [clean_mongo_doc(r) for r in resources]


@router.post("/{subcontractor_id}/resources")
async def create_subcontractor_resource(subcontractor_id: str, payload: SubcontractorResourceCreate):
    company = await db.subcontractors.find_one({"id": subcontractor_id})
    if not company:
        raise HTTPException(status_code=404, detail="Subcontractor not found")

    data = payload.dict()
    data["subcontractor_id"] = subcontractor_id

    item = SubcontractorResource(**data)
    final_data = item.dict()

    await db.subcontractor_resources.insert_one(final_data)
    return final_data


@router.put("/resources/{resource_id}")
async def update_subcontractor_resource(resource_id: str, payload: SubcontractorResourceUpdate):
    existing = await db.subcontractor_resources.find_one({"id": resource_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Subcontractor resource not found")

    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()

    await db.subcontractor_resources.update_one(
        {"id": resource_id},
        {"$set": update_data}
    )

    updated = await db.subcontractor_resources.find_one({"id": resource_id})
    return clean_mongo_doc(updated)


@router.delete("/resources/{resource_id}")
async def delete_subcontractor_resource(resource_id: str):
    existing = await db.subcontractor_resources.find_one({"id": resource_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Subcontractor resource not found")

    await db.subcontractor_resources.update_one(
        {"id": resource_id},
        {"$set": {"active": False, "updated_at": datetime.utcnow()}}
    )

    return {"success": True, "message": "Resource marked inactive"}


@router.get("/schedule/resources/all")
async def list_all_schedule_resources(active_only: bool = True):
    company_query = {}
    resource_query = {}

    if active_only:
        company_query["active"] = True
        resource_query["active"] = True

    companies = await db.subcontractors.find(company_query).to_list(length=1000)
    resources = await db.subcontractor_resources.find(resource_query).to_list(length=5000)

    company_lookup = {}
    for company in companies:
        company = clean_mongo_doc(company)
        company_lookup[company["id"]] = company

    output = []

    for resource in resources:
        resource = clean_mongo_doc(resource)
        company = company_lookup.get(resource.get("subcontractor_id"))

        if not company:
            continue

        output.append({
            "resource_type": "subcontractor_resource",
            "resource_id": resource["id"],
            "display_name": f"{company.get('company_name', '')} - {resource.get('name', '')}",
            "company_id": company["id"],
            "company_name": company.get("company_name", ""),
            "resource_name": resource.get("name", ""),
            "trade": resource.get("trade") or "",
            "capacity": resource.get("capacity", 1),
            "active": resource.get("active", True),
        })

    output.sort(key=lambda x: x["display_name"].lower())
    return output
