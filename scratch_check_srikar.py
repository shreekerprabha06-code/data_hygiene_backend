import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def check_user():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['data_hygiene']
    user = await db['users'].find_one({"username": "srikar_sme"})
    if user:
        print(f"User: {user.get('username')}, Role: {user.get('role')}, Status: {user.get('status')}, Exp: {user.get('expertise')}")
    else:
        print("srikar_sme not found!")

if __name__ == "__main__":
    asyncio.run(check_user())
