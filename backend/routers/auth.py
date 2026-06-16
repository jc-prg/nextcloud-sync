from fastapi import APIRouter, HTTPException, status

from backend.auth import create_access_token, hash_password, is_setup_done, verify_password
from backend.config import settings
from backend.schemas.auth import LoginRequest, SetupRequest, SetupStatus, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=SetupStatus)
async def setup_status() -> SetupStatus:
    return SetupStatus(is_configured=is_setup_done())


@router.post("/setup", response_model=TokenResponse)
async def setup(body: SetupRequest) -> TokenResponse:
    """First-run only: set the application password. Locked once configured."""
    if is_setup_done():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Already configured")
    if len(body.password) < 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must be at least 8 characters")

    hashed = hash_password(body.password)

    # Persist to .env so it survives restarts
    _write_env_var("APP_PASSWORD_HASH", hashed)

    # Reload settings in-process
    settings.app_password_hash = hashed

    return TokenResponse(access_token=create_access_token())


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    if not is_setup_done():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="App not configured yet")
    if not verify_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    return TokenResponse(access_token=create_access_token())


def _write_env_var(key: str, value: str) -> None:
    """Upsert a key=value line in .env."""
    from pathlib import Path

    env_path = Path(".env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n")
