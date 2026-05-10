from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    active: bool
    must_change_password: Optional[bool] = False

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str  # tambem setado em cookie httpOnly
    token_type: str = "bearer"
    must_change_password: bool = False
    user: UserResponse


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str = Field(min_length=8)
    role: str = "analyst"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)
