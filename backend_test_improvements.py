import requests
import json
import time
from datetime import datetime, timedelta
import uuid

# Configuration
BACKEND_URL = "https://8ed69a34-0256-47a2-a1bb-2bd068b0c0bc.preview.emergentagent.com/api"
LONDON_COORDINATES = {"latitude": 51.5074, "longitude": -0.1278, "accuracy": 10.0}

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ldagroup2024"

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

def create_test_worker(name, email, phone, role="worker", hourly_rate=15.0, password=None):
    """Helper function to create a test worker"""
    worker_data = {
        "name": name,
        "email": email,
        "phone": phone,
        "role": role,
        "hourly_rate": hourly_rate
    }
    
    if password:
        worker_data["password"] = password
    
    response = requests.post(
        f"{BACKEND_URL}/workers", 
        json=worker_data,
        auth=(ADMIN_USERNAME, ADMIN_PASSWORD)
    )
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to create test worker: {response.text}")
        return None

def create_test_job(name, description, location, client, quoted_cost):
    """Helper function to create a test job"""
    job_data = {
        "name": name,
        "description": description,
        "location": location,
        "client": client,
        "quoted_cost": quoted_cost
    }
    
    response = requests.post(
        f"{BACKEND_URL}/jobs", 
        json=job_data,
        auth=(ADMIN_USERNAME, ADMIN_PASSWORD)
    )
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to create test job: {response.text}")
        return None

def create_time_entry(worker_id, job_id, clock_in_time=None, clock_out_time=None):
    """Helper function to create a time entry with specific times"""
    # Clock in
    clock_in_data = {
        "worker_id": worker_id,
        "job_id": job_id,
        "gps_location": LONDON_COORDINATES,
        "notes": "Test time entry"
    }
    
    response = requests.post(f"{BACKEND_URL}/time-entries/clock-in", json=clock_in_data)
    
    if response.status_code != 200:
        print(f"Failed to create time entry: {response.text}")
        return None
    
    time_entry_id = response.json()["id"]
    
    # Clock out if needed
    if clock_out_time:
        clock_out_data = {
            "gps_location": LONDON_COORDINATES,
            "notes": "Test clock out"
        }
        
        response = requests.put(f"{BACKEND_URL}/time-entries/{time_entry_id}/clock-out", json=clock_out_data)
        
        if response.status_code != 200:
            print(f"Failed to clock out: {response.text}")
    
    return time_entry_id

# Test functions for the 5 backend API improvements

def test_attendance_alerts_api():
    """
    Test the endpoint that provides late login/early logout alerts for the dashboard
    (should exclude admin users from alerts)
    """
    print_separator()
    print("TESTING ATTENDANCE ALERTS API")
    print_separator()
    
    # 1. Create a regular worker and an admin worker
    print("\nCreating test workers...")
    
    # Generate unique emails to avoid conflicts
    unique_id = str(uuid.uuid4())[:8]
    
    regular_worker = create_test_worker(
        f"Regular Worker {unique_id}", 
        f"regular.worker.{unique_id}@ldagroup.co.uk", 
        "07700 900123"
    )
    
    admin_worker = create_test_worker(
        f"Admin Worker {unique_id}", 
        f"admin.worker.{unique_id}@ldagroup.co.uk", 
        "07700 900456", 
        role="admin", 
        password="adminpass123"
    )
    
    if not regular_worker or not admin_worker:
        print("Failed to create test workers. Skipping test.")
        return False
    
    # 2. Create a test job
    print("\nCreating test job...")
    test_job = create_test_job(
        f"Test Job {unique_id}",
        "Test job for attendance alerts",
        "123 Test Street, London",
        "Test Client",
        5000.00
    )
    
    if not test_job:
        print("Failed to create test job. Skipping test.")
        return False
    
    # 3. Create time entries for both workers
    print("\nCreating time entries...")
    regular_worker_entry = create_time_entry(regular_worker["id"], test_job["id"])
    admin_worker_entry = create_time_entry(admin_worker["id"], test_job["id"])
    
    if not regular_worker_entry or not admin_worker_entry:
        print("Failed to create time entries. Skipping test.")
        return False
    
    # 4. Get dashboard statistics and check attendance alerts
    print("\nGetting dashboard statistics...")
    response = requests.get(
        f"{BACKEND_URL}/reports/dashboard",
        auth=(ADMIN_USERNAME, ADMIN_PASSWORD)
    )
    
    print_response(response, "Dashboard statistics with attendance alerts")
    
    if response.status_code == 200:
        dashboard_data = response.json()
        attendance_alerts = dashboard_data.get("attendance_alerts", [])
        
        # Check if admin worker is excluded from alerts
        admin_in_alerts = any(
            alert.get("worker_name") == admin_worker["name"] 
            for alert in attendance_alerts
        )
        
        if admin_in_alerts:
            print("\n❌ TEST FAILED: Admin worker was found in attendance alerts")
            return False
        else:
            print("\n✅ TEST PASSED: Admin worker was correctly excluded from attendance alerts")
            return True
    else:
        print(f"\n❌ TEST FAILED: Could not retrieve dashboard statistics")
        return False

def test_archived_jobs_filtering_api():
    """
    Test that archived jobs are properly hidden from active job lists in all relevant endpoints
    (GET /api/jobs should not return archived jobs by default)
    """
    print_separator()
    print("TESTING ARCHIVED JOBS FILTERING API")
    print_separator()
    
    # 1. Create a test job
    print("\nCreating test job...")
    unique_id = str(uuid.uuid4())[:8]
    test_job = create_test_job(
        f"Archived Job Test {unique_id}",
        "Test job for archiving",
        "123 Archive Street, London",
        "Archive Client",
        5000.00
    )
    
    if not test_job:
        print("Failed to create test job. Skipping test.")
        return False
    
    # 2. Archive the job
    print("\nArchiving the job...")
    response = requests.put(
        f"{BACKEND_URL}/jobs/{test_job['id']}/archive",
        auth=(ADMIN_USERNAME, ADMIN_PASSWORD)
    )
    
    print_response(response, "Archive job response")
    
    if response.status_code != 200:
        print("Failed to archive job. Skipping test.")
        return False
    
    # 3. Get all jobs without specifying include_archived
    print("\nGetting all jobs (default behavior)...")
    response = requests.get(f"{BACKEND_URL}/jobs")
    
    print_response(response, "Get all jobs (default)")
    
    if response.status_code == 200:
        jobs = response.json()
        archived_job_found = any(job["id"] == test_job["id"] for job in jobs)
        
        if archived_job_found:
            print("\n❌ TEST FAILED: Archived job was found in default jobs list")
            return False
        else:
            print("\n✅ TEST PASSED: Archived job was correctly excluded from default jobs list")
    else:
        print(f"\n❌ TEST FAILED: Could not retrieve jobs list")
        return False
    
    # 4. Get all jobs with include_archived=true
    print("\nGetting all jobs with include_archived=true...")
    response = requests.get(f"{BACKEND_URL}/jobs?include_archived=true")
    
    print_response(response, "Get all jobs (include_archived=true)")
    
    if response.status_code == 200:
        jobs = response.json()
        archived_job_found = any(job["id"] == test_job["id"] for job in jobs)
        
        if not archived_job_found:
            print("\n❌ TEST FAILED: Archived job was not found when include_archived=true")
            return False
        else:
            print("\n✅ TEST PASSED: Archived job was correctly included when include_archived=true")
            return True
    else:
        print(f"\n❌ TEST FAILED: Could not retrieve jobs list with include_archived=true")
        return False

def test_job_unarchiving_api():
    """
    Test the endpoint that allows admins to unarchive jobs
    (should change job status from archived back to active)
    """
    print_separator()
    print("TESTING JOB UNARCHIVING API")
    print_separator()
    
    # 1. Create a test job
    print("\nCreating test job...")
    unique_id = str(uuid.uuid4())[:8]
    test_job = create_test_job(
        f"Unarchive Job Test {unique_id}",
        "Test job for unarchiving",
        "123 Unarchive Street, London",
        "Unarchive Client",
        5000.00
    )
    
    if not test_job:
        print("Failed to create test job. Skipping test.")
        return False
    
    # 2. Archive the job
    print("\nArchiving the job...")
    response = requests.put(
        f"{BACKEND_URL}/jobs/{test_job['id']}/archive",
        auth=(ADMIN_USERNAME, ADMIN_PASSWORD)
    )
    
    print_response(response, "Archive job response")
    
    if response.status_code != 200:
        print("Failed to archive job. Skipping test.")
        return False
    
    # 3. Verify job is archived
    print("\nVerifying job is archived...")
    response = requests.get(f"{BACKEND_URL}/jobs/{test_job['id']}")
    
    print_response(response, "Get archived job")
    
    if response.status_code == 200:
        job = response.json()
        if not job.get("archived"):
            print("\n❌ TEST FAILED: Job is not showing as archived")
            return False
    else:
        print(f"\n❌ TEST FAILED: Could not retrieve job")
        return False
    
    # 4. Unarchive the job
    print("\nUnarchiving the job...")
    response = requests.put(
        f"{BACKEND_URL}/jobs/{test_job['id']}/unarchive",
        auth=(ADMIN_USERNAME, ADMIN_PASSWORD)
    )
    
    print_response(response, "Unarchive job response")
    
    if response.status_code != 200:
        print("\n❌ TEST FAILED: Failed to unarchive job")
        return False
    
    # 5. Verify job is unarchived
    print("\nVerifying job is unarchived...")
    response = requests.get(f"{BACKEND_URL}/jobs/{test_job['id']}")
    
    print_response(response, "Get unarchived job")
    
    if response.status_code == 200:
        job = response.json()
        if job.get("archived"):
            print("\n❌ TEST FAILED: Job is still showing as archived after unarchiving")
            return False
        else:
            print("\n✅ TEST PASSED: Job was successfully unarchived")
            return True
    else:
        print(f"\n❌ TEST FAILED: Could not retrieve job after unarchiving")
        return False

def test_job_editing_authorization_fix():
    """
    Test that job editing no longer returns "not authorized" error
    (admins should be able to edit job details successfully)
    """
    print_separator()
    print("TESTING JOB EDITING AUTHORIZATION FIX")
    print_separator()
    
    # 1. Create a test job
    print("\nCreating test job...")
    unique_id = str(uuid.uuid4())[:8]
    test_job = create_test_job(
        f"Edit Auth Test {unique_id}",
        "Test job for editing authorization",
        "123 Edit Street, London",
        "Edit Client",
        5000.00
    )
    
    if not test_job:
        print("Failed to create test job. Skipping test.")
        return False
    
    # 2. Edit the job
    print("\nEditing the job...")
    update_data = {
        "name": f"Updated Job {unique_id}",
        "description": "Updated description",
        "quoted_cost": 6000.00
    }
    
    response = requests.put(
        f"{BACKEND_URL}/jobs/{test_job['id']}",
        json=update_data,
        auth=(ADMIN_USERNAME, ADMIN_PASSWORD)
    )
    
    print_response(response, "Edit job response")
    
    if response.status_code == 200:
        updated_job = response.json()
        
        # Verify the changes were applied
        if (updated_job.get("name") == update_data["name"] and
            updated_job.get("description") == update_data["description"] and
            updated_job.get("quoted_cost") == update_data["quoted_cost"]):
            print("\n✅ TEST PASSED: Job was successfully edited with admin credentials")
            return True
        else:
            print("\n❌ TEST FAILED: Job was not updated correctly")
            return False
    else:
        print(f"\n❌ TEST FAILED: Could not edit job, received status code {response.status_code}")
        return False

def test_new_admin_authentication_api():
    """
    Test that newly added admin users can authenticate successfully
    (should not get "Invalid admin credentials" error)
    """
    print_separator()
    print("TESTING NEW ADMIN AUTHENTICATION API")
    print_separator()
    
    # 1. Create a new admin user
    print("\nCreating new admin user...")
    unique_id = str(uuid.uuid4())[:8]
    admin_email = f"new.admin.{unique_id}@ldagroup.co.uk"
    admin_password = "newadminpass123"
    
    new_admin = create_test_worker(
        f"New Admin {unique_id}",
        admin_email,
        "07700 900789",
        role="admin",
        password=admin_password
    )
    
    if not new_admin:
        print("Failed to create new admin user. Skipping test.")
        return False
    
    # 2. Try to authenticate with the new admin credentials
    print("\nTesting authentication with new admin credentials...")
    login_data = {
        "username": admin_email,
        "password": admin_password
    }
    
    response = requests.post(f"{BACKEND_URL}/admin/login", json=login_data)
    
    print_response(response, "Admin login response")
    
    if response.status_code == 200:
        login_result = response.json()
        if login_result.get("success"):
            print("\n✅ TEST PASSED: New admin user authenticated successfully")
            return True
        else:
            print("\n❌ TEST FAILED: Login response did not indicate success")
            return False
    else:
        print(f"\n❌ TEST FAILED: Authentication failed with status code {response.status_code}")
        return False

def run_all_tests():
    print("\n\n")
    print("="*80)
    print("TESTING LDA GROUP TIME TRACKING API IMPROVEMENTS")
    print("="*80)
    
    # Run tests for the 5 backend API improvements
    attendance_alerts_result = test_attendance_alerts_api()
    archived_jobs_result = test_archived_jobs_filtering_api()
    job_unarchiving_result = test_job_unarchiving_api()
    job_editing_result = test_job_editing_authorization_fix()
    admin_auth_result = test_new_admin_authentication_api()
    
    print("\n\n")
    print("="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"1. Attendance Alerts API: {'✅ PASSED' if attendance_alerts_result else '❌ FAILED'}")
    print(f"2. Archived Jobs Filtering API: {'✅ PASSED' if archived_jobs_result else '❌ FAILED'}")
    print(f"3. Job Unarchiving API: {'✅ PASSED' if job_unarchiving_result else '❌ FAILED'}")
    print(f"4. Job Editing Authorization Fix: {'✅ PASSED' if job_editing_result else '❌ FAILED'}")
    print(f"5. New Admin Authentication API: {'✅ PASSED' if admin_auth_result else '❌ FAILED'}")
    print("="*80)
    print("TESTS COMPLETED")
    print("="*80)
    
    # Return overall success
    return all([
        attendance_alerts_result,
        archived_jobs_result,
        job_unarchiving_result,
        job_editing_result,
        admin_auth_result
    ])

if __name__ == "__main__":
    run_all_tests()