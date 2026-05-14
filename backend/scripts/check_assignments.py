import motor.motor_asyncio
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def check_real_data():
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    db_name = os.getenv("DB_NAME", "data_hygiene")
    client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    db = client[db_name]
    
    # Use the name from .env or default to Executioninfo
    col_name = os.getenv("COLLECTION_EXECUTION_INFO", "Executioninfo")
    print(f"Checking collection: {col_name}")
    
    total = await db[col_name].count_documents({})
    assigned = await db[col_name].count_documents({"assignment.status": "ASSIGNED"})
    
    print(f"Total Records: {total}")
    print(f"Assigned Records: {assigned}")
    
    if assigned > 0:
        cursor = db[col_name].find({"assignment.status": "ASSIGNED"}).limit(3)
        async for doc in cursor:
            print(f"- ID: {doc.get('benchmarkExecutionID')}, SME: {doc.get('assignment', {}).get('assigned_sme')}")
    else:
        # Check what the stages and categories are for unassigned records
        cats = await db[col_name].distinct("benchmarkCategory")
        stages = await db[col_name].distinct("stage")
        print(f"Categories present: {cats}")
        print(f"Stages present: {stages}")

if __name__ == "__main__":
    asyncio.run(check_real_data())
