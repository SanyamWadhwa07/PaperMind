"""FastAPI auth dependencies — replaces the Flask @token_required decorator."""

import asyncio
from typing import Annotated
from fastapi import Depends, HTTPException, Header, Cookie
from auth.utils import decode_access_token


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Cookie()] = None,
) -> dict:
    """
    Extract and validate the JWT from either:
    - Authorization: Bearer <token>  (used by existing frontend)
    - token cookie (httpOnly, set on login — more secure)
    """
    raw_token: str | None = None

    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization[7:]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        payload = await asyncio.to_thread(decode_access_token, raw_token)
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


CurrentUser = Annotated[dict, Depends(get_current_user)]
