import uuid

from pydantic import BaseModel, EmailStr, Field

from app.auth.permissions import Role


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class MemberAdd(BaseModel):
    email: EmailStr
    role: Role


class MemberRoleUpdate(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    role: Role
