from pydantic import BaseModel


class LoginRequest(BaseModel):
    password: str


class SetupRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SetupStatus(BaseModel):
    is_configured: bool
