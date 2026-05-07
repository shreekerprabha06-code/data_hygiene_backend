import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def count():
    c = AsyncIOMotorClient('mongodb://127.0.0.1:27017')
    db = c.data_hygiene
    print("ExecutionInfo:", await db.Executioninfo.count_documents({}))
    print("Snapshot:", await db.snapshot.count_documents({}))
    print("Masterlist:", await db.masterlist.count_documents({}))

asyncio.run(count())
