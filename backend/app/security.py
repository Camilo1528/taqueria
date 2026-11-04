import os
import secrets
import bcrypt
import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv

from app.paths import DATA_DIR

load_dotenv()


def _load_secret_key() -> str:
    """Lee JWT_SECRET del entorno; si no existe, genera una clave aleatoria
    y la guarda en data/.jwt_secret para que sobreviva reinicios."""
    env_key = os.getenv("JWT_SECRET")
    if env_key:
        return env_key
    key_file = DATA_DIR / ".jwt_secret"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    key_file.write_text(key, encoding="utf-8")
    return key


SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Nunca aceptar contraseñas guardadas en texto plano.
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except (ValueError, TypeError, AttributeError):
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=12))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
