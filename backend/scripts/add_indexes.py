import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import pymongo

async def create_indexes():
    c = AsyncIOMotorClient('mongodb://127.0.0.1:27017')
    db = c.data_hygiene
    
    print("Creating ExecutionInfo indexes...")
    # Indexes for sorting and filtering
    try:
        await db.Executioninfo.create_index([("stage", pymongo.ASCENDING)])
        await db.Executioninfo.create_index([("lastModifiedOn", pymongo.DESCENDING)])
    except Exception as e:
        print(f"Index creation warning: {e}")
    
    print("Creating Snapshot indexes...")
    try:
        await db.snapshot.create_index([("data.standardization_status", pymongo.ASCENDING)])
    except Exception as e:
        print(f"Index creation warning: {e}")
    
    print("Indexes created successfully!")

asyncio.run(create_indexes())
