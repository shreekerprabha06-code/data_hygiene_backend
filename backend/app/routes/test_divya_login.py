import asyncio
import sys
# Add backend directory to path
sys.path.append("c:\\Users\\user\\Desktop\\Data Hygiene New Masterlist POC FINAL MONDOY\\Data Hygiene New Masterlist\\backend")

from app.core.database import get_db
from app.routes.auth import resolve_expertise_from_db

async def run_test():
    db = get_db()
    user = await db["users"].find_one({"username": "divya_admin"})
    print("USER FROM DB:")
    print(user)
    
    raw_categories = user.get("benchmarkCategories", user.get("expertise", []))
    print(f"\nRAW CATEGORIES: {raw_categories}")
    
    benchmark_categories = await resolve_expertise_from_db(raw_categories, db)
    print(f"\nRESOLVED EXPERTISE CATEGORIES: {benchmark_categories}")

if __name__ == "__main__":
    asyncio.run(run_test())
