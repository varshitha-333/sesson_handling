"""Authentication routes — Email/Password + Google OAuth2."""

from __future__ import annotations

import uuid
import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Cookie
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import settings
from app.database import get_db
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    get_current_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ─── Google OAuth2 Constants ─────────────────────────────────────────────────
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# ─── Email / Password Registration ──────────────────────────────────────────

@router.post("/register", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserRegister, response: Response, db: Session = Depends(get_db)):
    """Create a new user with email + password."""
    # Check for duplicate email
    existing = crud.get_user_by_email(db, payload.email.lower().strip())
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    user = models.User(
        id=str(uuid.uuid4()),
        name=payload.name.strip(),
        email=payload.email.lower().strip(),
        password_hash=hash_password(payload.password),
        auth_provider="local",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token({"sub": user.id})
    refresh_token = create_refresh_token({"sub": user.id})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production with HTTPS
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )

    return schemas.TokenResponse(
        access_token=access_token,
        user=schemas.AuthUserResponse.model_validate(user),
    )


# ─── Email / Password Login ─────────────────────────────────────────────────

@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.UserLogin, response: Response, db: Session = Depends(get_db)):
    """Authenticate with email + password and return a JWT."""
    user = crud.get_user_by_email(db, payload.email.lower().strip())

    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    access_token = create_access_token({"sub": user.id})
    refresh_token = create_refresh_token({"sub": user.id})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production with HTTPS
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )

    return schemas.TokenResponse(
        access_token=access_token,
        user=schemas.AuthUserResponse.model_validate(user),
    )


# ─── Google OAuth2 ──────────────────────────────────────────────────────────

@router.get("/google/login")
def google_login(request: Request):
    """Redirect the browser to Google's OAuth consent screen."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured (GOOGLE_CLIENT_ID is empty).",
        )

    # Build the redirect URI from the incoming request
    redirect_uri = str(request.base_url) + "api/auth/google/callback"

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/google/callback")
async def google_callback(code: str, request: Request, db: Session = Depends(get_db)):
    """
    Handle the Google OAuth callback.
    Exchanges the auth code for tokens, fetches user info,
    creates or links a user, and redirects to the frontend with a JWT.
    """
    redirect_uri = str(request.base_url) + "api/auth/google/callback"

    # Exchange auth code for tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        logger.error("Google token exchange failed: %s", token_resp.text)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange Google auth code.",
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    # Fetch user info from Google
    async with httpx.AsyncClient() as client:
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if userinfo_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to fetch Google user info.",
        )

    google_user = userinfo_resp.json()
    google_id = google_user.get("id")
    email = google_user.get("email", "").lower().strip()
    name = google_user.get("name", "")

    # Find or create user
    user = crud.get_user_by_google_id(db, google_id)

    if not user and email:
        # Check if a local user with this email already exists — link it
        user = crud.get_user_by_email(db, email)
        if user:
            user.google_id = google_id
            if user.auth_provider == "local":
                user.auth_provider = "local+google"
            db.commit()
            db.refresh(user)

    if not user:
        # Brand new Google user
        user = models.User(
            id=str(uuid.uuid4()),
            name=name,
            email=email or None,
            auth_provider="google",
            google_id=google_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Create JWT access and refresh tokens
    access_token = create_access_token({"sub": user.id})
    refresh_token = create_refresh_token({"sub": user.id})

    # Redirect to frontend with token as query param
    # The frontend will read this and store it
    frontend_url = "http://localhost:5173"
    redirect_response = RedirectResponse(
        f"{frontend_url}/auth/callback?token={access_token}"
    )
    
    redirect_response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    
    return redirect_response


# ─── Current User ───────────────────────────────────────────────────────────

@router.get("/me", response_model=schemas.AuthUserResponse)
def get_me(current_user: models.User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return current_user


# ─── Refresh Token & Logout ──────────────────────────────────────────────────

@router.post("/refresh")
def refresh_token(response: Response, refresh_token: str = Cookie(None)):
    """Generate a new access token using a valid refresh token cookie."""
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )
        
    user_id = verify_refresh_token(refresh_token)
    access_token = create_access_token({"sub": user_id})
    
    return {"access_token": access_token}


@router.post("/logout")
def logout(response: Response):
    """Clear the refresh token cookie."""
    response.delete_cookie(key="refresh_token", samesite="lax", httponly=True)
    return {"status": "success", "message": "Logged out successfully"}
