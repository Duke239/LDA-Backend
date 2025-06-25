import requests
import json
import time
from datetime import datetime, timedelta
import csv
import io

# Configuration
BACKEND_URL = "https://8ed69a34-0256-47a2-a1bb-2bd068b0c0bc.preview.emergentagent.com/api"
LONDON_COORDINATES = {"latitude": 51.5074, "longitude": -0.1278, "accuracy": 10.0}

# Test data
test_workers = [
    {"name": "John Smith", "email": "john.smith@ldagroup.co.uk", "phone": "07700 900123", "role": "worker"},
    {"name": "Sarah Jones", "email": "sarah.jones@ldagroup.co.uk", "phone": "07700 900456", "role": "supervisor"},
    {"name": "Mike Wilson", "email": "mike.wilson@ldagroup.co.uk", "phone": "07700 900789", "role": "worker"},
    {"name": "Admin User", "email": "admin@ldagroup.co.uk", "phone": "07700 900999", "role": "admin"}
]

test_jobs = [
    {
        "name": "Kitchen Renovation - Smith House",
        "description": "Complete kitchen renovation including new cabinets, countertops, and appliances",
        "location": "123 Baker Street, London",
        "client": "Smith Family",
        "quoted_cost": 15000.00
    },
    {
        "name": "Bathroom Refit - Johnson Property",
        "description": "Full bathroom remodeling with new fixtures and tiling",
        "location": "45 Oxford Road, London",
        "client": "Johnson Ltd",
        "quoted_cost": 8500.00
    },
    {
        "name": "Garden Landscaping - Williams Home",
        "description": "Complete garden redesign with new patio, plants, and water feature",
        "location": "78 Kensington Gardens, London",
        "client": "Williams Family",
        "quoted_cost": 12000.00
    }
]

test_materials = [
    {"name": "Kitchen Cabinets", "cost": 3500.00, "quantity": 1, "notes": "Custom oak cabinets"},
    {"name": "Granite Countertop", "cost": 1200.00, "quantity": 1, "notes": "Black granite, 3m length"},
    {"name": "Bathroom Tiles", "cost": 45.00, "quantity": 20, "notes": "Ceramic white tiles, 30x30cm"},
    {"name": "Garden Paving Stones", "cost": 15.00, "quantity": 50, "notes": "Natural sandstone"}
]

# Helper functions
def print_separator():
    print("\n" + "="*80 + "\n")

def print_response(response, description):
    print(f"\n--- {description} ---")
    print(f"Status Code: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except:
        print(f"Response: {response.text}")

# Test functions
def test_workers_endpoints():
    print_separator()
    print("TESTING WORKERS ENDPOINTS")
    print_separator()
    
    # Store created worker IDs
    worker_ids = []
    
    # 1. Create workers
    print("\nCreating workers...")
    for worker_data in test_workers:
        response = requests.post(f"{BACKEND_URL}/workers", json=worker_data)
        print_response(response, f"Create worker: {worker_data['name']}")
        
        if response.status_code == 200:
            worker_ids.append(response.json()["id"])
    
    # 2. Get all workers
    print("\nGetting all workers...")
    response = requests.get(f"{BACKEND_URL}/workers")
    print_response(response, "Get all workers")
    
    # 3. Get specific worker
    if worker_ids:
        print("\nGetting specific worker...")
        response = requests.get(f"{BACKEND_URL}/workers/{worker_ids[0]}")
        print_response(response, f"Get worker with ID: {worker_ids[0]}")
    
    # 4. Update worker
    if worker_ids:
        print("\nUpdating worker...")
        update_data = {"phone": "07700 111222", "role": "supervisor"}
        response = requests.put(f"{BACKEND_URL}/workers/{worker_ids[0]}", json=update_data)
        print_response(response, f"Update worker with ID: {worker_ids[0]}")
    
    return worker_ids

def test_jobs_endpoints():
    print_separator()
    print("TESTING JOBS ENDPOINTS")
    print_separator()
    
    # Store created job IDs
    job_ids = []
    
    # 1. Create jobs
    print("\nCreating jobs...")
    for job_data in test_jobs:
        response = requests.post(f"{BACKEND_URL}/jobs", json=job_data)
        print_response(response, f"Create job: {job_data['name']}")
        
        if response.status_code == 200:
            job_ids.append(response.json()["id"])
    
    # 2. Get all jobs
    print("\nGetting all jobs...")
    response = requests.get(f"{BACKEND_URL}/jobs")
    print_response(response, "Get all jobs")
    
    # 3. Get specific job
    if job_ids:
        print("\nGetting specific job...")
        response = requests.get(f"{BACKEND_URL}/jobs/{job_ids[0]}")
        print_response(response, f"Get job with ID: {job_ids[0]}")
    
    # 4. Update job
    if job_ids:
        print("\nUpdating job...")
        update_data = {"quoted_cost": 16000.00, "description": "Updated kitchen renovation with premium fixtures"}
        response = requests.put(f"{BACKEND_URL}/jobs/{job_ids[0]}", json=update_data)
        print_response(response, f"Update job with ID: {job_ids[0]}")
    
    return job_ids

def test_time_tracking_endpoints(worker_ids, job_ids):
    print_separator()
    print("TESTING TIME TRACKING ENDPOINTS")
    print_separator()
    
    if not worker_ids or not job_ids:
        print("Cannot test time tracking without worker and job IDs")
        return []
    
    time_entry_ids = []
    
    # 1. Clock in
    print("\nClocking in worker...")
    clock_in_data = {
        "worker_id": worker_ids[0],
        "job_id": job_ids[0],
        "gps_location": LONDON_COORDINATES,
        "notes": "Starting kitchen renovation work"
    }
    response = requests.post(f"{BACKEND_URL}/time-entries/clock-in", json=clock_in_data)
    print_response(response, f"Clock in worker {worker_ids[0]} to job {job_ids[0]}")
    
    if response.status_code == 200:
        time_entry_id = response.json()["id"]
        time_entry_ids.append(time_entry_id)
        
        # 2. Check active time entry
        print("\nChecking active time entry...")
        response = requests.get(f"{BACKEND_URL}/workers/{worker_ids[0]}/active-entry")
        print_response(response, f"Get active time entry for worker {worker_ids[0]}")
        
        # Wait a bit to have some duration
        print("\nWaiting 5 seconds before clocking out...")
        time.sleep(5)
        
        # 3. Clock out
        print("\nClocking out worker...")
        clock_out_data = {
            "gps_location": LONDON_COORDINATES,
            "notes": "Completed initial assessment"
        }
        response = requests.put(f"{BACKEND_URL}/time-entries/{time_entry_id}/clock-out", json=clock_out_data)
        print_response(response, f"Clock out time entry {time_entry_id}")
    
    # 4. Get time entries with filters
    print("\nGetting time entries...")
    response = requests.get(f"{BACKEND_URL}/time-entries?worker_id={worker_ids[0]}")
    print_response(response, f"Get time entries for worker {worker_ids[0]}")
    
    # Create another time entry for a different worker and job
    if len(worker_ids) > 1 and len(job_ids) > 1:
        print("\nCreating another time entry for different worker and job...")
        clock_in_data = {
            "worker_id": worker_ids[1],
            "job_id": job_ids[1],
            "gps_location": LONDON_COORDINATES,
            "notes": "Starting bathroom refit"
        }
        response = requests.post(f"{BACKEND_URL}/time-entries/clock-in", json=clock_in_data)
        print_response(response, f"Clock in worker {worker_ids[1]} to job {job_ids[1]}")
        
        if response.status_code == 200:
            time_entry_id = response.json()["id"]
            time_entry_ids.append(time_entry_id)
            
            # Wait a bit
            time.sleep(3)
            
            # Clock out
            clock_out_data = {
                "gps_location": LONDON_COORDINATES,
                "notes": "Completed initial measurements"
            }
            response = requests.put(f"{BACKEND_URL}/time-entries/{time_entry_id}/clock-out", json=clock_out_data)
            print_response(response, f"Clock out time entry {time_entry_id}")
    
    return time_entry_ids

def test_materials_endpoints(job_ids):
    print_separator()
    print("TESTING MATERIALS ENDPOINTS")
    print_separator()
    
    if not job_ids:
        print("Cannot test materials without job IDs")
        return []
    
    material_ids = []
    
    # 1. Create materials
    print("\nCreating materials...")
    for i, material_data in enumerate(test_materials):
        # Assign different materials to different jobs
        job_index = min(i, len(job_ids) - 1)
        material_with_job = material_data.copy()
        material_with_job["job_id"] = job_ids[job_index]
        
        response = requests.post(f"{BACKEND_URL}/materials", json=material_with_job)
        print_response(response, f"Create material: {material_data['name']} for job {job_ids[job_index]}")
        
        if response.status_code == 200:
            material_ids.append(response.json()["id"])
    
    # 2. Get materials with job filter
    if job_ids:
        print("\nGetting materials for specific job...")
        response = requests.get(f"{BACKEND_URL}/materials?job_id={job_ids[0]}")
        print_response(response, f"Get materials for job {job_ids[0]}")
    
    # 3. Update material
    if material_ids:
        print("\nUpdating material...")
        update_data = {"cost": 3800.00, "notes": "Premium oak cabinets with soft-close hinges"}
        response = requests.put(f"{BACKEND_URL}/materials/{material_ids[0]}", json=update_data)
        print_response(response, f"Update material with ID: {material_ids[0]}")
    
    # 4. Delete material (test with the last material)
    if material_ids:
        print("\nDeleting material...")
        response = requests.delete(f"{BACKEND_URL}/materials/{material_ids[-1]}")
        print_response(response, f"Delete material with ID: {material_ids[-1]}")
        material_ids.pop()  # Remove the deleted ID
    
    return material_ids

def test_reporting_endpoints(job_ids):
    print_separator()
    print("TESTING REPORTING ENDPOINTS")
    print_separator()
    
    # 1. Dashboard statistics
    print("\nGetting dashboard statistics...")
    response = requests.get(f"{BACKEND_URL}/reports/dashboard")
    print_response(response, "Get dashboard statistics")
    
    # 2. Job cost analysis
    if job_ids:
        print("\nGetting job cost analysis...")
        response = requests.get(f"{BACKEND_URL}/reports/job-costs/{job_ids[0]}")
        print_response(response, f"Get job cost analysis for job {job_ids[0]}")
    
    # 3. Export time entries as CSV
    print("\nExporting time entries as CSV...")
    response = requests.get(f"{BACKEND_URL}/reports/export/time-entries")
    
    print(f"\n--- Export time entries as CSV ---")
    print(f"Status Code: {response.status_code}")
    print(f"Content Type: {response.headers.get('Content-Type')}")
    print(f"Content Disposition: {response.headers.get('Content-Disposition')}")
    
    if response.status_code == 200 and response.headers.get('Content-Type') == 'text/csv':
        csv_content = response.content.decode('utf-8')
        csv_reader = csv.reader(io.StringIO(csv_content))
        rows = list(csv_reader)
        
        print("\nCSV Headers:")
        if rows:
            print(rows[0])
        
        print(f"\nNumber of data rows: {len(rows) - 1}")
        if len(rows) > 1:
            print("\nSample data row:")
            print(rows[1])
    else:
        print(f"Response: {response.text}")

def run_all_tests():
    print("\n\n")
    print("="*80)
    print("STARTING LDA GROUP TIME TRACKING API TESTS")
    print("="*80)
    
    # Run tests in sequence
    worker_ids = test_workers_endpoints()
    job_ids = test_jobs_endpoints()
    time_entry_ids = test_time_tracking_endpoints(worker_ids, job_ids)
    material_ids = test_materials_endpoints(job_ids)
    test_reporting_endpoints(job_ids)
    
    print("\n\n")
    print("="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Workers created: {len(worker_ids)}")
    print(f"Jobs created: {len(job_ids)}")
    print(f"Time entries created: {len(time_entry_ids)}")
    print(f"Materials created: {len(material_ids)}")
    print("="*80)
    print("TESTS COMPLETED")
    print("="*80)

if __name__ == "__main__":
    run_all_tests()