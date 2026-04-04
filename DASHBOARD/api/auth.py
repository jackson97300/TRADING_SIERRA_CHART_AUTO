"""Module d'authentification JWT pour le dashboard MIA.

JWT manuel (base64 + hmac) — zero dependance externe.
Stockage users.json (phase 1 — SQLite viendra plus tard).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from DASHBOARD.config import JWT_SECRET

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")
TOKEN_EXPIRY_SEC = 86400  # 24h


# ---------------------------------------------------------------------------
# Modeles Pydantic
# ---------------------------------------------------------------------------
class RegisterBody(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str


class LoginBody(BaseModel):
    email: str
    password: str


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _load_users() -> dict:
    """Lit users.json et retourne un dict {email: {...}}."""
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_users(users: dict) -> None:
    """Ecrit users.json avec indent=2."""
    with open(USERS_FILE, "w", encoding="utf-8") as fh:
        json.dump(users, fh, indent=2, ensure_ascii=False)


def _hash_password(password: str, salt: str) -> str:
    """PBKDF2-HMAC SHA256, 100 000 iterations."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    ).hex()


def _base64url_encode(data: bytes) -> str:
    """Encode en base64url sans padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
    """Decode base64url en ajoutant le padding manquant."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _create_token(email: str, tier: str) -> str:
    """Cree un JWT HS256 manuellement."""
    now = int(time.time())
    header = _base64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = _base64url_encode(
        json.dumps(
            {"sub": email, "tier": tier, "exp": now + TOKEN_EXPIRY_SEC, "iat": now},
            separators=(",", ":"),
        ).encode()
    )
    signature = _base64url_encode(
        hmac.new(
            JWT_SECRET.encode("utf-8"),
            f"{header}.{payload}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    return f"{header}.{payload}.{signature}"


def _verify_token(token: str) -> Optional[dict]:
    """Verifie signature HMAC + expiration. Retourne le payload ou None."""
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts

    # Verification signature
    expected_sig = _base64url_encode(
        hmac.new(
            JWT_SECRET.encode("utf-8"),
            f"{header_b64}.{payload_b64}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(expected_sig, sig_b64):
        return None

    # Decode payload
    try:
        payload = json.loads(_base64url_decode(payload_b64))
    except (json.JSONDecodeError, Exception):
        return None

    # Verification expiration
    exp = payload.get("exp", 0)
    if int(time.time()) > exp:
        return None

    return payload


# ---------------------------------------------------------------------------
# Fonctions exportees
# ---------------------------------------------------------------------------

def get_current_user(authorization: Optional[str] = None) -> Optional[dict]:
    """Extrait et verifie le token du header Authorization.

    Retourne le payload JWT ou None.
    """
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    return _verify_token(token)


def get_user_tier(authorization: Optional[str] = None) -> str:
    """Retourne le tier depuis le token, ou 'free' si absent/invalide."""
    payload = get_current_user(authorization)
    if not payload:
        return "free"
    return payload.get("tier", "free")


# ---------------------------------------------------------------------------
# Router FastAPI
# ---------------------------------------------------------------------------
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/register")
async def register(body: RegisterBody):
    """Inscription d'un nouvel utilisateur."""
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Email invalide.")

    if len(body.password) < 6:
        raise HTTPException(status_code=422, detail="Mot de passe trop court (6 caracteres minimum).")

    users = _load_users()
    if email in users:
        raise HTTPException(status_code=409, detail="Cet email est deja utilise.")

    salt = secrets.token_hex(16)
    hashed = _hash_password(body.password, salt)

    users[email] = {
        "first_name": body.first_name.strip(),
        "last_name": body.last_name.strip(),
        "salt": salt,
        "password_hash": hashed,
        "tier": "free",
        "created": int(time.time()),
    }
    _save_users(users)

    token = _create_token(email, "free")
    return {"token": token, "tier": "free"}


@auth_router.post("/login")
async def login(body: LoginBody):
    """Connexion d'un utilisateur existant."""
    email = body.email.strip().lower()
    users = _load_users()

    user = users.get(email)
    if not user:
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")

    hashed = _hash_password(body.password, user["salt"])
    if not hmac.compare_digest(hashed, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")

    tier = user.get("tier", "free")
    token = _create_token(email, tier)
    return {"token": token, "tier": tier}
