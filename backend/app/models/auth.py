"""Signup / login / forgot-password schemas (Phase 16).

Authentication only -- no health, demographic, or heat-risk data lives on
these models. Personalized risk factors (age, acclimatization history,
health flags) are a separate, future concern.
"""

from pydantic import BaseModel, Field


class SecurityAnswerInput(BaseModel):
    """One answer to a question from GET /auth/security-questions."""

    question_index: int = Field(
        ..., ge=0, description="Index into GET /auth/security-questions."
    )
    answer: str = Field(..., min_length=1, max_length=200)


class SignupRequest(BaseModel):
    """Input for POST /auth/signup."""

    email: str = Field(..., min_length=3, max_length=254, examples=["priya@example.com"])
    password: str = Field(..., min_length=1, max_length=200, examples=["a-strong-passphrase"])
    security_answers: list[SecurityAnswerInput] = Field(
        ...,
        min_length=1,
        description=(
            "Answers to 2+ of GET /auth/security-questions, used only to "
            "recover a forgotten password -- never for anything else."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "priya@example.com",
                "password": "a-strong-passphrase",
                "security_answers": [
                    {"question_index": 0, "answer": "Simba"},
                    {"question_index": 2, "answer": "Jaipur"},
                ],
            }
        }
    }


class SignupResponse(BaseModel):
    email: str
    created_at: float = Field(..., description="Unix timestamp.")


class LoginRequest(BaseModel):
    """Input for POST /auth/login."""

    email: str = Field(..., examples=["priya@example.com"])
    password: str = Field(..., examples=["a-strong-passphrase"])


class LoginResponse(BaseModel):
    session_token: str = Field(..., description="Send as 'Authorization: Bearer <token>'.")
    expires_at: float = Field(..., description="Unix timestamp.")
    email: str


class MeResponse(BaseModel):
    """GET /auth/me -- the account behind the current session token."""

    email: str
    created_at: float


class SecurityQuestionsResponse(BaseModel):
    """GET /auth/security-questions -- the configured question bank.

    A question's position in this list IS its `question_index` everywhere
    else in this API.
    """

    questions: list[str]


class ForgotPasswordVerifyRequest(BaseModel):
    """Input for POST /auth/forgot-password/verify."""

    email: str
    security_answers: list[SecurityAnswerInput] = Field(..., min_length=1)


class ForgotPasswordVerifyResponse(BaseModel):
    reset_token: str = Field(
        ..., description="Short-lived. Send to POST /auth/forgot-password/reset."
    )
    expires_at: float = Field(..., description="Unix timestamp.")


class ForgotPasswordResetRequest(BaseModel):
    """Input for POST /auth/forgot-password/reset."""

    reset_token: str
    new_password: str = Field(..., min_length=1, max_length=200, examples=["a-new-strong-passphrase"])


class ResetPasswordResponse(BaseModel):
    status: str = Field(..., examples=["password_reset"])
