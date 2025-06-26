#!/usr/bin/env python3
"""
Data Restoration Script for LDA Group Time Tracking Application
Restores data from backup to MongoDB Atlas via the FastAPI backend
"""

import json
import requests
import base64
from datetime import datetime

# Configuration
BACKEND_URL = "https://lda-backend-eyn4.onrender.com/api"  # Your new backend URL
LOCAL_BACKEND_URL = "http://localhost:8001/api"  # For testing locally first

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ldagroup2024"
ADMIN_AUTH = base64.b64encode(f"{ADMIN_USERNAME}:{ADMIN_PASSWORD}".encode()).decode()
ADMIN_HEADERS = {"Authorization": f"Basic {ADMIN_AUTH}", "Content-Type": "application/json"}

def load_backup_data():
    """Load the backup data from JSON file"""
    print("Loading backup data...")
    try:
        with open('lda_data_backup.json', 'r') as f:
            data = json.load(f)
        
        print("✅ Backup data loaded successfully")
        print(f"Collections found: {list(data.keys())}")
        for collection, docs in data.items():
            print(f"  {collection}: {len(docs)} documents")
        
        return data
    except Exception as e:
        print(f"❌ Failed to load backup data: {e}")
        return None

def test_backend_connection(backend_url):
    """Test if the backend is accessible"""
    print(f"Testing backend connection to {backend_url}...")
    try:
        response = requests.get(f"{backend_url}/", timeout=10)
        if response.status_code == 200:
            print("✅ Backend connection successful")
            return True
        else:
            print(f"❌ Backend returned status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Backend connection failed: {e}")
        return False

def restore_workers(workers_data, backend_url):
    """Restore workers data"""
    print(f"\nRestoring {len(workers_data)} workers...")
    
    for worker in workers_data:
        # Remove MongoDB _id field
        worker_data = {k: v for k, v in worker.items() if k != '_id'}
        
        try:
            response = requests.post(
                f"{backend_url}/workers",
                json=worker_data,
                headers=ADMIN_HEADERS,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"  ✅ Created worker: {worker_data.get('name', 'Unknown')}")
            else:
                print(f"  ❌ Failed to create worker {worker_data.get('name', 'Unknown')}: {response.text}")
                
        except Exception as e:
            print(f"  ❌ Error creating worker {worker_data.get('name', 'Unknown')}: {e}")

def restore_jobs(jobs_data, backend_url):
    """Restore jobs data"""
    print(f"\nRestoring {len(jobs_data)} jobs...")
    
    for job in jobs_data:
        # Remove MongoDB _id field
        job_data = {k: v for k, v in job.items() if k != '_id'}
        
        try:
            response = requests.post(
                f"{backend_url}/jobs",
                json=job_data,
                headers=ADMIN_HEADERS,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"  ✅ Created job: {job_data.get('name', 'Unknown')}")
            else:
                print(f"  ❌ Failed to create job {job_data.get('name', 'Unknown')}: {response.text}")
                
        except Exception as e:
            print(f"  ❌ Error creating job {job_data.get('name', 'Unknown')}: {e}")

def restore_materials(materials_data, backend_url):
    """Restore materials data"""
    print(f"\nRestoring {len(materials_data)} materials...")
    
    for material in materials_data:
        # Remove MongoDB _id field
        material_data = {k: v for k, v in material.items() if k != '_id'}
        
        try:
            response = requests.post(
                f"{backend_url}/materials",
                json=material_data,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"  ✅ Created material: {material_data.get('name', 'Unknown')}")
            else:
                print(f"  ❌ Failed to create material {material_data.get('name', 'Unknown')}: {response.text}")
                
        except Exception as e:
            print(f"  ❌ Error creating material {material_data.get('name', 'Unknown')}: {e}")

def restore_time_entries(time_entries_data, backend_url):
    """Restore time entries data"""
    print(f"\nRestoring {len(time_entries_data)} time entries...")
    print("Note: Time entries need to be created via clock-in/clock-out endpoints and then updated")
    
    for entry in time_entries_data:
        try:
            # Create clock-in entry
            clock_in_data = {
                "worker_id": entry.get("worker_id"),
                "job_id": entry.get("job_id"),
                "gps_location": entry.get("gps_location_in"),
                "notes": entry.get("notes", "")
            }
            
            response = requests.post(
                f"{backend_url}/time-entries/clock-in",
                json=clock_in_data,
                timeout=10
            )
            
            if response.status_code == 200:
                entry_id = response.json()["id"]
                
                # If there's a clock_out time, update the entry
                if entry.get("clock_out"):
                    update_data = {
                        "worker_id": entry.get("worker_id"),
                        "job_id": entry.get("job_id"),
                        "clock_in": entry.get("clock_in"),
                        "clock_out": entry.get("clock_out"),
                        "duration_minutes": entry.get("duration_minutes"),
                        "notes": entry.get("notes", "")
                    }
                    
                    update_response = requests.put(
                        f"{backend_url}/time-entries/{entry_id}",
                        json=update_data,
                        headers=ADMIN_HEADERS,
                        timeout=10
                    )
                    
                    if update_response.status_code == 200:
                        print(f"  ✅ Created and updated time entry for worker {entry.get('worker_id')}")
                    else:
                        print(f"  ⚠️ Created entry but failed to update: {update_response.text}")
                else:
                    print(f"  ✅ Created active time entry for worker {entry.get('worker_id')}")
                    
            else:
                print(f"  ❌ Failed to create time entry: {response.text}")
                
        except Exception as e:
            print(f"  ❌ Error creating time entry: {e}")

def main():
    """Main restoration function"""
    print("LDA Group Time Tracking - Data Restoration")
    print("="*50)
    
    # Load backup data
    backup_data = load_backup_data()
    if not backup_data:
        print("❌ Cannot proceed without backup data")
        return
    
    # Test local backend first
    if test_backend_connection(LOCAL_BACKEND_URL):
        print("Using local backend for restoration")
        backend_url = LOCAL_BACKEND_URL
    elif test_backend_connection(BACKEND_URL):
        print("Using remote backend for restoration")
        backend_url = BACKEND_URL
    else:
        print("❌ No backend available. Please ensure your backend is running.")
        return
    
    print(f"\nStarting restoration to {backend_url}...")
    
    # Restore in order: workers, jobs, materials, time_entries
    if 'workers' in backup_data:
        restore_workers(backup_data['workers'], backend_url)
    
    if 'jobs' in backup_data:
        restore_jobs(backup_data['jobs'], backend_url)
    
    if 'materials' in backup_data:
        restore_materials(backup_data['materials'], backend_url)
    
    if 'time_entries' in backup_data:
        restore_time_entries(backup_data['time_entries'], backend_url)
    
    print("\n✅ Data restoration completed!")
    print("\nNext steps:")
    print("1. Test your application to verify all data is present")
    print("2. Check admin dashboard for correct statistics")
    print("3. Verify time entries and materials are showing correctly")

if __name__ == "__main__":
    main()