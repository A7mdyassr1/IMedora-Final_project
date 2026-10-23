from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.schemas.user import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, UserResponse


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # The mobile app calls this field "identifier"; the web app may send "email".
    # Users have no username column, so the identifier is the email address.
    identifier: str = Field(validation_alias=AliasChoices("identifier", "email"), min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)  # no min length: don't reveal the policy at login


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
