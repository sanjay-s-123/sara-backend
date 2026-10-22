import os
from typing import Optional
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from app.core.config import settings

def _init_firebase_admin():
    if not firebase_admin._apps:
        try:
            cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
            cred_path = settings.FIREBASE_CREDENTIALS_PATH
            if cred_json:
                import json
                cred = credentials.Certificate(json.loads(cred_json))
                firebase_admin.initialize_app(cred, {"projectId": settings.FIREBASE_PROJECT_ID})
            elif cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {"projectId": settings.FIREBASE_PROJECT_ID})
            elif settings.FIREBASE_PROJECT_ID:
                firebase_admin.initialize_app(options={"projectId": settings.FIREBASE_PROJECT_ID})
        except Exception:
            pass

_init_firebase_admin()

security = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> str:
    """Verifies Firebase ID token and returns authenticated user ID."""
    if not credentials:
        if settings.ENVIRONMENT == "development":
            return "dev_mock_user_123"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = credentials.credentials
    if token.startswith("mock-token-"):
        if settings.ENVIRONMENT == "development":
            return token.replace("mock-token-", "")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mock tokens are only allowed in development environment",
        )

    try:
        decoded_token = firebase_auth.verify_id_token(token)
        return (decoded_token.get("email") or decoded_token["uid"]).lower()
    except Exception as e:
        if settings.ENVIRONMENT == "development":
            return "dev_mock_user_123"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication token: {str(e)}",
        )
