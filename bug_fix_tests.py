import requests
import json
import time
from datetime import datetime, timedelta
import base64

# Configuration
BACKEND_URL = "https://8ed69a34-0256-47a2-a1bb-2bd068b0c0bc.preview.emergentagent.com/api"
LONDON_COORDINATES = {"latitude": 51.5074, "longitude": -0.1278, "accuracy": 10.0}

# Authentication
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ldagroup2024"
ADMIN_AUTH = base64.b64encode(f"{ADMIN_USERNAME}:{ADMIN_PASSWORD}".encode()).decode()
ADMIN_HEADERS = {"Authorization": f"Basic {ADMIN_AUTH}"}

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

def test_new_admin_authentication():
    print_separator()
    print("TESTING NEW ADMIN AUTHENTICATION")
    print_separator()
    
    # 1. Create a new admin user with email and password
    print("\nCreating new admin user...")
    admin_data = {
        "name": "Test Admin",
        "email": "testadmin@ldagroup.co.uk",
        "phone": "07700 900555",
        "role": "admin",
        "password": "testadmin2024"
    }
    response = requests.post(f"{BACKEND_URL}/workers", json=admin_data, headers=ADMIN_HEADERS)
    print_response(response, "Create new admin user")
    
    if response.status_code != 200:
        print("Failed to create admin user, cannot continue test")
        return False
    
    admin_id = response.json()["id"]
    
    # 2. Test login with the new admin credentials
    print("\nTesting admin login...")
    login_data = {
        "username": "testadmin@ldagroup.co.uk",
        "password": "testadmin2024"
    }
    response = requests.post(f"{BACKEND_URL}/admin/login", json=login_data)
    print_response(response, "Admin login")
    
    if response.status_code != 200:
        print("Admin login failed")
        return False
    
    # 3. Test that authentication persists for subsequent authenticated requests
    print("\nTesting authentication persistence...")
    
    # Create auth headers for the new admin
    new_admin_auth = base64.b64encode(f"testadmin@ldagroup.co.uk:testadmin2024".encode()).decode()
    new_admin_headers = {"Authorization": f"Basic {new_admin_auth}"}
    
    # Try to access a protected endpoint (dashboard)
    response = requests.get(f"{BACKEND_URL}/reports/dashboard", headers=new_admin_headers)
    print_response(response, "Access dashboard after login")
    
    dashboard_success = response.status_code == 200
    
    # Check if we can update a worker (protected endpoint)
    update_data = {"name": "Updated Test Admin"}
    response = requests.put(f"{BACKEND_URL}/workers/{admin_id}", json=update_data, headers=new_admin_headers)
    print_response(response, "Update worker after login")
    
    update_success = response.status_code == 200
    
    # Check if we can access job cost report (protected endpoint)
    job_response = requests.get(f"{BACKEND_URL}/jobs", headers=new_admin_headers)
    job_cost_success = False
    
    if job_response.status_code == 200 and len(job_response.json()) > 0:
        job_id = job_response.json()[0]["id"]
        response = requests.get(f"{BACKEND_URL}/reports/job-costs/{job_id}", headers=new_admin_headers)
        print_response(response, "Access job cost report after login")
        job_cost_success = response.status_code == 200
    
    print("\nAdmin authentication test completed")
    return dashboard_success and update_success and job_cost_success

def test_time_entry_editing():
    print_separator()
    print("TESTING TIME ENTRY EDITING ENDPOINT")
    print_separator()
    
    # 1. Create a test worker and job
    print("\nCreating test worker and job...")
    worker_data = {
        "name": "Test Worker",
        "email": "testworker@ldagroup.co.uk",
        "phone": "07700 900666",
        "role": "worker"
    }
    response = requests.post(f"{BACKEND_URL}/workers", json=worker_data, headers=ADMIN_HEADERS)
    print_response(response, "Create test worker")
    
    if response.status_code != 200:
        print("Failed to create worker, cannot continue test")
        return False
    
    worker_id = response.json()["id"]
    
    job_data = {
        "name": "Test Job",
        "description": "Job for testing time entry editing",
        "location": "Test Location",
        "client": "Test Client",
        "quoted_cost": 5000.00
    }
    response = requests.post(f"{BACKEND_URL}/jobs", json=job_data, headers=ADMIN_HEADERS)
    print_response(response, "Create test job")
    
    if response.status_code != 200:
        print("Failed to create job, cannot continue test")
        return False
    
    job_id = response.json()["id"]
    
    # 2. Create a time entry (clock in)
    print("\nCreating time entry...")
    clock_in_data = {
        "worker_id": worker_id,
        "job_id": job_id,
        "gps_location": LONDON_COORDINATES,
        "notes": "Test time entry for editing"
    }
    response = requests.post(f"{BACKEND_URL}/time-entries/clock-in", json=clock_in_data)
    print_response(response, "Create time entry")
    
    if response.status_code != 200:
        print("Failed to create time entry, cannot continue test")
        return False
    
    entry_id = response.json()["id"]
    
    # Wait a bit to have some duration
    print("\nWaiting 3 seconds before clocking out...")
    time.sleep(3)
    
    # Clock out
    clock_out_data = {
        "gps_location": LONDON_COORDINATES,
        "notes": "Completed test time entry"
    }
    response = requests.put(f"{BACKEND_URL}/time-entries/{entry_id}/clock-out", json=clock_out_data)
    print_response(response, "Clock out time entry")
    
    # 3. Test updating the time entry using PUT /api/time-entries/{entry_id}
    print("\nTesting time entry update...")
    
    # Get the current time entry to see original values
    response = requests.get(f"{BACKEND_URL}/time-entries?worker_id={worker_id}")
    print_response(response, "Get original time entry")
    
    original_entry = None
    if response.status_code == 200:
        entries = response.json()
        for entry in entries:
            if entry["id"] == entry_id:
                original_entry = entry
                break
    
    if not original_entry:
        print("Could not find original time entry, cannot continue test")
        return False
    
    # Update the time entry with new notes
    print("\nUpdating time entry notes...")
    update_data = {
        "notes": "Updated test time entry notes"
    }
    response = requests.put(f"{BACKEND_URL}/time-entries/{entry_id}", json=update_data, headers=ADMIN_HEADERS)
    print_response(response, "Update time entry notes")
    
    notes_update_success = response.status_code == 200
    
    # 4. Verify the time entry is updated correctly
    response = requests.get(f"{BACKEND_URL}/time-entries?worker_id={worker_id}")
    print_response(response, "Get updated time entry")
    
    # 5. Test updating both clock_in and clock_out times
    print("\nUpdating clock_in and clock_out times...")
    
    # Get current times
    original_clock_in = original_entry["clock_in"]
    original_clock_out = original_entry["clock_out"]
    
    # Create new times (30 minutes earlier for clock_in, 30 minutes later for clock_out)
    clock_in_dt = datetime.fromisoformat(original_clock_in.replace('Z', '+00:00')) - timedelta(minutes=30)
    clock_out_dt = datetime.fromisoformat(original_clock_out.replace('Z', '+00:00')) + timedelta(minutes=30)
    
    # Format for API
    new_clock_in = clock_in_dt.isoformat()
    new_clock_out = clock_out_dt.isoformat()
    
    update_data = {
        "clock_in": new_clock_in,
        "clock_out": new_clock_out
    }
    response = requests.put(f"{BACKEND_URL}/time-entries/{entry_id}", json=update_data, headers=ADMIN_HEADERS)
    print_response(response, "Update clock_in and clock_out times")
    
    times_update_success = response.status_code == 200
    
    # 6. Verify duration is calculated correctly
    response = requests.get(f"{BACKEND_URL}/time-entries?worker_id={worker_id}")
    print_response(response, "Get time entry with updated times")
    
    duration_correct = False
    if response.status_code == 200:
        entries = response.json()
        for entry in entries:
            if entry["id"] == entry_id:
                updated_entry = entry
                # Calculate expected duration (in minutes)
                expected_duration = int((clock_out_dt - clock_in_dt).total_seconds() / 60)
                actual_duration = updated_entry["duration_minutes"]
                
                print(f"\nDuration calculation check:")
                print(f"Expected duration: {expected_duration} minutes")
                print(f"Actual duration: {actual_duration} minutes")
                print(f"Duration calculation is {'correct' if expected_duration == actual_duration else 'incorrect'}")
                
                duration_correct = expected_duration == actual_duration
                break
    
    print("\nTime entry editing test completed")
    return notes_update_success and times_update_success and duration_correct

def test_uk_timezone_handling():
    print_separator()
    print("TESTING UK TIMEZONE HANDLING")
    print_separator()
    
    # 1. Create a test worker and job
    print("\nCreating test worker and job...")
    worker_data = {
        "name": "UK Test Worker",
        "email": "ukworker@ldagroup.co.uk",
        "phone": "07700 900777",
        "role": "worker"
    }
    response = requests.post(f"{BACKEND_URL}/workers", json=worker_data, headers=ADMIN_HEADERS)
    print_response(response, "Create UK test worker")
    
    if response.status_code != 200:
        print("Failed to create worker, cannot continue test")
        return False
    
    worker_id = response.json()["id"]
    
    job_data = {
        "name": "UK Timezone Test Job",
        "description": "Job for testing UK timezone handling",
        "location": "London, UK",
        "client": "UK Test Client",
        "quoted_cost": 3000.00
    }
    response = requests.post(f"{BACKEND_URL}/jobs", json=job_data, headers=ADMIN_HEADERS)
    print_response(response, "Create UK test job")
    
    if response.status_code != 200:
        print("Failed to create job, cannot continue test")
        return False
    
    job_id = response.json()["id"]
    
    # 2. Create a time entry spanning midnight
    print("\nCreating time entry spanning midnight...")
    
    # Get current UK time
    now = datetime.now()
    
    # Create a time entry with clock_in at 11:30 PM and clock_out at 12:30 AM
    clock_in_time = now.replace(hour=23, minute=30, second=0, microsecond=0)
    clock_out_time = clock_in_time + timedelta(hours=1)  # This will be 00:30 the next day
    
    # Format for API
    clock_in_str = clock_in_time.isoformat()
    clock_out_str = clock_out_time.isoformat()
    
    # First create a normal time entry
    clock_in_data = {
        "worker_id": worker_id,
        "job_id": job_id,
        "gps_location": LONDON_COORDINATES,
        "notes": "UK timezone test entry"
    }
    response = requests.post(f"{BACKEND_URL}/time-entries/clock-in", json=clock_in_data)
    print_response(response, "Create initial time entry")
    
    if response.status_code != 200:
        print("Failed to create time entry, cannot continue test")
        return False
    
    entry_id = response.json()["id"]
    
    # Clock out
    clock_out_data = {
        "gps_location": LONDON_COORDINATES,
        "notes": "Completed UK timezone test"
    }
    response = requests.put(f"{BACKEND_URL}/time-entries/{entry_id}/clock-out", json=clock_out_data)
    print_response(response, "Clock out time entry")
    
    # Now update the times to span midnight
    update_data = {
        "clock_in": clock_in_str,
        "clock_out": clock_out_str
    }
    response = requests.put(f"{BACKEND_URL}/time-entries/{entry_id}", json=update_data, headers=ADMIN_HEADERS)
    print_response(response, "Update time entry to span midnight")
    
    update_success = response.status_code == 200
    
    # Verify duration is calculated correctly
    response = requests.get(f"{BACKEND_URL}/time-entries?worker_id={worker_id}")
    print_response(response, "Get time entry with midnight span")
    
    duration_correct = False
    if response.status_code == 200:
        entries = response.json()
        for entry in entries:
            if entry["id"] == entry_id:
                # Calculate expected duration (in minutes)
                expected_duration = 60  # 1 hour = 60 minutes
                actual_duration = entry["duration_minutes"]
                
                print(f"\nUK Timezone Duration Check:")
                print(f"Clock In: {clock_in_str}")
                print(f"Clock Out: {clock_out_str}")
                print(f"Expected duration: {expected_duration} minutes")
                print(f"Actual duration: {actual_duration} minutes")
                print(f"Duration calculation is {'correct' if expected_duration == actual_duration else 'incorrect'}")
                
                duration_correct = expected_duration == actual_duration
                break
    
    print("\nUK timezone handling test completed")
    return update_success and duration_correct

def run_tests():
    print("\n\n")
    print("="*80)
    print("TESTING BUG FIXES FOR LDA GROUP TIME TRACKING API")
    print("="*80)
    
    # Run tests for bug fixes
    admin_auth_result = test_new_admin_authentication()
    time_entry_edit_result = test_time_entry_editing()
    uk_timezone_result = test_uk_timezone_handling()
    
    print("\n\n")
    print("="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"New Admin Authentication: {'PASSED' if admin_auth_result else 'FAILED'}")
    print(f"Time Entry Editing: {'PASSED' if time_entry_edit_result else 'FAILED'}")
    print(f"UK Timezone Handling: {'PASSED' if uk_timezone_result else 'FAILED'}")
    print("="*80)
    print("TESTS COMPLETED")
    print("="*80)

if __name__ == "__main__":
    run_tests()