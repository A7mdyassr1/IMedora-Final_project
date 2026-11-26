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
    token: str = Field(description="The same value as `access_token`. The mobile contract reads `{token, user}` "
                                   "(Master Instructions section 5); `access_token` stays for existing clients.")
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserResponse


FORGOT_PASSWORD_MESSAGE = ("If an account exists for this email, your administrator has been asked to reset its "
                           "password. Please contact your administrator to receive the new password.")


class ForgotPasswordRequest(BaseModel):
    """The mobile app's "Reset password" screen sends the email; `identifier` is accepted as at login."""
    model_config = ConfigDict(populate_by_name=True)

    identifier: str = Field(validation_alias=AliasChoices("identifier", "email"), min_length=1, max_length=255)


class ForgotPasswordResponse(BaseModel):
    message: str = Field(default=FORGOT_PASSWORD_MESSAGE, description="Always the same text: the answer does not "
                                                                      "reveal whether an account exists.")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
