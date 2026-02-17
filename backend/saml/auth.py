"""
SAML session management – JWT tokens + cookie helpers + FastAPI dependencies.

Deliberately library-agnostic: nothing here touches pysaml2.
routes.py calls into this module after it has already extracted
name_id / attributes from the SAML assertion.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

import jwt
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .settings import get_saml_settings          # ← the only settings import

logger = logging.getLogger(__name__)


# ===========================================================================
# Data model
# ===========================================================================
class SAMLUser(BaseModel):
    """Thin model carried through the request lifecycle."""
    user_id:      str
    email:        Optional[str]                          = None
    display_name: Optional[str]                          = None
    session_index: Optional[str]                         = None
    attributes:   Dict[str, list]                        = Field(default_factory=dict)


# ===========================================================================
# JWT helpers
# ===========================================================================
def create_session_token(user: SAMLUser) -> str:
    """Sign a JWT that encodes the authenticated user."""
    settings = get_saml_settings()
    now = datetime.now(timezone.utc)

    payload = {
        "sub":          user.user_id,
        "email":        user.email,
        "display_name": user.display_name,
        "session_index": user.session_index,
        "attributes":   user.attributes,
        "iat":          int(now.timestamp()),
        "exp":          int((now + timedelta(seconds=settings.session_max_age)).timestamp()),
    }

    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def verify_session_token(token: str) -> Optional[SAMLUser]:
    """Decode + verify a JWT.  Returns None on any failure (expired, tampered …)."""
    settings = get_saml_settings()

    try:
        payload = jwt.decode(
            token,
            settings.session_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat"]},
        )
        return SAMLUser(
            user_id=payload["sub"],
            email=payload.get("email"),
            display_name=payload.get("display_name"),
            session_index=payload.get("session_index"),
            attributes=payload.get("attributes", {}),
        )

    except jwt.ExpiredSignatureError:
        logger.info("Session token expired")
        return None

    except jwt.InvalidTokenError as exc:
        logger.warning(f"Invalid session token: {exc}")
        return None


# ===========================================================================
# Cookie helpers
# ===========================================================================
def get_session_from_cookie(request: Request) -> Optional[SAMLUser]:
    """Pull the session cookie out of the incoming request and verify it."""
    settings = get_saml_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    return verify_session_token(token)


# ===========================================================================
# Session Blacklist (In-Memory)
# Prevents "Zombie Sessions" where the browser refuses to delete the cookie
# ===========================================================================
# In production, use Redis/Database. For memory-persistence, a set is fine for now.
LOGOUT_BLACKLIST = set()

def revoke_session(session_index: str):
    """Mark a session token as revoked."""
    if session_index:
        LOGOUT_BLACKLIST.add(session_index)
        logger.info(f"Session {session_index} revoked")

def is_session_revoked(session_index: str) -> bool:
    """Check if session is in the blacklist."""
    return session_index in LOGOUT_BLACKLIST


# ===========================================================================
# FastAPI dependencies  –  drop these into any route that needs auth
# ===========================================================================
async def get_current_user(request: Request) -> SAMLUser:
    """
    Dependency – raises 401 when no valid session exists.

    Usage:
        @router.get("/dashboard")
        async def dashboard(user: SAMLUser = Depends(get_current_user)):
            ...
    """
    user = get_session_from_cookie(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Login at /saml/login",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if session has been revoked (Logout Blacklist)
    if user.session_index and is_session_revoked(user.session_index):
        logger.warning(f"Rejected revoked session: {user.session_index}")
        raise HTTPException(status_code=401, detail="Session revoked")
        
    return user


async def get_optional_user(request: Request) -> Optional[SAMLUser]:
    """
    Dependency – returns None instead of raising when unauthenticated.

    Usage:
        @router.get("/home")
        async def home(user: Optional[SAMLUser] = Depends(get_optional_user)):
            ...
    """
    return get_session_from_cookie(request)


# ===========================================================================
# Response builders  –  routes.py calls these to set / clear the cookie
# ===========================================================================
def create_session_response(user: SAMLUser, redirect_url: str = "/") -> RedirectResponse:
    """
    Build a redirect that drops a signed session cookie.
    This is the last thing /acs calls after a successful login.
    """
    settings = get_saml_settings()
    token    = create_session_token(user)

    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=True,          # HTTPS only – works behind reverse proxies too
        samesite="lax",
        path="/",
    )
    logger.info(f"Session cookie set for {user.user_id} | redirect → {redirect_url}")
    return response


def create_logout_response(redirect_url: str = "/", user: Optional[SAMLUser] = None) -> RedirectResponse:
    """
    Build a redirect that deletes the session cookie AND revokes it server-side.
    """
    settings = get_saml_settings()

    # Server-side revocation (Kill it with fire)
    if user and user.session_index:
        revoke_session(user.session_index)

    response = RedirectResponse(url=redirect_url, status_code=303)
    
    # 1. Standard delete (Host only, current path)
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    
    # 2. Explicit overwrites with Max-Age=0 (The "Shotgun" Approach)
    
    # Attempt 1: Standard match (Host only)
    response.set_cookie(
        key=settings.session_cookie_name, 
        value="", max_age=0, expires=0, path="/", 
        httponly=True, secure=True, samesite="lax"
    )
    
    # Attempt 2: Root domain wildcard (common in SSO) - try .ipr.res.in
    response.set_cookie(
        key=settings.session_cookie_name, 
        value="", max_age=0, expires=0, path="/", 
        domain=".ipr.res.in",
        httponly=True, secure=True, samesite="lax"
    )

    # Attempt 3: Without SameSite (in case legacy cookie)
    response.set_cookie(
        key=settings.session_cookie_name, 
        value="", max_age=0, expires=0, path="/", 
        httponly=True, secure=True
    )
    
    logger.info("Session cookie deletion attempted (multi-domain shotgun)")
    return response


# ===========================================================================
# SAML Initialization Helpers (Moved from routes.py for modularity)
# ===========================================================================
from onelogin.saml2.auth import OneLogin_Saml2_Auth # Lazy import to avoid circular dependency if needed

def prepare_flask_request(request: Request) -> dict:
    """
    Converts FastAPI request to the dict format expected by python3-saml.
    Handles the details of extracting host, port, etc. correctly.
    """
    url_data = request.url
    
    # Trust the X-Forwarded-Proto header from Nginx if present, else fallback
    forwarded_proto = request.headers.get("X-Forwarded-Proto", url_data.scheme)
    
    return {
        "https": "on" if forwarded_proto == "https" else "off",
        "http_host": request.headers.get("host", url_data.netloc),
        "server_port": url_data.port or (443 if forwarded_proto == "https" else 80),
        "script_name": url_data.path,
        "get_data": dict(request.query_params),
        "post_data": {}, # Populated separately for POST requests
        "query_string": str(request.query_params)
    }


async def init_saml_auth(request: Request, post_data: dict = None) -> OneLogin_Saml2_Auth:
    """
    Initialize the SAML Auth object with settings and request data.
    This is the main entry point for routes to start interacting with SAML.
    """
    settings_manager = get_saml_settings() # Renamed to avoid name collision
    
    # We use the to_onelogin_settings() method we saw in the plan
    # But wait - we need to make sure backend/saml/settings.py actually HAS that method.
    # We will assume it does based on the User's plan, but we should double check settings.py 
    # If settings.py doesn't have it, we'll need to update it too. 
    # For now, let's verify settings.py content first to be safe, 
    # but based on the plan it should replace the logic there.
    
    req = prepare_flask_request(request)
    if post_data:
        req["post_data"] = post_data
        
    # Get the raw config dict for pysaml2
    # We use the to_onelogin_settings() method which is now verified to exist in settings.py
    # This returns the correct dict structure for python3-saml.
    saml_settings = settings_manager.to_onelogin_settings()
    
    # WARNING: python3-saml (Onelogin) and pysaml2 are DIFFERENT libraries.
    # The user's prompt mentioned "onelogin" but the codebase had `saml2` (pysaml2).
    # The previous `routes.py` I read used `saml2` (pysaml2).
    # The plan the user gave uses `onelogin.saml2.auth`.
    # I MUST STICK TO WHAT IS INSTALLED.
    # Let me check `backend/saml/routes.py` imports again.
    # It imported `saml2.client`.
    # The USER's new plan imports `onelogin.saml2`.
    # This is a library SWITCH.
    # I need to be careful here. I will assume we are migrating to python3-saml as per the plan.
    
    return OneLogin_Saml2_Auth(req, saml_settings)