from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel
from typing import List
import jwt
import datetime
from app.core.database import get_db

router = APIRouter()

SECRET_KEY = "super-secret-key-for-data-hygiene" # In production, use os.environ.get("JWT_SECRET")
ALGORITHM = "HS256"

class LoginRequest(BaseModel):
    username: str
    password: str

import hashlib

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str
    name: str = ""
    email: str = ""
    benchmarkCategories: List[str] = []
    specialAdminPassword: str = ""

async def resolve_expertise_from_db(user_expertise: list, db) -> list:
    resolved_categories = set()
    
    # Get all valid benchmarkCategory values currently in the masterlist
    categories_cursor = db["masterlist"].find(
        {"type": "benchmarkType"},
        {"data.metadata.benchmarkCategory": 1}
    )
    all_known_cats = set()
    async for doc in categories_cursor:
        cat = doc.get("data", {}).get("metadata", {}).get("benchmarkCategory")
        if cat:
            all_known_cats.add(cat)
            
    for item in user_expertise:
        if not item:
            continue
        item_str = str(item).strip()
        
        # Scenario A: The item is already a known benchmarkCategory (case-insensitive check)
        matched_cat = None
        for known_cat in all_known_cats:
            if known_cat.lower() == item_str.lower():
                matched_cat = known_cat
                break
        
        if matched_cat:
            resolved_categories.add(matched_cat)
            continue
            
        # Scenario B: Try to look up as a benchmarkType name
        benchmark_doc = await db["masterlist"].find_one({
            "type": "benchmarkType",
            "data.value": {"$regex": f"^{item_str}$", "$options": "i"}
        })
        if benchmark_doc:
            cat = benchmark_doc.get("data", {}).get("metadata", {}).get("benchmarkCategory")
            if cat:
                resolved_categories.add(cat)
                continue
                
        # Scenario C: Case-insensitive fallback lookup directly on category fields
        fallback_doc = await db["masterlist"].find_one({
            "type": "benchmarkType",
            "data.metadata.benchmarkCategory": {"$regex": f"^{item_str}$", "$options": "i"}
        })
        if fallback_doc:
            cat = fallback_doc.get("data", {}).get("metadata", {}).get("benchmarkCategory")
            if cat:
                resolved_categories.add(cat)
                continue
                
        # Scenario D: If no database record matched, just pass it through gracefully
        resolved_categories.add(item_str)
        
    return sorted(list(resolved_categories)) if resolved_categories else sorted(list(all_known_cats))

@router.post("/login")
async def login(credentials: LoginRequest):
    username = credentials.username
    password = credentials.password
    
    db = get_db()
    # Support lookup via username or email
    user = await db["users"].find_one({
        "$or": [
            {"username": username.strip()},
            {"email": username.strip()}
        ]
    })
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    # Check plaintext (legacy fallback), SHA-256 (new users), or SHA-1 (seeded database users) hashed password
    stored_password = user.get("password")
    hashed_sha256 = hashlib.sha256(password.encode()).hexdigest()
    hashed_sha1 = hashlib.sha1(password.encode()).hexdigest()
    
    if stored_password != password and stored_password != hashed_sha256 and stored_password != hashed_sha1:
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    role = user.get("role", "SME")
    raw_categories = user.get("benchmarkCategories", user.get("expertise", []))
    benchmark_categories = await resolve_expertise_from_db(raw_categories, db)
    
    # Generate JWT Token (expires in 24 hours) with embedded claims
    expiration = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    token_payload = {
        "sub": username,
        "role": role,
        "emailid": user.get("email", ""),
        "expertise": benchmark_categories,
        "exp": expiration
    }
    
    token = jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)
    
    return {
        "status": "success", 
        "token": token, 
        "username": username,
        "role": role,
        "emailid": user.get("email", ""),
        "expertise": benchmark_categories
    }

@router.post("/register")
async def register(req: RegisterRequest):
    db = get_db()
    
    # Normalize input
    username = req.username.strip()
    role = req.role.strip().upper()
    special_admin_pwd = req.specialAdminPassword.strip() if req.specialAdminPassword else ""
    
    if role == "ADMIN":
        if special_admin_pwd == "AdminPassSecure":
            role = "ADMIN"
        else:
            role = "SME"
            
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")
        
    if role not in ["ADMIN", "SME"]:
        raise HTTPException(status_code=400, detail="Invalid role specified. Must be ADMIN or SME")
        
    # Check if user already exists
    existing_user = await db["users"].find_one({"username": username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")
        
    # Hash the password
    hashed_password = hashlib.sha256(req.password.encode()).hexdigest()
    
    # Build user document matching requested layout
    user_doc = {
        "name": req.name.strip() if req.name else username,
        "email": req.email.strip() if req.email else f"{username}@gmail.com",
        "username": username,
        "password": hashed_password,
        "benchmarkCategories": req.benchmarkCategories if role == "SME" else [],
        "role": role,
        "createdAt": datetime.datetime.utcnow()
    }
    
    await db["users"].insert_one(user_doc)
    
    return {
        "status": "success",
        "message": "User registered successfully",
        "username": username,
        "role": role
    }

@router.get("/verify")
async def verify_token(request: Request):
    """
    Called internally by NGINX auth_request to validate the token.
    If it returns 200 OK, NGINX forwards the request to the real API.
    If it returns 401, NGINX blocks the request.
    """
    auth_header = request.headers.get("Authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        
    token = auth_header.split(" ")[1]
    
    try:
        # Verify the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Return 200 OK (Content doesn't matter to NGINX, just the status code)
        return Response(status_code=200)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
