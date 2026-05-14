import motor.motor_asyncio
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def inspect():
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    db_name = os.getenv("DB_NAME", "data_hygiene")
    client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    db = client[db_name]
    
    cols = await db.list_collection_names()
    print(f"Collections found in '{db_name}':")
    for c in cols:
        count = await db[c].count_documents({})
        print(f"- {c}: {count} records")

if __name__ == "__main__":
    asyncio.run(inspect())
