import motor.motor_asyncio
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def diagnose():
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    db_name = os.getenv("DB_NAME", "data_hygiene")
    client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    db = client[db_name]
    
    # 1. Check Categories in Records
    cats = await db["ExecutionInfo"].distinct("benchmarkCategory")
    print(f"Benchmark Categories found in Records: {cats}")
    
    # 2. Check User Expertise
    users = await db["users"].find({"status": "Active"}).to_list(100)
    print("\nActive Users and Expertise:")
    for u in users:
        exp = u.get("benchmarkCategories", u.get("expertise", []))
        print(f"- {u.get('username')} ({u.get('role')}): {exp}")
    
    # 3. Check for unassigned records
    unassigned = await db["ExecutionInfo"].count_documents({"assignment.status": {"$ne": "ASSIGNED"}})
    print(f"\nUnassigned Records: {unassigned}")

if __name__ == "__main__":
    asyncio.run(diagnose())
