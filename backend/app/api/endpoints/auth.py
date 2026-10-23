from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, TokenResponse
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
    return TokenResponse(access_token=token, expires_in=expires_in, user=UserResponse.model_validate(user))


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
