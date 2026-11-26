from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest, ForgotPasswordRequest, ForgotPasswordResponse, LoginRequest, TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService

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
        "The answer is always `202` with the same message, whether or not the account exists, so it cannot be "
        "used to find out which emails are registered."
    ),
)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    AuthService(db).request_password_reset(body.identifier)
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
