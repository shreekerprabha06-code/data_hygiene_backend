import asyncio
import os
import sys

# Ensure backend directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["MONGO_URI"] = "mongodb://localhost:27017/"
os.environ["DB_NAME"] = "data_hygiene"

from motor.motor_asyncio import AsyncIOMotorClient

async def seed_users():
    client = AsyncIOMotorClient("mongodb://localhost:27017/")
    db = client["data_hygiene"]
    col = db["users"]
    
    # Drop existing index if needed and create unique index on username
    await col.create_index("username", unique=True)
    
    users = [
        {
            "username": "admin",
            "password": "password123", # For simplicity and keeping existing login credentials
            "role": "ADMIN",
            "expertise": [], # Empty list for Admins means they can access everything
            "status": "Active"
        },
        {
            "username": "tester",
            "password": "test", # Keeps existing login credentials
            "role": "SME",
            "expertise": ["OSS", "Database", "Cloud"],
            "status": "Active"
        },
        {
            "username": "sme_oss",
            "password": "password123",
            "role": "SME",
            "expertise": ["OSS"],
            "status": "Active"
        },
        {
            "username": "sme_db",
            "password": "password123",
            "role": "SME",
            "expertise": ["Database"],
            "status": "Active"
        }
    ]
    
    for user in users:
        await col.update_one({"username": user["username"]}, {"$set": user}, upsert=True)
        
    print("Database successfully seeded with RBAC users!")
    client.close()

if __name__ == "__main__":
    asyncio.run(seed_users())
