import asyncio
import sys
# Add backend directory to path
sys.path.append("c:\\Users\\user\\Desktop\\Data Hygiene New Masterlist POC FINAL MONDOY\\Data Hygiene New Masterlist\\backend")

from app.core.database import get_db

async def run_test():
    db = get_db()
    
    # Let's get distinct benchmarkCategory in Executioninfo
    distinct_cats = await db["Executioninfo"].distinct("benchmarkCategory")
    print(f"DISTINCT CATEGORIES IN EXECUTIONINFO: {distinct_cats}")
    
    # Check if there are any documents with category matching 'Crypto' or 'SPEC' (case-insensitive)
    for cat in ["Crypto", "SPEC"]:
        cnt = await db["Executioninfo"].count_documents({"benchmarkCategory": {"$regex": f"^{cat}$", "$options": "i"}})
        print(f"Count of '{cat}': {cnt}")
        
    # Check if there are any documents with category matching 'SPEC' but wait, SPEC isn't a direct category, is it?
    # Let's find one sample document for SPEC in masterlist or Executioninfo
    sample_spec = await db["masterlist"].find_one({"type": "benchmarkType", "data.value": {"$regex": "spec", "$options": "i"}})
    print(f"\nSAMPLE MASTERLIST SPEC DOCUMENT: {sample_spec}")

if __name__ == "__main__":
    asyncio.run(run_test())
