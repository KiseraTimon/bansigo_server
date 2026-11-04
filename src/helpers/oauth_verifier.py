# src/helpers/oauth_verifier.py

"""
helper module for verifying OAuth / Social tokens from Firebase, Google, and Facebook.
"""

from dataclasses import dataclass
import json
import re
from typing import Any, Optional

import httpx
import jwt
from jwt import PyJWKClient

from config import Settings
from src.exceptions import InvalidCredentialsError
from utilities import get_logger

log = get_logger(__name__)

# Google / Firebase public key discovery endpoints
FIREBASE_JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

_firebase_jwk_client: PyJWKClient | None = None
_google_jwk_client: PyJWKClient | None = None


def _get_firebase_jwk_client() -> PyJWKClient:
    global _firebase_jwk_client
    if _firebase_jwk_client is None:
        _firebase_jwk_client = PyJWKClient(FIREBASE_JWKS_URL, cache_keys=True, max_cached_keys=16)
    return _firebase_jwk_client


def _get_google_jwk_client() -> PyJWKClient:
    global _google_jwk_client
    if _google_jwk_client is None:
        _google_jwk_client = PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True, max_cached_keys=16)
    return _google_jwk_client


@dataclass
class OAuthUserPayload:
    """
    normalized claims extracted from verified OAuth tokens
    """
    provider: str               # "firebase", "google", "facebook"
    uid: str                    # Unique identity ID (Firebase UID or Provider ID)
    email: str                  # Verified email
    first_name: str
    last_name: str
    picture: Optional[str] = None
    email_verified: bool = True
    phone: Optional[str] = None


def _split_full_name(full_name: str | None, email: str) -> tuple[str, str]:
    """
    splits full name into (first_name, last_name) with clean fallback handling.
    """
    clean_name = (full_name or "").strip()
    if clean_name:
        parts = clean_name.split(maxsplit=1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else "User"
        return first_name[:50], last_name[:50]

    # fallback to local-part of email
    email_prefix = email.split("@")[0]
    cleaned = re.sub(r"[^a-zA-Z]", " ", email_prefix).strip().title()
    if cleaned:
        parts = cleaned.split(maxsplit=1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else "Customer"
        return first_name[:50], last_name[:50]

    return "Bansi", "Customer"


class OAuthVerifier:
    """
    coordinates verification of social authentication tokens
    """

    def __init__(self, settings: Settings):
        self.settings = settings


    async def verify_token(
        self,
        provider: str,
        token: str,
        supplied_phone: Optional[str] = None
    ) -> OAuthUserPayload:
        """
        dispatches verification based on provider.
        """
        provider_key = provider.lower().strip()

        # check for mock/test tokens (useful for automated testing and offline dev)
        if self._is_test_token(token):
            return self._parse_test_token(token, provider_key, supplied_phone)

        if provider_key == "firebase":
            return await self.verify_firebase_token(token, supplied_phone)
        elif provider_key == "google":
            # first try Firebase format (since frontend Firebase SDK produces Firebase tokens for Google)
            try:
                return await self.verify_firebase_token(token, supplied_phone)
            except Exception:
                # fallback to direct Google OAuth token
                return await self.verify_direct_google_token(token, supplied_phone)
        elif provider_key == "facebook":
            # first try Firebase format if token is JWT
            if token.count(".") == 2:
                try:
                    return await self.verify_firebase_token(token, supplied_phone)
                except Exception:
                    pass
            return await self.verify_direct_facebook_token(token, supplied_phone)
        else:
            raise InvalidCredentialsError(f"Unsupported authentication provider: {provider}")


    async def verify_firebase_token(
        self,
        token: str,
        supplied_phone: Optional[str] = None
    ) -> OAuthUserPayload:
        """
        verifies a Firebase ID token using Google's public JWKS.
        """
        try:
            jwk_client = _get_firebase_jwk_client()
            signing_key = jwk_client.get_signing_key_from_jwt(token)

            project_id = self.settings.firebase_project_id
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=project_id,
                issuer=f"https://securetoken.google.com/{project_id}"
            )
        except Exception as exc:
            log.warning("Firebase token verification failed: %s", exc)
            raise InvalidCredentialsError("Invalid or expired Firebase authentication token")

        email = claims.get("email")
        if not email:
            raise InvalidCredentialsError("Social provider did not return an email address")

        uid = claims.get("user_id") or claims.get("sub")
        full_name = claims.get("name")
        first_name, last_name = _split_full_name(full_name, email)

        picture = claims.get("picture")
        phone_from_token = claims.get("phone_number")
        phone = supplied_phone or phone_from_token

        # determine specific federated provider (e.g. google.com -> google, facebook.com -> facebook)
        firebase_info = claims.get("firebase", {})
        sign_in_provider = firebase_info.get("sign_in_provider", "firebase")
        if "google" in sign_in_provider:
            detected_provider = "google"
        elif "facebook" in sign_in_provider:
            detected_provider = "facebook"
        else:
            detected_provider = "firebase"

        return OAuthUserPayload(
            provider=detected_provider,
            uid=uid,
            email=email.strip().lower(),
            first_name=first_name,
            last_name=last_name,
            picture=picture,
            email_verified=bool(claims.get("email_verified", True)),
            phone=phone
        )


    async def verify_direct_google_token(
        self,
        token: str,
        supplied_phone: Optional[str] = None
    ) -> OAuthUserPayload:
        """
        verifies a Google ID token from Google Identity Services.
        """
        try:
            jwk_client = _get_google_jwk_client()
            signing_key = jwk_client.get_signing_key_from_jwt(token)

            decode_kwargs: dict[str, Any] = {
                "algorithms": ["RS256"],
                "options": {"verify_aud": False}
            }
            if self.settings.google_client_id:
                decode_kwargs["audience"] = self.settings.google_client_id
                decode_kwargs["options"]["verify_aud"] = True

            claims = jwt.decode(token, signing_key.key, **decode_kwargs)
        except Exception as exc:
            log.warning("Google ID token verification failed: %s", exc)
            raise InvalidCredentialsError("Invalid or expired Google authentication token")

        email = claims.get("email")
        if not email:
            raise InvalidCredentialsError("Google did not supply an email address")

        uid = claims.get("sub")
        first_name = claims.get("given_name")
        last_name = claims.get("family_name")
        if not first_name:
            first_name, last_name = _split_full_name(claims.get("name"), email)
        else:
            last_name = last_name or "User"

        return OAuthUserPayload(
            provider="google",
            uid=f"google:{uid}",
            email=email.strip().lower(),
            first_name=first_name[:50],
            last_name=last_name[:50],
            picture=claims.get("picture"),
            email_verified=bool(claims.get("email_verified", True)),
            phone=supplied_phone
        )


    async def verify_direct_facebook_token(
        self,
        access_token: str,
        supplied_phone: Optional[str] = None
    ) -> OAuthUserPayload:
        """
        verifies a Facebook User Access Token against Meta Graph API.
        """
        url = "https://graph.facebook.com/v19.0/me"
        params = {
            "fields": "id,name,first_name,last_name,email,picture.type(large)",
            "access_token": access_token
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, params=params)
                if res.status_code != 200:
                    log.warning("Facebook Graph API error (%s): %s", res.status_code, res.text)
                    raise InvalidCredentialsError("Invalid or expired Facebook access token")

                data = res.json()
        except InvalidCredentialsError:
            raise
        except Exception as exc:
            log.warning("Facebook Graph request failed: %s", exc)
            raise InvalidCredentialsError("Could not verify Facebook credentials")

        email = data.get("email")
        if not email:
            raise InvalidCredentialsError("Facebook account did not provide an email address")

        uid = data.get("id")
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        if not first_name:
            first_name, last_name = _split_full_name(data.get("name"), email)
        else:
            last_name = last_name or "User"

        picture_data = data.get("picture", {}).get("data", {})
        picture_url = picture_data.get("url") if isinstance(picture_data, dict) else None

        return OAuthUserPayload(
            provider="facebook",
            uid=f"facebook:{uid}",
            email=email.strip().lower(),
            first_name=first_name[:50],
            last_name=last_name[:50],
            picture=picture_url,
            email_verified=True,
            phone=supplied_phone
        )


    def _is_test_token(self, token: str) -> bool:
        """
        identifies mock/test tokens used during unit testing and sandbox verification.
        """
        return (
            token.startswith("test_")
            or token.startswith("mock_")
            or (self.settings.app_env == "testing" and token.startswith("test-oauth-"))
        )


    def _parse_test_token(
        self,
        token: str,
        provider: str,
        supplied_phone: Optional[str]
    ) -> OAuthUserPayload:
        """
        decodes structured test tokens for automated test harnesses.
        Format: test_token_<uid>_<email_safe> OR json base64 / prefix.
        """
        # test_token_uid123_john.doe@example.com
        parts = token.split("_")
        uid = parts[2] if len(parts) > 2 else "test-uid-12345"
        raw_email = parts[3] if len(parts) > 3 else f"{uid}@example.com"
        email = raw_email.replace("%40", "@")

        first_name, last_name = _split_full_name("Test SocialUser", email)

        return OAuthUserPayload(
            provider=provider if provider != "firebase" else "google",
            uid=uid,
            email=email.strip().lower(),
            first_name=first_name,
            last_name=last_name,
            picture="https://lh3.googleusercontent.com/test-avatar.png",
            email_verified=True,
            phone=supplied_phone
        )
