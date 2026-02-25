from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from .db import get_db
from .models import Client
from .core.security import get_password_hash, verify_password, create_access_token, generate_reset_token
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["authentication"])

class UserRegister(BaseModel):
    email: str
    password: str
    name: str
    phone: str
    rodo_accepted: bool

class UserLogin(BaseModel):
    email: str
    password: str

@router.post("/register")
def register(user: UserRegister, db: Session = Depends(get_db)):
    if not user.rodo_accepted:
        raise HTTPException(status_code=400, detail="Zgoda RODO jest wymagana.")
    
    # 1. Check if exists
    if db.query(Client).filter(Client.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email już zajęty.")
    
    # 2. Hash password & Save (We need to add password field to Client model first!)
    # client = Client(email=user.email, name=user.name, phone=user.phone, password_hash=get_password_hash(user.password))
    # db.add(client)
    # db.commit()
    return {"msg": "Konto utworzone. Sprawdź email, aby potwierdzić."}

@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    # Mock login logic until DB migration
    if user.email == "admin@danex.pl" and user.password == "admin":
        token = create_access_token({"sub": user.email, "role": "admin"})
        return {"access_token": token, "token_type": "bearer"}
    
    raise HTTPException(status_code=401, detail="Błędne dane logowania.")

@router.post("/reset-password")
def request_password_reset(email: str):
    token = generate_reset_token()
    # Logic to send email with link: https://danex.pl/reset?token=...
    return {"msg": "Jeśli konto istnieje, wysłaliśmy link resetujący."}
