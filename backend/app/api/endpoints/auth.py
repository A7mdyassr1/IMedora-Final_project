from fastapi import APIRouter, BackgroundTasks, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest, ForgotPasswordRequest, ForgotPasswordResponse, LoginRequest, TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService, process_password_reset_request

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"description": "Invalid email or password (also returned for inactive accounts)"}},
    summary="Log in with email + password",
)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user, token, expires_in = AuthService(db).login(body.identifier, body.password)
    return TokenResponse(access_token=token, token=token, expires_in=expires_in, user=UserResponse.model_validate(user))


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=202,
    summary="Ask an administrator to reset a forgotten password",
    description=(
        "No sign-in needed. IMedora has no e-mail service: when the email belongs to an account that can sign in, "
        "the organization's administrators receive an in-app notification (`password_reset_requested`) and set a "
        "new password with `POST /users/{id}/reset-password`. An administrator who still has an unread request "
        "for the same account is not notified again.\n\n"
        "Every well-formed request gets `202` with the same message, whether or not the account exists. The "
        "request is processed after the answer is sent, so the answer's timing does not depend on it either. "
        "A request for the organization's only administrator notifies nobody (the account itself is never "
        "notified). Not rate limited: limit it at the reverse proxy."
    ),
)
def forgot_password(body: ForgotPasswordRequest, background: BackgroundTasks):
    background.add_task(process_password_reset_request, body.identifier)
    return ForgotPasswordResponse()


@router.get("/me", response_model=UserResponse, summary="Current user")
def me(user: User = Depends(get_current_user)):
    return UserResponse.model_validate(user)


@router.post("/change-password", status_code=204, summary="Change your own password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    AuthService(db).change_password(user, body.current_password, body.new_password)
    return Response(status_code=204)
