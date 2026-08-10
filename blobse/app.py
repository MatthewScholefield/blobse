from uuid import uuid4
import time

from aioredis import Redis
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi_plugins import redis_plugin, depends_redis
from pydantic import UUID4
from fastapi.requests import Request
from fastapi.responses import Response

from blobse.config import config

app = FastAPI(title="Blobse", description="Simple small blob store over HTTP with safe locking")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOCK_TIMEOUT = 30
PUBLIC_EDIT_KEY = "public"

not_found_exception = HTTPException(status_code=404, detail="Blob not found")
locked_exception = HTTPException(status_code=423, detail="Blob is locked")
invalid_lock_exception = HTTPException(status_code=403, detail="Invalid or expired lock key")
invalid_edit_key_exception = HTTPException(status_code=403, detail="Invalid edit key")

CREATE_SCRIPT = """
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2])
return true
"""

LOCK_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then
    return -1
end
local edit_key = redis.call('GET', KEYS[3])
if not edit_key or (edit_key ~= 'public' and edit_key ~= ARGV[3]) then
    return -2
end
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
redis.call('SETEX', KEYS[1], ARGV[1], ARGV[2])
return 1
"""

MODIFY_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then
    return {-1, ""}
end
local edit_key = redis.call('GET', KEYS[3])
if not edit_key or (edit_key ~= 'public' and edit_key ~= ARGV[4]) then
    return {-2, ""}
end
local lock_data = redis.call('GET', KEYS[1])
if not lock_data then
    return {false, "Invalid or expired lock key"}
end
local lock_key, expiration_time = lock_data:match("([^:]+):([^:]+)")
if lock_key ~= ARGV[1] or tonumber(expiration_time) < tonumber(ARGV[2]) then
    return {false, "Invalid or expired lock key"}
end
redis.call('SET', KEYS[2], ARGV[3])
redis.call('DEL', KEYS[1])
return {true, ""}
"""

PUT_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then
    return -1
end
local edit_key = redis.call('GET', KEYS[3])
if not edit_key or (edit_key ~= 'public' and edit_key ~= ARGV[2]) then
    return -2
end
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
redis.call('SET', KEYS[2], ARGV[1])
return 1
"""

RELEASE_LOCK_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then
    return -1
end
local edit_key = redis.call('GET', KEYS[3])
if not edit_key or (edit_key ~= 'public' and edit_key ~= ARGV[1]) then
    return -2
end
if redis.call('DEL', KEYS[1]) ~= 1 then
    return 0
end
return 1
"""

DELETE_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 0 then
    return -1
end
local edit_key = redis.call('GET', KEYS[3])
if not edit_key or (edit_key ~= 'public' and edit_key ~= ARGV[1]) then
    return -2
end
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
redis.call('DEL', KEYS[2])
redis.call('DEL', KEYS[3])
return 1
"""


def edit_key_name(uuid: UUID4) -> str:
    return f"edit-key:{uuid}"


def raise_for_edit_result(result) -> None:
    if result == -1:
        raise not_found_exception
    if result == -2:
        raise invalid_edit_key_exception


@app.on_event("startup")
async def on_startup() -> None:
    await redis_plugin.init_app(app, config=config)
    await redis_plugin.init()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await redis_plugin.terminate()


@app.post("/blob/{uuid}/lock")
async def lock_blob(
    uuid: UUID4,
    redis: Redis = Depends(depends_redis),
    x_edit_key: str = Header(None),
):
    lock_key = str(uuid4())
    expiration_time = int(time.time()) + LOCK_TIMEOUT
    result = await redis.eval(
        LOCK_SCRIPT,
        keys=[f"lock:{uuid}", f"blob:{uuid}", edit_key_name(uuid)],
        args=[str(LOCK_TIMEOUT), f"{lock_key}:{expiration_time}", x_edit_key]
    )
    raise_for_edit_result(result)
    if result == 0:
        raise locked_exception

    blob = await redis.get(f"blob:{uuid}")
    response = Response(content=blob)
    response.headers["X-Lock-Key"] = lock_key
    return response


@app.put("/blob/{uuid}/locked-content")
async def modify_locked_blob(
    request: Request,
    uuid: UUID4,
    redis: Redis = Depends(depends_redis),
    x_lock_key: str = Header(None),
    x_edit_key: str = Header(None),
):
    new_blob = await request.body()
    current_time = int(time.time())
    result = await redis.eval(
        MODIFY_SCRIPT,
        keys=[f"lock:{uuid}", f"blob:{uuid}", edit_key_name(uuid)],
        args=[x_lock_key, str(current_time), new_blob, x_edit_key]
    )
    raise_for_edit_result(result[0])
    if not result[0]:
        raise invalid_lock_exception
    return Response(content="")


@app.delete("/blob/{uuid}/lock")
async def release_lock(
    uuid: UUID4,
    redis: Redis = Depends(depends_redis),
    x_edit_key: str = Header(None),
):
    result = await redis.eval(
        RELEASE_LOCK_SCRIPT,
        keys=[f"lock:{uuid}", f"blob:{uuid}", edit_key_name(uuid)],
        args=[x_edit_key]
    )
    raise_for_edit_result(result)
    if result == 0:
        raise not_found_exception
    return Response(content="")


@app.post("/blob/new")
async def new_blob(
    request: Request,
    redis: Redis = Depends(depends_redis),
    x_edit_key: str = Header(None),
):
    blob = await request.body()
    uuid = str(uuid4())
    edit_key = PUBLIC_EDIT_KEY if x_edit_key == PUBLIC_EDIT_KEY else str(uuid4())
    await redis.eval(
        CREATE_SCRIPT,
        keys=[f"blob:{uuid}", f"edit-key:{uuid}"],
        args=[blob, edit_key]
    )

    response = Response(content=f"{config.server_url}/blob/{uuid}")
    if edit_key != PUBLIC_EDIT_KEY:
        response.headers["X-Edit-Key"] = edit_key
    return response


@app.get("/blob/{uuid}")
async def get_blob(uuid: UUID4, redis: Redis = Depends(depends_redis)):
    blob = await redis.get(f"blob:{uuid}")
    if blob is None:
        raise not_found_exception
    return Response(content=blob)


@app.put("/blob/{uuid}")
async def put_blob(
    uuid: UUID4,
    request: Request,
    redis: Redis = Depends(depends_redis),
    x_edit_key: str = Header(None),
):
    new_blob = await request.body()
    result = await redis.eval(
        PUT_SCRIPT,
        keys=[f"lock:{uuid}", f"blob:{uuid}", edit_key_name(uuid)],
        args=[new_blob, x_edit_key]
    )
    raise_for_edit_result(result)
    if result == 0:
        raise locked_exception
    return Response(content=b"")


@app.delete("/blob/{uuid}")
async def delete_blob(
    uuid: UUID4,
    redis: Redis = Depends(depends_redis),
    x_edit_key: str = Header(None),
):
    result = await redis.eval(
        DELETE_SCRIPT,
        keys=[f"lock:{uuid}", f"blob:{uuid}", edit_key_name(uuid)],
        args=[x_edit_key]
    )
    raise_for_edit_result(result)
    if result == 0:
        raise locked_exception
    return Response(content=b"")
