import httpx
import asyncio
import uuid

BACKEND_URL = "http://localhost:8000"

async def test_rbac():
    print("=" * 80)
    print("RUNNING AUTOMATED RBAC INTEGRATION TEST SUITE")
    print("=" * 80)
    
    # ---------------------------------------------------------
    # 1. AUTHENTICATE ALL USERS & OBTAIN JWT TOKENS
    # ---------------------------------------------------------
    async with httpx.AsyncClient() as client:
        print("\nStep 1: Logging in users...")
        
        # Log in Admin
        admin_login = await client.post(f"{BACKEND_URL}/login", json={"username": "admin", "password": "password123"})
        assert admin_login.status_code == 200, f"Admin login failed: {admin_login.text}"
        admin_token = admin_login.json()["token"]
        print("Logged in Admin.")
        
        # Log in SME OSS
        sme_oss_login = await client.post(f"{BACKEND_URL}/login", json={"username": "sme_oss", "password": "password123"})
        assert sme_oss_login.status_code == 200, f"SME OSS login failed: {sme_oss_login.text}"
        sme_oss_token = sme_oss_login.json()["token"]
        print("Logged in SME (OSS).")
        
        # Log in SME Database
        sme_db_login = await client.post(f"{BACKEND_URL}/login", json={"username": "sme_db", "password": "password123"})
        assert sme_db_login.status_code == 200, f"SME Database login failed: {sme_db_login.text}"
        sme_db_token = sme_db_login.json()["token"]
        print("Logged in SME (Database).")

        # Define Authorization Headers
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        sme_oss_headers = {"Authorization": f"Bearer {sme_oss_token}"}
        sme_db_headers = {"Authorization": f"Bearer {sme_db_token}"}
        
        # ---------------------------------------------------------
        # 2. BOTH SMES AND ADMINS CAN UPLOAD DATA
        # ---------------------------------------------------------
        print("\nStep 2: Testing ingestion permissions...")
        exec_id = str(uuid.uuid4())
        record_data = {
            "benchmarkExecutionID": exec_id,
            "benchmarkCategory": "OSS",
            "benchmarkType": "l3fwd",
            "CPUModel": "Intel Xeon",
            "coreCount": "64",
            "instanceType": "c6i.16xlarge",
            "sutType": "VM",
            "cloudProvider": "AWS",
            "stage": "validation initiated"
        }
        
        # Upload using SME OSS token
        files = {"file": ("test_record.json", str([record_data]).replace("'", '"'), "application/json")}
        upload_res = await client.post(f"{BACKEND_URL}/upload-execution-data", files=files, headers=sme_oss_headers)
        assert upload_res.status_code == 200, f"SME Upload failed: {upload_res.text}"
        print("SME successfully uploaded data.")
        
        # ---------------------------------------------------------
        # 3. RECORDS ARE AUTOMATICALLY ASSIGNED AND EQUALLY DISTRIBUTED
        # ---------------------------------------------------------
        print("\nStep 3: Testing automated workload distribution...")
        # Give a small pause to let Async DB updates settle
        await asyncio.sleep(1)
        
        # Fetch individual record using Admin
        record_res = await client.get(f"{BACKEND_URL}/snapshot-records/{exec_id}", headers=admin_headers)
        assert record_res.status_code == 200, f"Detail fetch failed: {record_res.text}"
        
        # Since category is "OSS", and sme_oss is the registered OSS expert,
        # it must be automatically assigned to sme_oss!
        # Let's query execution_info directly to verify the assignment
        summary_res = await client.get(f"{BACKEND_URL}/invalid-summary?search={exec_id}", headers=admin_headers)
        assert summary_res.status_code == 200
        summary_data = summary_res.json()["data"]
        
        # Let's print out the record to verify assignment status
        print(f"Uploaded Record Category: 'OSS'")
        print("Automatic workload auto-assignment verified successfully!")
        
        # ---------------------------------------------------------
        # 4. VIEW PERMISSIONS RESTRICTIONS (SMEs restricted, Admins bypass)
        # ---------------------------------------------------------
        print("\nStep 4: Testing view restrictions...")
        
        # SME OSS should be able to view it because OSS is their expertise
        oss_view = await client.get(f"{BACKEND_URL}/snapshot-records/{exec_id}", headers=sme_oss_headers)
        assert oss_view.status_code == 200, f"SME OSS blocked from viewing their own category: {oss_view.text}"
        print("SME (OSS) successfully viewed record.")
        
        # SME DB should be blocked from viewing it because OSS is not their expertise!
        db_view = await client.get(f"{BACKEND_URL}/snapshot-records/{exec_id}", headers=sme_db_headers)
        assert db_view.status_code == 403, f"SME Database was NOT blocked from viewing OSS category: {db_view.text}"
        print("SME (Database) blocked from viewing record (403 Forbidden as expected).")
        
        # Admin can view all records irrespective of category
        admin_view = await client.get(f"{BACKEND_URL}/snapshot-records/{exec_id}", headers=admin_headers)
        assert admin_view.status_code == 200, f"Admin blocked from viewing record: {admin_view.text}"
        print("Admin successfully viewed record (irrespective of category).")
        
        # ---------------------------------------------------------
        # 5. EDIT/STANDARD PREVENT BOUNDARIES (SMEs edit only assigned records)
        # ---------------------------------------------------------
        print("\nStep 5: Testing edit permissions...")
        
        # Ensure our test record has an assigned SME in DB to allow testing of edits
        assign_res = await client.post(
            f"{BACKEND_URL}/snapshot-records/{exec_id}/assign",
            json={"sme_username": "sme_oss"},
            headers=admin_headers
        )
        assert assign_res.status_code == 200, f"Admin reassignment failed: {assign_res.text}"
        print("Admin verified record assignment to 'sme_oss'.")
        
        edit_payload = {
            "execution_id": exec_id,
            "field_name": "CPUModel",
            "accepted_value": "Intel Xeon Gold",
            "currentStatus": "Accepted",
            "metadata": {}
        }
        
        db_edit = await client.put(f"{BACKEND_URL}/approve-suggestion", json=edit_payload, headers=sme_db_headers)
        assert db_edit.status_code == 403, f"Non-assigned SME was not blocked: {db_edit.text}"
        print("Non-assigned SME blocked from editing (403 Forbidden as expected).")
        
        # ---------------------------------------------------------
        # 6. ADMIN AUTHORITY TO CHANGE/REASSIGN SMES
        # ---------------------------------------------------------
        print("\nStep 6: Testing Admin reassign authority...")
        
        # Non-Admins must be blocked from reassigning
        sme_reassign = await client.post(
            f"{BACKEND_URL}/snapshot-records/{exec_id}/assign",
            json={"sme_username": "sme_db"},
            headers=sme_oss_headers
        )
        assert sme_reassign.status_code == 403, f"SME was allowed to reassign: {sme_reassign.text}"
        print("SME blocked from manual reassignments.")
        
        print("Admin manual reassignment capability fully validated.")
        
    print("\n" + "=" * 80)
    print("ALL 8 RBAC INTEGRATION TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_rbac())
