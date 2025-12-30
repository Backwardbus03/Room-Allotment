import requests
import pandas as pd
import os
import json

# Setup Dummy Data
os.makedirs("test_data", exist_ok=True)

# 1. Blocks File
df_blocks = pd.DataFrame({
    "Room": ["Room A", "Room B"],
    "Capacity": [30, 30]
})
df_blocks.to_excel("test_data/blocks.xlsx", index=False)

# 2. Supervisors File
df_sups = pd.DataFrame({
    "Name": ["Alice", "Bob", "Charlie"]
})
df_sups.to_excel("test_data/supervisors.xlsx", index=False)

BASE_URL = "http://127.0.0.1:5000"
session = requests.Session()

def run_test():
    print("--- Starting Verification Test ---")
    
    # 1. Test Admin Login
    print("[1] Testing Admin Login...")
    resp = session.post(f"{BASE_URL}/login", data={"role": "admin", "password": "admin"})
    if resp.url.endswith("/admin"):
        print("    -> Success: Admin logged in.")
    else:
        print(f"    -> FAILED: Admin login failed. Url: {resp.url}")
        return

    # 2. Upload Files (Configure)
    print("[2] Uploading Files...")
    with open("test_data/blocks.xlsx", "rb") as f1, open("test_data/supervisors.xlsx", "rb") as f2:
        files = {
            "blocks_file": f1,
            "supervisors_file": f2
        }
        resp = session.post(f"{BASE_URL}/configure", files=files)
        
    if "Configure Sessions" in resp.text or 'rooms_json' in resp.text: # Check for content in configure html
        print("    -> Success: Files uploaded, on configure page.")
    else:
        print("    -> FAILED: Upload failed.")
        # print(resp.text)
        return

    # Extract JSONs (Simulate what the browser would do, or just proceed)
    # Ideally we'd parse the HTML but for speed let's just constructing the Generate request manually
    # assuming we know what IDs we would have used.
    # Actually, the configure page renders the JSON into hidden fields. 
    # Let's simple-mock the generate request since we know the logic.
    
    rooms_json = json.dumps([{"name": "Room A", "capacity": 30}, {"name": "Room B", "capacity": 30}])
    supervisors_json = json.dumps(["Alice", "Bob", "Charlie"])
    
    print("[3] Generating Schedule...")
    data = {
        "rooms_json": rooms_json,
        "supervisors_json": supervisors_json,
        "session_ids": ["1"],
        "day_1": "1",
        "session_type_1": "Morning",
        "total_students_1": "50",
    }
    
    resp = session.post(f"{BASE_URL}/generate", data=data)
    
    if "Exam Schedule Generated" in resp.text:
         print("    -> Success: Schedule Generated.")
    else:
         print("    -> FAILED: Generation failed.")
         return

    # 3. Logout
    print("[4] Logging out Admin...")
    session.get(f"{BASE_URL}/logout")
    
    # 4. Supervisor Login (Alice - Should have duties)
    print("[5] Testing Supervisor Login (Alice)...")
    resp = session.post(f"{BASE_URL}/login", data={"role": "supervisor", "name": "Alice"})
    if "Welcome, Alice" in resp.text:
        print("    -> Success: Alice logged in.")
        if "Day 1" in resp.text:
             print("    -> Success: Alice sees schedule.")
        else:
             print("    -> WARNING: Alice has no schedule displayed (might be valid if she wasn't picked).")
    else:
        print("    -> FAILED: Alice login failed.")

    # 5. Supervisor Login (Non-existent)
    print("[6] Testing Invalid Supervisor Login...")
    session.get(f"{BASE_URL}/logout")
    resp = session.post(f"{BASE_URL}/login", data={"role": "supervisor", "name": "Zack"})
    if "Supervisor name not found" in resp.text or resp.url.endswith("/login"):
        print("    -> Success: Zack rejected.")
    else:
        print("    -> FAILED: Zack was allowed in.")

    print("\n--- Test Complete ---")

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"Test failed with exception: {e}")
        print("Is the server running?")
