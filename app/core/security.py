from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from jose import jwt
from ..config import settings
import secrets

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.STRIPE_SECRET_KEY, algorithm=ALGORITHM) # Using Stripe key as secret for simplicity
    return encoded_jwt

def generate_reset_token():
    """Generates a secure, URL-safe token for password reset."""
    return secrets.token_urlsafe(32)
