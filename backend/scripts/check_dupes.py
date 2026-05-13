import asyncio
from app.core.database import get_db, EXECUTION_INFO_COL

async def check():
    db = get_db()
    col = db[EXECUTION_INFO_COL]

    # Find duplicate benchmarkExecutionIDs
    pipeline = [
        {"$group": {"_id": "$benchmarkExecutionID", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20}
    ]
    dupes = await col.aggregate(pipeline).to_list(20)

    if not dupes:
        print("No duplicate benchmarkExecutionIDs found. All IDs are unique.")
        # Verify total count
        total = await col.count_documents({})
        distinct = len(await col.distinct("benchmarkExecutionID"))
        print(f"Total records: {total} | Distinct IDs: {distinct}")
    else:
        print(f"Found {len(dupes)} duplicate groups:")
        for d in dupes:
            print(f"  benchmarkExecutionID: {d['_id']}  ->  {d['count']} copies")

asyncio.run(check())
