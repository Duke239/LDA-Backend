#!/usr/bin/env python3
"""
Production Data Restoration Script for LDA Group Time Tracking Application
Run this on your production server after deploying the updated code
"""

import json
import requests
import base64
import time

# Configuration - Update these to match your production URLs
BACKEND_URL = "https://lda-backend-eyn4.onrender.com/api"  # Your Render backend URL

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
        for collection, docs in data.items():
            print(f"  {collection}: {len(docs)} documents")
        
        return data
    except Exception as e:
        print(f"❌ Failed to load backup data: {e}")
        return None

def test_backend_connection():
    """Test if the backend is accessible"""
    print(f"Testing backend connection to {BACKEND_URL}...")
    try:
        response = requests.get(f"{BACKEND_URL}/", timeout=30)
        if response.status_code == 200:
            print("✅ Backend connection successful")
            return True
        else:
            print(f"❌ Backend returned status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Backend connection failed: {e}")
        return False

def restore_workers(workers_data):
    """Restore workers data"""
    print(f"\nRestoring {len(workers_data)} workers...")
    
    success_count = 0
    for worker in workers_data:
        # Remove MongoDB _id field and clean data
        worker_data = {k: v for k, v in worker.items() if k not in ['_id']}
        
        try:
            response = requests.post(
                f"{BACKEND_URL}/workers",
                json=worker_data,
                headers=ADMIN_HEADERS,
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"  ✅ Created worker: {worker_data.get('name', 'Unknown')}")
                success_count += 1
            else:
                print(f"  ❌ Failed to create worker {worker_data.get('name', 'Unknown')}: {response.text[:200]}")
                
        except Exception as e:
            print(f"  ❌ Error creating worker {worker_data.get('name', 'Unknown')}: {e}")
        
        time.sleep(0.5)  # Small delay to avoid overwhelming the server
    
    print(f"Workers restored: {success_count}/{len(workers_data)}")

def restore_jobs(jobs_data):
    """Restore jobs data"""
    print(f"\nRestoring {len(jobs_data)} jobs...")
    
    success_count = 0
    for job in jobs_data:
        # Remove MongoDB _id field and clean data
        job_data = {k: v for k, v in job.items() if k not in ['_id']}
        
        try:
            response = requests.post(
                f"{BACKEND_URL}/jobs",
                json=job_data,
                headers=ADMIN_HEADERS,
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"  ✅ Created job: {job_data.get('name', 'Unknown')}")
                success_count += 1
            else:
                print(f"  ❌ Failed to create job {job_data.get('name', 'Unknown')}: {response.text[:200]}")
                
        except Exception as e:
            print(f"  ❌ Error creating job {job_data.get('name', 'Unknown')}: {e}")
        
        time.sleep(0.5)  # Small delay
    
    print(f"Jobs restored: {success_count}/{len(jobs_data)}")

def restore_materials(materials_data):
    """Restore materials data"""
    print(f"\nRestoring {len(materials_data)} materials...")
    
    success_count = 0
    for material in materials_data:
        # Remove MongoDB _id field and clean data
        material_data = {k: v for k, v in material.items() if k not in ['_id']}
        
        try:
            response = requests.post(
                f"{BACKEND_URL}/materials",
                json=material_data,
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"  ✅ Created material: {material_data.get('name', 'Unknown')}")
                success_count += 1
            else:
                print(f"  ❌ Failed to create material {material_data.get('name', 'Unknown')}: {response.text[:200]}")
                
        except Exception as e:
            print(f"  ❌ Error creating material {material_data.get('name', 'Unknown')}: {e}")
        
        time.sleep(0.5)  # Small delay
    
    print(f"Materials restored: {success_count}/{len(materials_data)}")

def main():
    """Main restoration function"""
    print("LDA Group Time Tracking - Production Data Restoration")
    print("="*60)
    
    # Load backup data
    backup_data = load_backup_data()
    if not backup_data:
        print("❌ Cannot proceed without backup data")
        return
    
    # Test backend connection
    if not test_backend_connection():
        print("❌ Cannot connect to backend. Please ensure your backend is running.")
        return
    
    print(f"\nStarting restoration to {BACKEND_URL}...")
    
    # Restore in order: workers, jobs, materials
    # Note: Time entries are complex and may need manual recreation
    
    if 'workers' in backup_data:
        restore_workers(backup_data['workers'])
    
    if 'jobs' in backup_data:
        restore_jobs(backup_data['jobs'])
    
    if 'materials' in backup_data:
        restore_materials(backup_data['materials'])
    
    print("\n" + "="*60)
    print("✅ Data restoration completed!")
    print("\nNext steps:")
    print("1. Test your application to verify all data is present")
    print("2. Check admin dashboard for correct statistics")
    print("3. Time entries may need to be recreated manually")
    print("4. Verify all workers and jobs are displaying correctly")

if __name__ == "__main__":
    main()