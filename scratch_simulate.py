import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def simulate_logic(username):
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['data_hygiene']
    
    # 1. Requester
    db_user = await db["users"].find_one({"$or": [{"username": username}, {"email": username}]})
    if not db_user:
        print(f"Requester {username} not found")
        return

    my_expertise_raw = db_user.get("benchmarkCategories") or db_user.get("expertise") or []
    if isinstance(my_expertise_raw, str):
        my_expertise_raw = [c.strip() for c in my_expertise_raw.split(",") if c.strip()]
    my_expertise = [str(c).strip().lower() for c in my_expertise_raw]
    print(f"Requester {username} expertise: {my_expertise}")

    # 2. Others
    all_users = await db["users"].find(
        {"role": {"$in": ["SME", "Admin", "ADMIN", "sme"]}, "status": {"$nin": ["Inactive", "inactive"]}}
    ).to_list(None)
    print(f"Total candidate users: {len(all_users)}")

    matches = []
    for u in all_users:
        u_name = u.get("username")
        u_email = u.get("email")
        if u_name == username or u_email == db_user.get("email"):
            continue
            
        u_cats_raw = u.get("benchmarkCategories") or u.get("expertise") or []
        if isinstance(u_cats_raw, str):
            u_cats_raw = [c.strip() for c in u_cats_raw.split(",") if c.strip()]
        u_cats = [str(c).strip().lower() for c in u_cats_raw]
        
        overlap = [cat for cat in u_cats if cat in my_expertise]
        if overlap:
            print(f"MATCH: {u_name} shares {overlap}")
            matches.append(u_name)
        else:
            # print(f"NO MATCH: {u_name} has {u_cats}")
            pass

    print(f"Final matches for {username}: {matches}")

if __name__ == "__main__":
    asyncio.run(simulate_logic('divya_admin'))
