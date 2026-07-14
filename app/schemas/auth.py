import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None
    # Self-service admin signup is intentionally NOT exposed here.
    # The only admin account in Milestone 1 is seeded on startup (see main.py).
    # Promoting a user to admin is an explicit Admin-only action (Milestone 7).


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}
