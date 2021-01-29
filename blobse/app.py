from uuid import uuid4

from aioredis import Redis
from fastapi import FastAPI, Depends, HTTPException
from fastapi_plugins import redis_plugin, depends_redis
from loguru import logger
from pydantic import UUID4
from pydantic.main import BaseModel
from fastapi.requests import Request
from fastapi.responses import Response

from blobse.config import config

app = FastAPI(
    title='Blobse',
    description='Simple small blob store over HTTP'
)
not_found_exception = HTTPException(status_code=404, detail='Blob not found')


@app.on_event("startup")
async def on_startup() -> None:
    await redis_plugin.init_app(app, config=config)
    logger.info(
        "Connecting to {}. Will hang if redis-server not started...",
        config.get_redis_address(),
    )
    await redis_plugin.init()  # Will hang if redis-server not started
    logger.info("Connected to Redis.")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await redis_plugin.terminate()


class BlobInfo(BaseModel):
    resource: str


@app.post('/new', response_model=BlobInfo)
async def new_blob(request: Request, redis: Redis = Depends(depends_redis)):
    blob = await request.body()
    uuid = str(uuid4())
    await redis.set(f'blob:{uuid}', blob)  # ensure at least one char
    return BlobInfo(resource=f'{config.server_url}/blob/{uuid}')


@app.get('/blob/{uuid}')
async def get_blob_route(uuid: UUID4, redis: Redis = Depends(depends_redis)):
    blob = await redis.get(f'blob:{uuid}')
    if blob is None:
        raise not_found_exception
    return Response(content=blob)


@app.put('/blob/{uuid}')
async def put_blob_route(
    request: Request, uuid: UUID4,
    redis: Redis = Depends(depends_redis)
):
    count = await redis.exists(f'blob:{uuid}')
    if count != 1:
        raise not_found_exception
    await redis.set(f'blob:{uuid}', await request.body())
    return Response(content="")


@app.delete('/blob/{uuid}')
async def delete_blob(uuid: UUID4, redis: Redis = Depends(depends_redis)):
    count = await redis.delete(f'blob:{uuid}')
    if count != 1:
        raise not_found_exception
    return Response(content="")
