from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel
import jwt
import datetime

router = APIRouter()

SECRET_KEY = "super-secret-key-for-data-hygiene" # In production, use os.environ.get("JWT_SECRET")
ALGORITHM = "HS256"

# A dummy database of users (In production, look this up in MongoDB)
USERS = {
    "admin": "password123",
    "tester": "test"
}

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
async def login(credentials: LoginRequest):
    username = credentials.username
    password = credentials.password
    
    # Check if user exists and password is correct
    if username not in USERS or USERS[username] != password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    # Generate JWT Token (expires in 24 hours)
    expiration = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    token = jwt.encode(
        {"sub": username, "exp": expiration}, 
        SECRET_KEY, 
        algorithm=ALGORITHM
    )
    
    return {"status": "success", "token": token, "username": username}

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
