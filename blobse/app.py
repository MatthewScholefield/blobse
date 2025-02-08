from uuid import uuid4
import time

from aioredis import Redis
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi_plugins import redis_plugin, depends_redis
from loguru import logger
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

not_found_exception = HTTPException(status_code=404, detail="Blob not found")
locked_exception = HTTPException(status_code=423, detail="Blob is locked")
invalid_lock_exception = HTTPException(status_code=403, detail="Invalid or expired lock key")

LOCK_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return nil
end
redis.call('SETEX', KEYS[1], ARGV[1], ARGV[2])
return ARGV[2]
"""

MODIFY_SCRIPT = """
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

CHECK_LOCK_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return false
end
redis.call('SET', KEYS[2], ARGV[1])
return true
"""


@app.on_event("startup")
async def on_startup() -> None:
    await redis_plugin.init_app(app, config=config)
    await redis_plugin.init()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await redis_plugin.terminate()


@app.post("/blob/{uuid}/lock")
async def lock_blob(uuid: UUID4, redis: Redis = Depends(depends_redis)):
    blob = await redis.get(f"blob:{uuid}")
    if blob is None:
        raise not_found_exception

    lock_key = str(uuid4())
    expiration_time = int(time.time()) + LOCK_TIMEOUT

    result = await redis.eval(LOCK_SCRIPT, keys=[f"lock:{uuid}"], args=[str(LOCK_TIMEOUT), f"{lock_key}:{expiration_time}"])
    if result is None:
        raise locked_exception

    response = Response(content=blob)
    response.headers["X-Lock-Key"] = lock_key
    return response


@app.put("/blob/{uuid}/locked-content")
async def modify_locked_blob(
    request: Request,
    uuid: UUID4,
    redis: Redis = Depends(depends_redis),
    x_lock_key: str = Header(None),
):
    new_blob = await request.body()
    current_time = int(time.time())

    result = await redis.eval(
        MODIFY_SCRIPT,
        keys=[f"lock:{uuid}", f"blob:{uuid}"],
        args=[x_lock_key, str(current_time), new_blob]
    )

    if not result[0]:
        raise invalid_lock_exception

    return Response(content="")


@app.delete("/blob/{uuid}/lock")
async def release_lock(uuid: UUID4, redis: Redis = Depends(depends_redis)):
    count = await redis.delete(f"lock:{uuid}")
    if count != 1:
        raise not_found_exception
    return Response(content="")


@app.post("/blob/new")
async def new_blob(request: Request, redis: Redis = Depends(depends_redis)):
    blob = await request.body()
    uuid = str(uuid4())
    await redis.set(f"blob:{uuid}", blob)
    return Response(content=f"{config.server_url}/blob/{uuid}")


@app.get("/blob/{uuid}")
async def get_blob(uuid: UUID4, redis: Redis = Depends(depends_redis)):
    blob = await redis.get(f"blob:{uuid}")
    if blob is None:
        raise not_found_exception
    return Response(content=blob)


@app.put("/blob/{uuid}")
async def put_blob(uuid: UUID4, request: Request, redis: Redis = Depends(depends_redis)):
    new_blob = await request.body()

    result = await redis.eval(
        CHECK_LOCK_SCRIPT,
        keys=[f"lock:{uuid}", f"blob:{uuid}"],
        args=[new_blob]
    )

    if not result:
        raise locked_exception

    return Response(content=b"")


@app.delete("/blob/{uuid}")
async def delete_blob(uuid: UUID4, redis: Redis = Depends(depends_redis)):
    if await redis.exists(f"lock:{uuid}"):
        raise locked_exception

    count = await redis.delete(f"blob:{uuid}")
    if count != 1:
        raise not_found_exception
    return Response(content=b"")
