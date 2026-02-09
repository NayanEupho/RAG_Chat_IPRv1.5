# SAML SSO Implementation Guide for RAG Chat IPR

## Quick Reference

| File | Action | Description |
|------|--------|-------------|
| `backend/saml/__init__.py` | CREATE | Package init |
| `backend/saml/settings.py` | CREATE | SAML configuration |
| `backend/saml/auth.py` | CREATE | JWT session management |
| `backend/saml/routes.py` | CREATE | SAML endpoints |
| `backend/state/history.py` | REPLACE functions | Add user_id support |
| `backend/api/routes.py` | REPLACE functions | Add auth protection |
| `backend/app.py` | REPLACE section | Add SAML router + CORS fix |
| `frontend/src/hooks/useAuth.ts` | CREATE | Auth hook |
| `frontend/src/components/AuthProvider.tsx` | CREATE | Auth context |
| `frontend/src/hooks/useChat.ts` | REPLACE functions | Fix URLs + credentials |
| `frontend/src/components/Sidebar.tsx` | REPLACE functions | Fix URLs + add logout |
| `.env` | APPEND | SAML config variables |

---

## Understanding the Changes: Before vs After

### Why Functions Need to Change

The current system has **no user identity** - anyone can see all sessions. After SAML:
- Every session is tied to a specific user via `user_id`
- Every API request identifies who is making it via JWT cookie
- Users can only see/modify their own sessions

### Where Does `user_id` Come From?

**Users don't register or create accounts manually.** The `user_id` comes automatically from your SAML Identity Provider:

```
User clicks "Login with SSO"
        ↓
Redirected to your internal SAML IdP
        ↓
User enters their existing corporate credentials
        ↓
IdP sends SAML assertion with NameID (e.g., "john.doe@ipr.res.in")
        ↓
Backend extracts NameID as user_id, creates JWT cookie
        ↓
All sessions are automatically tied to that user_id
```

The **NameID** from your IdP becomes the `user_id`. This is typically:
- Email address (`john.doe@ipr.res.in`)
- Employee ID (`EMP12345`)
- Username (`jdoe`)

Whatever your IdP sends as NameID is used. **No manual user management needed!**

---

### File: `backend/state/history.py`

| Function | Before | After | Why |
|----------|--------|-------|-----|
| `init_history_db` | Creates `sessions` table with `session_id`, `title` | Adds `user_id` column to table | Sessions need an owner |
| `create_session` | Takes `session_id`, `title` only | Adds `user_id` parameter | New sessions must record who created them |
| `create_new_session` | Generates session without user | Adds `user_id` parameter | Same as above |
| `get_all_sessions` | Returns ALL sessions | Filters by `user_id` | User A shouldn't see User B's sessions |
| `delete_session` | Deletes any session by ID | Checks ownership first, raises `PermissionError` if not owner | User A can't delete User B's session |
| `get_session_owner` | ❌ Doesn't exist | ✅ NEW: Returns `user_id` for a session | Needed to verify ownership |
| `delete_all_sessions` | ❌ Doesn't exist | ✅ NEW: Wipes all data for clean start | One-time migration helper |

---

### File: `backend/api/routes.py`

| Function | Before | After | Why |
|----------|--------|-------|-----|
| `create_session_endpoint` | Creates session for anyone | Adds `Depends(get_current_user)`, passes `user.user_id` | Session belongs to logged-in user |
| `get_sessions` | Returns all sessions | Adds `Depends(get_current_user)`, filters by `user.user_id` | Only show your sessions |
| `delete_session_endpoint` | Deletes any session | Adds `Depends(get_current_user)`, passes `user.user_id` for ownership check | Can't delete others' sessions |
| `get_history` | Shows any session's history | Adds `Depends(get_current_user)`, checks `get_session_owner()` | Can't view others' history |
| `chat_stream_endpoint` | Accepts any session_id | Adds `Depends(get_current_user)`, verifies ownership | Can't chat in others' sessions |

**What is `Depends(get_current_user)`?**
This is FastAPI's dependency injection. It:
1. Reads the `saml_session` cookie from the request
2. Decodes the JWT token
3. Returns a `SAMLUser` object with `user_id`, `email`, `display_name`
4. If no valid cookie → returns 401 Unauthorized

---

### File: `backend/app.py`

| Section | Before | After | Why |
|---------|--------|-------|-----|
| CORS `allow_origins` | `["*"]` (any origin) | `["https://askme.ipr.res.in", "http://localhost:3000"]` | Cookies require specific origins with `allow_credentials=True` |
| Router includes | Only API router | Add SAML router | Enable `/saml/*` endpoints |

---

### File: `frontend/src/hooks/useChat.ts`

| Function | Before | After | Why |
|----------|--------|-------|-----|
| `getApiBase` | Returns `http://${hostname}:8000/api` | Returns `/api` (relative) | HTTPS breaks with hardcoded HTTP; nginx proxies correctly |
| `fetchDocuments` | No credentials | Adds `{ credentials: 'include' }` | Cookies need this to be sent |
| `loadHistory` | No credentials | Adds `{ credentials: 'include' }` | Same |
| `sendMessage` (fetch) | No credentials | Adds `{ credentials: 'include' }` | Same |

---

### File: `frontend/src/components/Sidebar.tsx`

| Function | Before | After | Why |
|----------|--------|-------|-----|
| `getApiBase` | Returns `http://${hostname}:8000/api` | Returns `/api` (relative) | Same as useChat.ts |
| `fetchSessions` | No credentials | Adds `{ credentials: 'include' }` | Cookies need this |
| `handleDelete` | No credentials | Adds `{ credentials: 'include' }` | Same |

---

### File: `frontend/src/app/layout.tsx`

| Section | Before | After | Why |
|---------|--------|-------|-----|
| Body content | `{children}` directly | `<AuthProvider>{children}</AuthProvider>` | Wraps app to check auth before rendering |

---

### Data Flow Comparison

**BEFORE (No Authentication):**
```
Browser → fetch('/api/sessions') → Backend returns ALL sessions → Anyone sees everything
```

**AFTER (SAML Authentication):**
```
Browser → fetch('/api/sessions', {credentials: 'include'})
        → Cookie: saml_session=<JWT>
        → Backend: get_current_user() extracts user_id from JWT
        → get_all_sessions(user_id) → Only YOUR sessions returned
```

---



## Step 0: Install System Dependencies

```bash
# On your Ubuntu/Debian server:
sudo apt-get update
sudo apt-get install -y xmlsec1 libxmlsec1-dev pkg-config

# Install Python packages:
cd /path/to/RAG_Chat_IPRv1.5
pip install python3-saml PyJWT
```

---

## Step 1: Create `backend/saml/__init__.py`

**Action:** Create new file

```python
# SAML Authentication Module for RAG Chat IPR
```

---

## Step 2: Create `backend/saml/settings.py`

**Action:** Create new file

```python
"""
SAML Configuration Settings

Environment Variables Required:
- SAML_IDP_ENTITY_ID: Your IdP's entity ID
- SAML_IDP_SSO_URL: IdP's Single Sign-On URL
- SAML_IDP_CERT_FILE: Path to IdP's X.509 certificate file
- SAML_SESSION_SECRET: Secret key for JWT signing
"""
import os
from functools import lru_cache
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class SAMLSettings:
    def __init__(self):
        # Service Provider (Your App) Settings
        self.sp_entity_id = os.getenv("SAML_SP_ENTITY_ID", "https://askme.ipr.res.in")
        self.sp_acs_url = os.getenv("SAML_SP_ACS_URL", "https://askme.ipr.res.in/saml/acs")
        self.sp_slo_url = os.getenv("SAML_SP_SLO_URL", "https://askme.ipr.res.in/saml/slo")

        # Identity Provider Settings (REQUIRED)
        self.idp_entity_id = os.getenv("SAML_IDP_ENTITY_ID")
        self.idp_sso_url = os.getenv("SAML_IDP_SSO_URL")
        self.idp_slo_url = os.getenv("SAML_IDP_SLO_URL")
        self.idp_cert_file = os.getenv("SAML_IDP_CERT_FILE")

        # Session Settings
        self.session_cookie_name = "saml_session"
        self.session_secret = os.getenv("SAML_SESSION_SECRET", "CHANGE-THIS-IN-PRODUCTION-minimum-32-chars")
        self.session_max_age = int(os.getenv("SAML_SESSION_MAX_AGE", "28800"))  # 8 hours

    @property
    def is_configured(self) -> bool:
        return all([self.idp_entity_id, self.idp_sso_url, self.idp_cert_file])

    def get_idp_cert(self) -> Optional[str]:
        if not self.idp_cert_file or not os.path.exists(self.idp_cert_file):
            logger.warning(f"IdP certificate file not found: {self.idp_cert_file}")
            return None
        with open(self.idp_cert_file, 'r') as f:
            return f.read()

    def to_onelogin_settings(self) -> dict:
        return {
            "strict": True,
            "debug": False,
            "sp": {
                "entityId": self.sp_entity_id,
                "assertionConsumerService": {
                    "url": self.sp_acs_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                },
                "singleLogoutService": {
                    "url": self.sp_slo_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                },
                "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            },
            "idp": {
                "entityId": self.idp_entity_id,
                "singleSignOnService": {
                    "url": self.idp_sso_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                },
                "x509cert": self.get_idp_cert() or ""
            },
            "security": {
                "authnRequestsSigned": False,
                "wantAssertionsSigned": True,
            }
        }


@lru_cache()
def get_saml_settings() -> SAMLSettings:
    return SAMLSettings()
```

---

## Step 3: Create `backend/saml/auth.py`

**Action:** Create new file

```python
"""
SAML Authentication and Session Management

Provides JWT token creation/verification and FastAPI dependencies.
"""
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from pydantic import BaseModel
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
import logging

from .settings import get_saml_settings

logger = logging.getLogger(__name__)


class SAMLUser(BaseModel):
    user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    attributes: dict = {}


def create_session_token(user: SAMLUser) -> str:
    settings = get_saml_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user.user_id,
        "email": user.email,
        "display_name": user.display_name,
        "exp": now + timedelta(seconds=settings.session_max_age),
        "iat": now
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def verify_session_token(token: str) -> Optional[SAMLUser]:
    settings = get_saml_settings()
    try:
        payload = jwt.decode(token, settings.session_secret, algorithms=["HS256"])
        return SAMLUser(
            user_id=payload["user_id"],
            email=payload.get("email"),
            display_name=payload.get("display_name")
        )
    except jwt.ExpiredSignatureError:
        logger.info("Session token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid session token: {e}")
        return None


def get_session_from_cookie(request: Request) -> Optional[SAMLUser]:
    settings = get_saml_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    return verify_session_token(token)


async def get_current_user(request: Request) -> SAMLUser:
    """FastAPI dependency - raises 401 if not authenticated."""
    user = get_session_from_cookie(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please login via SAML.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user


async def get_optional_user(request: Request) -> Optional[SAMLUser]:
    """FastAPI dependency - returns None if not authenticated."""
    return get_session_from_cookie(request)


def create_session_response(user: SAMLUser, redirect_url: str = "/") -> RedirectResponse:
    settings = get_saml_settings()
    token = create_session_token(user)
    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=True,
        samesite="lax"
    )
    return response


def create_logout_response(redirect_url: str = "/") -> RedirectResponse:
    settings = get_saml_settings()
    response = RedirectResponse(url=redirect_url, status_code=303)
    response.delete_cookie(key=settings.session_cookie_name)
    return response
```

---

## Step 4: Create `backend/saml/routes.py`

**Action:** Create new file

```python
"""
SAML Authentication Routes

Endpoints:
- GET  /saml/login    - Redirect to IdP
- POST /saml/acs      - Receive SAML response
- GET  /saml/logout   - Clear session
- GET  /saml/metadata - SP metadata XML
- GET  /saml/me       - Current user info
- GET  /saml/check    - Auth status check
"""
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import Response, RedirectResponse
from onelogin.saml2.auth import OneLogin_Saml2_Auth
import logging

from .settings import get_saml_settings
from .auth import SAMLUser, get_current_user, get_optional_user, create_session_response, create_logout_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/saml", tags=["SAML Authentication"])


def prepare_flask_request(request: Request) -> dict:
    url_data = request.url
    return {
        "https": "on" if url_data.scheme == "https" else "off",
        "http_host": request.headers.get("host", url_data.netloc),
        "server_port": url_data.port or (443 if url_data.scheme == "https" else 80),
        "script_name": url_data.path,
        "get_data": dict(request.query_params),
        "post_data": {},
        "query_string": str(request.query_params)
    }


async def init_saml_auth(request: Request, post_data: dict = None) -> OneLogin_Saml2_Auth:
    settings = get_saml_settings()
    if not settings.is_configured:
        raise HTTPException(status_code=500, detail="SAML not configured")
    req = prepare_flask_request(request)
    if post_data:
        req["post_data"] = post_data
    return OneLogin_Saml2_Auth(req, settings.to_onelogin_settings())


@router.get("/login")
async def saml_login(request: Request, next: str = "/"):
    auth = await init_saml_auth(request)
    redirect_url = auth.login(return_to=next)
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/acs")
async def saml_acs(request: Request):
    form_data = await request.form()
    post_data = {key: value for key, value in form_data.items()}
    auth = await init_saml_auth(request, post_data)
    auth.process_response()
    errors = auth.get_errors()

    if errors:
        logger.error(f"SAML ACS Error: {errors}")
        raise HTTPException(status_code=400, detail=f"SAML failed: {auth.get_last_error_reason()}")

    if not auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Authentication failed")

    name_id = auth.get_nameid()
    attributes = auth.get_attributes()

    # Validate user_id is not empty
    if not name_id or not name_id.strip():
        raise HTTPException(status_code=400, detail="IdP returned empty user ID")

    email = (
        attributes.get("email", [None])[0] or
        attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress", [None])[0] or
        (name_id if "@" in str(name_id) else None)
    )
    display_name = (
        attributes.get("displayName", [None])[0] or
        attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name", [None])[0] or
        email
    )

    user = SAMLUser(user_id=name_id, email=email, display_name=display_name, attributes=attributes)
    logger.info(f"SAML login successful: {user.user_id}")

    relay_state = post_data.get("RelayState", "/")
    redirect_url = relay_state if relay_state and not relay_state.startswith("http") else "/"
    return create_session_response(user, redirect_url)


@router.get("/logout")
async def saml_logout():
    logger.info("User logged out")
    return create_logout_response("/")


@router.get("/metadata")
async def saml_metadata(request: Request):
    auth = await init_saml_auth(request)
    settings = auth.get_settings()
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        raise HTTPException(status_code=500, detail=f"Invalid metadata: {errors}")
    return Response(content=metadata, media_type="application/xml")


@router.get("/me")
async def get_current_user_info(user: SAMLUser = Depends(get_current_user)):
    return {"user_id": user.user_id, "email": user.email, "display_name": user.display_name, "authenticated": True}


@router.get("/check")
async def check_auth_status(user: SAMLUser = Depends(get_optional_user)):
    if user:
        return {"authenticated": True, "user_id": user.user_id, "email": user.email, "display_name": user.display_name}
    return {"authenticated": False}
```

---

## Step 5: Modify `backend/state/history.py`

**Action:** Find and REPLACE these functions with the versions below.

### Replace `init_history_db`:
```python
def init_history_db():
    global _db_initialized
    if _db_initialized:
        return
    try:
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                user_id TEXT DEFAULT 'anonymous',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                intent TEXT,
                sources TEXT,
                thoughts TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")

        # Migration for existing tables
        cursor = conn.execute("PRAGMA table_info(messages)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'metadata' not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        if 'thoughts' not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN thoughts TEXT")

        cursor = conn.execute("PRAGMA table_info(sessions)")
        session_columns = [row['name'] for row in cursor.fetchall()]
        if 'user_id' not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT 'legacy_user'")
            logger.info("Migrated sessions table: added user_id column")

        conn.commit()
        _db_initialized = True
    except Exception as e:
        logger.error(f"Failed to init history DB: {e}")
```

### Replace `create_session`:
```python
def create_session(session_id: str, title: str = None, user_id: str = "anonymous"):
    init_history_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
    if not cursor.fetchone():
        final_title = title or f"Session {session_id[:8]}"
        conn.execute(
            "INSERT INTO sessions (session_id, title, user_id) VALUES (?, ?, ?)",
            (session_id, final_title, user_id)
        )
        conn.commit()
        return True
    return False
```

### Replace `create_new_session`:
```python
def create_new_session(title: str = None, user_id: str = "anonymous"):
    import uuid
    session_id = f"web_{uuid.uuid4().hex[:8]}"
    create_session(session_id, title, user_id)
    return {"session_id": session_id, "title": title or f"Session {session_id[:8]}", "user_id": user_id}
```

### Replace `get_all_sessions`:
```python
def get_all_sessions(user_id: str = None):
    init_history_db()
    conn = get_connection()
    if user_id:
        cursor = conn.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    else:
        cursor = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
    return [dict(row) for row in cursor.fetchall()]
```

### Replace `delete_session`:
```python
def delete_session(session_id: str, user_id: str = None):
    init_history_db()
    conn = get_connection()
    if user_id:
        cursor = conn.execute("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Session not found")
        if row['user_id'] != user_id:
            raise PermissionError("Not authorized to delete this session")
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
```

### ADD this new function at end of file:
```python
def get_session_owner(session_id: str) -> str:
    """Get the user_id that owns a session."""
    init_history_db()
    conn = get_connection()
    cursor = conn.execute("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    return row['user_id'] if row else None


def delete_all_sessions():
    """Delete all sessions and messages for clean start."""
    init_history_db()
    conn = get_connection()
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    logger.info("Deleted all sessions and messages")
```

---

## Step 6: Modify `backend/api/routes.py`

> **Modularity Feature**: Uses `SAML_ENABLED` environment variable. Set to `false` to disable auth completely.

### ADD at top of file (after existing imports):
```python
import os
from fastapi import Depends
from typing import Optional

# Feature flag for SAML authentication
SAML_ENABLED = os.getenv("SAML_ENABLED", "false").lower() == "true"

if SAML_ENABLED:
    from backend.saml.auth import get_current_user, get_optional_user, SAMLUser
else:
    # Dummy user when SAML is disabled
    class SAMLUser:
        user_id: str = "anonymous"
        email: str = None
        display_name: str = None
    
    async def get_current_user():
        return SAMLUser()
    
    async def get_optional_user():
        return SAMLUser()
```

### Replace `create_session_endpoint`:
```python
@router.post("/sessions")
def create_session_endpoint(request: CreateSessionRequest, user: SAMLUser = Depends(get_current_user)):
    from backend.state.history import create_new_session
    return create_new_session(request.title, user.user_id)
```

### Replace `get_sessions`:
```python
@router.get("/sessions")
def get_sessions(user: SAMLUser = Depends(get_current_user)):
    from backend.state.history import get_all_sessions
    return {"sessions": get_all_sessions(user.user_id)}
```

### Replace `delete_session_endpoint`:
```python
@router.delete("/sessions/{session_id}")
def delete_session_endpoint(session_id: str, user: SAMLUser = Depends(get_current_user)):
    from backend.state.history import delete_session
    try:
        delete_session(session_id, user.user_id)
        return {"status": "deleted", "id": session_id}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Replace `get_history`:
```python
@router.get("/history/{session_id}")
def get_history(session_id: str, user: SAMLUser = Depends(get_current_user)):
    from backend.state.history import get_session_history, get_session_owner
    owner = get_session_owner(session_id)
    if owner and owner != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to view this session")
    return {"messages": get_session_history(session_id)}
```

### Replace `chat_stream_endpoint` signature and add ownership check:
```python
@router.post("/chat/stream")
async def chat_stream_endpoint(request_body: ChatRequest, request: Request, user: SAMLUser = Depends(get_current_user)):
    from backend.state.history import add_message, create_session, get_session_owner
    
    # Verify ownership
    owner = get_session_owner(request_body.session_id)
    if owner and owner != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to use this session")
    
    # Ensure session exists with correct user
    create_session(request_body.session_id, user_id=user.user_id)
    
    # ... rest of existing code unchanged ...
```

---

## Step 7: Modify `backend/app.py`

### Replace the CORS middleware section:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://askme.ipr.res.in", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### ADD after existing router include:
```python
from backend.saml.routes import router as saml_router
app.include_router(saml_router)
```

---

## Step 8: Create `frontend/src/hooks/useAuth.ts`

**Action:** Create new file

```typescript
'use client';
import { useState, useEffect, useCallback } from 'react';

export interface User {
    user_id: string;
    email: string | null;
    display_name: string | null;
    authenticated: boolean;
}

export function useAuth() {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);

    const checkAuth = useCallback(async () => {
        try {
            const res = await fetch('/saml/check', { credentials: 'include' });
            const data = await res.json();
            if (data.authenticated) {
                setUser(data);
            } else {
                setUser(null);
            }
        } catch (e) {
            console.error('Auth check failed:', e);
            setUser(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        checkAuth();
    }, [checkAuth]);

    const login = useCallback((returnUrl: string = '/') => {
        window.location.href = `/saml/login?next=${encodeURIComponent(returnUrl)}`;
    }, []);

    const logout = useCallback(async () => {
        localStorage.removeItem('rag_session_id');
        window.location.href = '/saml/logout';
    }, []);

    return { user, loading, login, logout, checkAuth };
}
```

---

## Step 9: Create `frontend/src/components/AuthProvider.tsx`

**Action:** Create new file

```typescript
'use client';
import { createContext, useContext, ReactNode } from 'react';
import { useAuth, User } from '@/hooks/useAuth';

interface AuthContextType {
    user: User | null;
    loading: boolean;
    login: (returnUrl?: string) => void;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuthContext() {
    const context = useContext(AuthContext);
    if (!context) throw new Error('useAuthContext must be used within AuthProvider');
    return context;
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const auth = useAuth();

    if (auth.loading) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#0a0a0a', color: '#fff' }}>
                <div>Loading...</div>
            </div>
        );
    }

    if (!auth.user) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#0a0a0a', color: '#fff', gap: '20px' }}>
                <h1>RAG Chat IPR</h1>
                <p>Please login to continue</p>
                <button onClick={() => auth.login()} style={{ padding: '12px 24px', background: '#3b82f6', border: 'none', borderRadius: '8px', color: '#fff', cursor: 'pointer', fontSize: '16px' }}>
                    Login with SSO
                </button>
            </div>
        );
    }

    return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}
```

---

## Step 10: Modify `frontend/src/app/layout.tsx`

### ADD import at top:
```typescript
import { AuthProvider } from '@/components/AuthProvider';
```

### Wrap children with AuthProvider:
```typescript
// Change this:
{children}

// To this:
<AuthProvider>{children}</AuthProvider>
```

---

## Step 11: Fix URLs in Frontend Files

### In `useChat.ts`, replace `getApiBase`:
```typescript
const getApiBase = () => '/api';
```

### In `useChat.ts`, replace `fetchDocuments`:
```typescript
const fetchDocuments = useCallback(async () => {
    try {
        const res = await fetch('/api/documents', { credentials: 'include' });
        const data = await res.json();
        return data.documents || [];
    } catch (e) {
        console.error("Failed to fetch documents", e);
        return [];
    }
}, []);
```

### Add `credentials: 'include'` to ALL fetch calls in:
- `useChat.ts`: loadHistory, sendMessage
- `Sidebar.tsx`: fetchSessions, handleDelete, handleRename
- `ChatInterface.tsx`: fetchDocuments (if separate)

---

## Step 12: Append to `.env`

```bash
# ===========================================
# SAML SSO Configuration
# ===========================================

# FEATURE FLAG: Set to "true" to enable SAML, "false" to disable
# When false, the app works without any authentication (original behavior)
SAML_ENABLED=true

SAML_SP_ENTITY_ID=https://askme.ipr.res.in
SAML_SP_ACS_URL=https://askme.ipr.res.in/saml/acs
SAML_SP_SLO_URL=https://askme.ipr.res.in/saml/slo

# Fill these from your IdP admin
SAML_IDP_ENTITY_ID=your-idp-entity-id
SAML_IDP_SSO_URL=https://your-idp.example.com/saml/sso
SAML_IDP_SLO_URL=https://your-idp.example.com/saml/slo
SAML_IDP_CERT_FILE=/path/to/idp-certificate.pem

# Session Security (CHANGE THIS!)
SAML_SESSION_SECRET=generate-a-64-character-random-string-here
SAML_SESSION_MAX_AGE=28800
```

---

## Step 13: Update nginx Configuration

```nginx
server {
    listen 443 ssl;
    server_name askme.ipr.res.in;
    
    # Your existing SSL config...
    
    # CRITICAL: Forward headers for SAML
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    
    location /saml/ {
        proxy_pass http://localhost:8000/saml/;
    }
    
    location /api/ {
        proxy_pass http://localhost:8000/api/;
    }
    
    location / {
        proxy_pass http://localhost:3000/;
    }
}
```

---

## Step 14: Clean Start - Delete Existing Sessions

Run this Python command once to clear all sessions:

```python
from backend.state.history import delete_all_sessions
delete_all_sessions()
```

---

## Verification Checklist

- [ ] xmlsec1 installed on server
- [ ] python3-saml and PyJWT installed
- [ ] IdP certificate file exists at specified path
- [ ] .env has all SAML variables filled
- [ ] nginx reloaded with new config
- [ ] Backend restarted
- [ ] Frontend rebuilt
- [ ] Test: Visit https://askme.ipr.res.in → redirected to IdP
- [ ] Test: After login → see chat interface
- [ ] Test: Create session → belongs to your user
- [ ] Test: Logout → redirected to login page

---

## Modularity Summary: How to Disable SAML

The implementation is designed to be **easily toggled**:

### To Disable SAML (go back to pre-SAML behavior):

1. **Change `.env`:**
   ```bash
   SAML_ENABLED=false
   ```

2. **Restart backend** - that's it!

When `SAML_ENABLED=false`:
- No login required
- All sessions use `user_id="anonymous"`
- App works exactly like before SAML

### To Completely Remove SAML:

| What | Action |
|------|--------|
| `backend/saml/` folder | Delete entire folder |
| `backend/app.py` | Remove SAML router import & include |
| `frontend/src/hooks/useAuth.ts` | Delete file |
| `frontend/src/components/AuthProvider.tsx` | Delete file |
| `frontend/src/app/layout.tsx` | Remove AuthProvider wrapper |
| `backend/api/routes.py` | Remove SAML imports, set `SAML_ENABLED=False` |

The `history.py` and URL/credential changes can stay - they're backward compatible.
