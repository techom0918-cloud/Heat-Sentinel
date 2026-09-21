"""Signup, login, and forgot-password endpoints (Phase 16)."""

from fastapi import APIRouter, Header

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.models.auth import (
    ForgotPasswordResetRequest,
    ForgotPasswordVerifyRequest,
    ForgotPasswordVerifyResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ResetPasswordResponse,
    SecurityQuestionsResponse,
    SignupRequest,
    SignupResponse,
)
from app.models.common import ErrorResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Accounts"])

_DESCRIPTION = """
Lightweight signup/login for personalization -- **not** a production
identity system. Email + password, with answers to 2+ configured security
questions collected at signup as the forgot-password recovery path (no
email or SMS delivery is wired up here, so security questions are the
only recovery mechanism today).

Nothing on this router stores health, demographic, or heat-risk data --
this is authentication only.
"""


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing bearer token.")
    return authorization.split(" ", 1)[1].strip()


@router.get(
    "/security-questions",
    response_model=SecurityQuestionsResponse,
    summary="List the configured security questions",
    description=(
        "A question's position in this list is its `question_index` "
        "everywhere else on this router."
    ),
)
async def security_questions() -> SecurityQuestionsResponse:
    return SecurityQuestionsResponse(questions=settings.auth_security_questions_list)


@router.post(
    "/signup",
    response_model=SignupResponse,
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Invalid input, or an account already exists for this email.",
        }
    },
    summary="Create an account",
    description=_DESCRIPTION,
)
async def signup(payload: SignupRequest) -> SignupResponse:
    result = auth_service.signup(
        email=payload.email,
        password=payload.password,
        security_answers=[a.model_dump() for a in payload.security_answers],
    )
    return SignupResponse(**result)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={401: {"model": ErrorResponse, "description": "Incorrect email or password."}},
    summary="Log in",
    description="Returns a bearer session token -- send it as "
    "`Authorization: Bearer <session_token>` to GET /auth/me.",
)
async def login(payload: LoginRequest) -> LoginResponse:
    result = auth_service.login(email=payload.email, password=payload.password)
    return LoginResponse(**result)


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid session."}},
    summary="Current logged-in user",
)
async def me(authorization: str | None = Header(default=None)) -> MeResponse:
    token = _bearer_token(authorization)
    result = auth_service.get_current_user(token)
    return MeResponse(**result)


@router.post(
    "/forgot-password/verify",
    response_model=ForgotPasswordVerifyResponse,
    responses={
        401: {
            "model": ErrorResponse,
            "description": "Email or security answers did not match.",
        }
    },
    summary="Verify security-question answers to start a password reset",
    description="On success, returns a short-lived `reset_token` for "
    "POST /auth/forgot-password/reset.",
)
async def forgot_password_verify(
    payload: ForgotPasswordVerifyRequest,
) -> ForgotPasswordVerifyResponse:
    result = auth_service.verify_security_answers(
        email=payload.email,
        security_answers=[a.model_dump() for a in payload.security_answers],
    )
    return ForgotPasswordVerifyResponse(**result)


@router.post(
    "/forgot-password/reset",
    response_model=ResetPasswordResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Reset token is invalid or expired."}
    },
    summary="Set a new password using a verified reset token",
    description="Also invalidates every existing session for the account.",
)
async def forgot_password_reset(
    payload: ForgotPasswordResetRequest,
) -> ResetPasswordResponse:
    result = auth_service.reset_password(
        reset_token=payload.reset_token, new_password=payload.new_password
    )
    return ResetPasswordResponse(**result)
