import bcrypt
import random
from datetime import datetime, timedelta

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        # Fallback for plain text passwords in legacy DBs
        return plain_password == hashed_password

def generate_code() -> str:
    return str(random.randint(100000, 999999))

def future_minutes(minutes: int) -> str:
    return (datetime.now() + timedelta(minutes=minutes)).isoformat()
