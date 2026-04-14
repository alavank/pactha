from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    active: bool

    class Config:
        from_attributes = True


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "analyst"
