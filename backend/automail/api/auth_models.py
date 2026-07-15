"""Request and response models for auth endpoints."""

from pydantic import Field

from automail.models import CamelCaseModel


class AuthResponse(CamelCaseModel):
    token: str
    email: str
    language: str = "en"
    tenant_id: str
    tenant_name: str
    is_root: bool
    is_platform_admin: bool = False
    tenant_account_type: str = "normal"
    capabilities: dict[str, bool] = Field(default_factory=dict)
    must_change_password: bool


class LoginCodeRequest(CamelCaseModel):
    email: str


class LoginMethodResponse(CamelCaseModel):
    method: str


class VerifyLoginCodeRequest(CamelCaseModel):
    email: str
    code: str


class PasswordLoginRequest(CamelCaseModel):
    email: str
    password: str


class SignupRequest(CamelCaseModel):
    company_name: str = ""
    email: str
    password: str


class SignupResponse(CamelCaseModel):
    verification_required: bool
    email: str
    message: str
