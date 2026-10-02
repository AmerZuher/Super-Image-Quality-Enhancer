"""API keys and signing in with one (when ``SIQE_API_AUTH=keys``)."""

import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from siqe.api.deps import SessionDep, SettingsDep
from siqe.api.schemas import ApiKeyCreatedOut, ApiKeyIn, ApiKeyOut, AuthStatusOut, SignInIn
from siqe.auth.keys import check, create_key, forget
from siqe.auth.middleware import COOKIE, credential
from siqe.core.errors import AppError, NotFoundError
from siqe.db.base import utcnow
from siqe.db.models import ApiKey

router = APIRouter(tags=["access"])

COOKIE_DAYS = 90


def _key_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut.model_validate(key, from_attributes=True)


@router.get("/auth/status", response_model=AuthStatusOut, summary="Whether this app asks for a key")
async def auth_status(request: Request, session: SessionDep, settings: SettingsDep) -> AuthStatusOut:
    if settings.api_auth == "off":
        return AuthStatusOut(mode="off", signed_in=True)
    secret = credential(request.scope)
    found = await check(session, secret) if secret else None
    return AuthStatusOut(mode="keys", signed_in=found is not None, key_name=found.name if found else None)


@router.post(
    "/auth/session",
    response_model=AuthStatusOut,
    summary="Sign this browser in with an API key",
    description="Sets an HttpOnly cookie holding the key; scripts should send the key in a header instead.",
)
async def sign_in(
    body: SignInIn, request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> AuthStatusOut:
    found = await check(session, body.key.strip())
    if found is None:
        raise AppError(
            "auth.invalid_key",
            "That API key isn't valid. It may have been revoked.",
            status=401,
            title="Key not accepted",
            fix="Check you copied the whole key, or create a new one with `siqe keys create`.",
        )
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE,
        body.key.strip(),
        max_age=COOKIE_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/api",
    )
    return AuthStatusOut(mode=settings.api_auth, signed_in=True, key_name=found.name)


@router.delete(
    "/auth/session",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Sign this browser out",
)
async def sign_out() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(COOKIE, path="/api", httponly=True, samesite="strict")
    return response


@router.get("/keys", response_model=list[ApiKeyOut], summary="API keys, newest first")
async def list_keys(session: SessionDep) -> list[ApiKeyOut]:
    keys = (await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars()
    return [_key_out(k) for k in keys]


@router.post(
    "/keys",
    response_model=ApiKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key (the key is shown only in this response)",
)
async def new_key(body: ApiKeyIn, session: SessionDep) -> ApiKeyCreatedOut:
    key, secret = await create_key(session, body.name)
    await session.commit()
    return ApiKeyCreatedOut.model_validate({**_key_out(key).model_dump(), "secret": secret})


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Revoke an API key; anything using it stops working",
)
async def revoke_key(
    key_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise NotFoundError("auth.key_not_found", "That API key doesn't exist.", title="Key not found")
    current = request.scope.get("state", {}).get("api_key")
    if settings.api_auth == "keys" and current is not None and current.key_id == key.id:
        live = (
            await session.execute(
                select(ApiKey.id).where(ApiKey.revoked_at.is_(None), ApiKey.id != key.id).limit(1)
            )
        ).first()
        if live is None:
            raise AppError(
                "auth.last_key",
                "This is the only key left and you're signed in with it, so revoking it would lock you out.",
                status=409,
                title="Last key",
                fix="Create another key first, or turn sign-in off with SIQE_API_AUTH=off.",
            )
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        await session.commit()
    forget(key.hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
