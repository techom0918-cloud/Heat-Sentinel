"""Phase 16 tests: signup, login, and forgot-password.

Every test gets its own throwaway SQLite file (see `isolated_auth_db`
below) so tests never share or leak account state.
"""

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ValidationError
from app.main import app
from app.services import auth_service

URL = f"{settings.API_V1_PREFIX}/auth"


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_auth_db(tmp_path, monkeypatch):
    """Every test runs against its own empty account store."""
    monkeypatch.setattr(
        settings, "AUTH_DB_PATH", str(tmp_path / "test_users.db"), raising=False
    )
    yield


def _answers(pet="Simba", city="Jaipur"):
    return [
        {"question_index": 0, "answer": pet},
        {"question_index": 2, "answer": city},
    ]


def _signup(email="priya@example.com", password="a-strong-passphrase", answers=None):
    return auth_service.signup(
        email=email, password=password, security_answers=answers or _answers()
    )


# --- security questions --------------------------------------------------


def test_security_questions_endpoint_lists_configured_questions(client: TestClient) -> None:
    response = client.get(f"{URL}/security-questions")
    assert response.status_code == 200
    assert response.json()["questions"] == settings.auth_security_questions_list


# --- signup ----------------------------------------------------------------


def test_signup_creates_account() -> None:
    result = _signup()
    assert result["email"] == "priya@example.com"
    assert isinstance(result["created_at"], float)


def test_signup_lowercases_and_trims_email() -> None:
    result = _signup(email="  Priya@Example.com  ")
    assert result["email"] == "priya@example.com"


def test_signup_rejects_duplicate_email() -> None:
    _signup()
    with pytest.raises(ValidationError):
        _signup()


def test_signup_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        _signup(password="short")


def test_signup_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        _signup(email="not-an-email")


def test_signup_rejects_too_few_security_answers() -> None:
    with pytest.raises(ValidationError):
        _signup(answers=[{"question_index": 0, "answer": "Simba"}])


def test_signup_rejects_duplicate_question_index() -> None:
    with pytest.raises(ValidationError):
        _signup(
            answers=[
                {"question_index": 0, "answer": "Simba"},
                {"question_index": 0, "answer": "Again"},
            ]
        )


def test_signup_rejects_unknown_question_index() -> None:
    with pytest.raises(ValidationError):
        _signup(answers=[{"question_index": 0, "answer": "Simba"}, {"question_index": 999, "answer": "x"}])


def test_signup_rejects_empty_answer() -> None:
    with pytest.raises(ValidationError):
        _signup(answers=[{"question_index": 0, "answer": "   "}, {"question_index": 2, "answer": "Jaipur"}])


def test_signup_required_answer_count_is_configurable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_SECURITY_QUESTIONS_REQUIRED", 1, raising=False)
    result = _signup(answers=[{"question_index": 0, "answer": "Simba"}])
    assert result["email"] == "priya@example.com"


# --- login -----------------------------------------------------------------


def test_login_succeeds_with_correct_credentials() -> None:
    _signup()
    result = auth_service.login(email="priya@example.com", password="a-strong-passphrase")
    assert result["email"] == "priya@example.com"
    assert isinstance(result["session_token"], str) and len(result["session_token"]) > 20


def test_login_rejects_wrong_password() -> None:
    _signup()
    with pytest.raises(AuthenticationError):
        auth_service.login(email="priya@example.com", password="wrong-password")


def test_login_rejects_unknown_email() -> None:
    with pytest.raises(AuthenticationError):
        auth_service.login(email="nobody@example.com", password="anything123")


def test_login_error_message_does_not_reveal_which_field_was_wrong() -> None:
    _signup()
    try:
        auth_service.login(email="priya@example.com", password="wrong-password")
        wrong_password_message = None
    except AuthenticationError as exc:
        wrong_password_message = exc.message
    try:
        auth_service.login(email="nobody@example.com", password="wrong-password")
        unknown_email_message = None
    except AuthenticationError as exc:
        unknown_email_message = exc.message
    assert wrong_password_message == unknown_email_message


def test_login_is_case_insensitive_on_email() -> None:
    _signup(email="priya@example.com")
    result = auth_service.login(email="Priya@Example.com", password="a-strong-passphrase")
    assert result["email"] == "priya@example.com"


# --- current session (/auth/me) ---------------------------------------------


def test_me_returns_current_user_with_valid_token() -> None:
    _signup()
    login_result = auth_service.login(email="priya@example.com", password="a-strong-passphrase")
    me = auth_service.get_current_user(login_result["session_token"])
    assert me["email"] == "priya@example.com"


def test_me_rejects_missing_token() -> None:
    with pytest.raises(AuthenticationError):
        auth_service.get_current_user("")


def test_me_rejects_unknown_token() -> None:
    with pytest.raises(AuthenticationError):
        auth_service.get_current_user("not-a-real-token")


def test_me_rejects_expired_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_SESSION_EXPIRY_SECONDS", -1, raising=False)
    _signup()
    login_result = auth_service.login(email="priya@example.com", password="a-strong-passphrase")
    with pytest.raises(AuthenticationError):
        auth_service.get_current_user(login_result["session_token"])


def test_me_endpoint_requires_bearer_header(client: TestClient) -> None:
    response = client.get(f"{URL}/me")
    assert response.status_code == 401


# --- passwords and answers are never stored in plain text -------------------


def test_passwords_are_not_stored_in_plain_text() -> None:
    _signup(password="a-strong-passphrase")
    db_path = auth_service._db_path()
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT password_hash FROM users").fetchone()
    conn.close()
    assert "a-strong-passphrase" not in row[0]


def test_security_answers_are_not_stored_in_plain_text() -> None:
    _signup(answers=_answers(pet="Simba"))
    db_path = auth_service._db_path()
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT answer_hash FROM security_answers").fetchall()
    conn.close()
    assert all("simba" not in r[0].lower() for r in rows)


# --- forgot password ---------------------------------------------------


def test_forgot_password_verify_succeeds_with_correct_answers() -> None:
    _signup()
    result = auth_service.verify_security_answers(
        email="priya@example.com", security_answers=_answers()
    )
    assert isinstance(result["reset_token"], str) and len(result["reset_token"]) > 20


def test_forgot_password_verify_is_case_and_whitespace_insensitive() -> None:
    _signup(answers=_answers(pet="Simba", city="Jaipur"))
    result = auth_service.verify_security_answers(
        email="priya@example.com",
        security_answers=[
            {"question_index": 0, "answer": "  SIMBA  "},
            {"question_index": 2, "answer": "jaipur"},
        ],
    )
    assert isinstance(result["reset_token"], str)


def test_forgot_password_verify_rejects_wrong_answer() -> None:
    _signup()
    with pytest.raises(AuthenticationError):
        auth_service.verify_security_answers(
            email="priya@example.com",
            security_answers=[
                {"question_index": 0, "answer": "wrong-pet"},
                {"question_index": 2, "answer": "Jaipur"},
            ],
        )


def test_forgot_password_verify_rejects_unknown_email() -> None:
    with pytest.raises(AuthenticationError):
        auth_service.verify_security_answers(
            email="nobody@example.com", security_answers=_answers()
        )


def test_forgot_password_verify_rejects_too_few_answers() -> None:
    _signup()
    with pytest.raises(ValidationError):
        auth_service.verify_security_answers(
            email="priya@example.com",
            security_answers=[{"question_index": 0, "answer": "Simba"}],
        )


def test_forgot_password_reset_changes_password() -> None:
    _signup()
    verify = auth_service.verify_security_answers(
        email="priya@example.com", security_answers=_answers()
    )
    auth_service.reset_password(
        reset_token=verify["reset_token"], new_password="a-new-strong-passphrase"
    )
    # Old password no longer works, new one does.
    with pytest.raises(AuthenticationError):
        auth_service.login(email="priya@example.com", password="a-strong-passphrase")
    result = auth_service.login(email="priya@example.com", password="a-new-strong-passphrase")
    assert result["email"] == "priya@example.com"


def test_forgot_password_reset_rejects_invalid_token() -> None:
    with pytest.raises(AuthenticationError):
        auth_service.reset_password(reset_token="not-a-real-token", new_password="a-new-strong-passphrase")


def test_forgot_password_reset_rejects_short_new_password() -> None:
    _signup()
    verify = auth_service.verify_security_answers(
        email="priya@example.com", security_answers=_answers()
    )
    with pytest.raises(ValidationError):
        auth_service.reset_password(reset_token=verify["reset_token"], new_password="short")


def test_forgot_password_reset_invalidates_existing_sessions() -> None:
    _signup()
    login_result = auth_service.login(email="priya@example.com", password="a-strong-passphrase")
    verify = auth_service.verify_security_answers(
        email="priya@example.com", security_answers=_answers()
    )
    auth_service.reset_password(
        reset_token=verify["reset_token"], new_password="a-new-strong-passphrase"
    )
    with pytest.raises(AuthenticationError):
        auth_service.get_current_user(login_result["session_token"])


def test_reset_token_expires(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_RESET_TOKEN_EXPIRY_SECONDS", -1, raising=False)
    _signup()
    verify = auth_service.verify_security_answers(
        email="priya@example.com", security_answers=_answers()
    )
    with pytest.raises(AuthenticationError):
        auth_service.reset_password(
            reset_token=verify["reset_token"], new_password="a-new-strong-passphrase"
        )


# --- API-level smoke tests ------------------------------------------------


def test_signup_endpoint_in_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert f"{settings.API_V1_PREFIX}/auth/signup" in paths
    assert f"{settings.API_V1_PREFIX}/auth/login" in paths
    assert f"{settings.API_V1_PREFIX}/auth/forgot-password/verify" in paths
    assert f"{settings.API_V1_PREFIX}/auth/forgot-password/reset" in paths


def test_signup_via_api(client: TestClient) -> None:
    response = client.post(
        f"{URL}/signup",
        json={
            "email": "api-user@example.com",
            "password": "a-strong-passphrase",
            "security_answers": [
                {"question_index": 0, "answer": "Simba"},
                {"question_index": 2, "answer": "Jaipur"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["email"] == "api-user@example.com"


def test_duplicate_signup_via_api_returns_422(client: TestClient) -> None:
    payload = {
        "email": "dup@example.com",
        "password": "a-strong-passphrase",
        "security_answers": [
            {"question_index": 0, "answer": "Simba"},
            {"question_index": 2, "answer": "Jaipur"},
        ],
    }
    client.post(f"{URL}/signup", json=payload)
    response = client.post(f"{URL}/signup", json=payload)
    assert response.status_code == 422


def test_login_via_api_returns_401_for_wrong_password(client: TestClient) -> None:
    client.post(
        f"{URL}/signup",
        json={
            "email": "login-user@example.com",
            "password": "a-strong-passphrase",
            "security_answers": [
                {"question_index": 0, "answer": "Simba"},
                {"question_index": 2, "answer": "Jaipur"},
            ],
        },
    )
    response = client.post(
        f"{URL}/login",
        json={"email": "login-user@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "no-password@example.com"},
        {"password": "a-strong-passphrase"},
        {},
    ],
)
def test_malformed_signup_requests_rejected(client: TestClient, payload) -> None:
    assert client.post(f"{URL}/signup", json=payload).status_code == 422
