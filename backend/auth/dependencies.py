"""FastAPI auth dependencies."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Cookie, Depends, Header

from api.errors import AuthenticationError
from auth.utils import TokenError, decode_access_token


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Cookie()] = None,
) -> dict:
    """Resolve the caller from either an Authorization header or the token cookie.

    The header wins when both are present, so an explicit API call is never
    silently answered as whoever happens to be logged in in the browser.
    """
    raw_token: str | None = None

    if authorization and authorization.startswith('Bearer '):
        raw_token = authorization[7:].strip()
    elif token:
        raw_token = token.strip()

    if not raw_token:
        raise AuthenticationError('Authentication required')

    try:
        payload = await asyncio.to_thread(decode_access_token, raw_token)
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    if not payload.get('user_id'):
        raise AuthenticationError('Invalid token payload')

    return payload


CurrentUser = Annotated[dict, Depends(get_current_user)]
