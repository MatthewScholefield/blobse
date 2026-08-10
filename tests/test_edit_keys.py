import asyncio
from uuid import UUID

import pytest

pytest.importorskip("aioredis")
pytest.importorskip("fastapi_plugins")

from blobse import app


class Request:
    def __init__(self, body):
        self._body = body

    async def body(self):
        return self._body


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    async def eval(self, script, *, keys, args):
        if script == app.CREATE_SCRIPT:
            self.values[keys[0]] = args[0]
            self.values[keys[1]] = args[1]
            return True

        blob_exists = keys[1] in self.values
        edit_key = self.values.get(keys[2])
        provided_edit_key = args[-1]
        edit_key_is_valid = edit_key == app.PUBLIC_EDIT_KEY or edit_key == provided_edit_key

        if script == app.LOCK_SCRIPT:
            if not blob_exists:
                return -1
            if not edit_key or not edit_key_is_valid:
                return -2
            if keys[0] in self.values:
                return 0
            self.values[keys[0]] = args[1]
            return 1

        if script == app.MODIFY_SCRIPT:
            if not blob_exists:
                return [-1, ""]
            if not edit_key or not edit_key_is_valid:
                return [-2, ""]
            lock_data = self.values.get(keys[0])
            if lock_data is None:
                return [False, "Invalid or expired lock key"]
            lock_key, expiration = lock_data.split(":", 1)
            if lock_key != args[0] or int(expiration) < int(args[1]):
                return [False, "Invalid or expired lock key"]
            self.values[keys[1]] = args[2]
            del self.values[keys[0]]
            return [True, ""]

        if script == app.PUT_SCRIPT:
            if not blob_exists:
                return -1
            if not edit_key or not edit_key_is_valid:
                return -2
            if keys[0] in self.values:
                return 0
            self.values[keys[1]] = args[0]
            return 1

        if script == app.RELEASE_LOCK_SCRIPT:
            if not blob_exists:
                return -1
            if not edit_key or not edit_key_is_valid:
                return -2
            return int(self.values.pop(keys[0], None) is not None)

        if script == app.DELETE_SCRIPT:
            if not blob_exists:
                return -1
            if not edit_key or not edit_key_is_valid:
                return -2
            if keys[0] in self.values:
                return 0
            del self.values[keys[1]]
            del self.values[keys[2]]
            return 1

        raise AssertionError("unexpected Redis script")


def run(coroutine):
    return asyncio.run(coroutine)


def create(redis, body=b"original", edit_key=None):
    response = run(app.new_blob(Request(body), redis, edit_key))
    uuid = UUID(response.body.decode().rsplit("/", 1)[1])
    return uuid, response


def assert_forbidden(coroutine):
    with pytest.raises(app.HTTPException) as error:
        run(coroutine)
    assert error.value.status_code == 403
    assert error.value.detail == "Invalid edit key"


def test_create_persists_generated_or_public_edit_key():
    redis = FakeRedis()

    private_uuid, private_response = create(redis)
    public_uuid, public_response = create(redis, edit_key=app.PUBLIC_EDIT_KEY)
    supplied_uuid, supplied_response = create(redis, edit_key="not-an-edit-key")

    assert private_response.headers["x-edit-key"] == redis.values[f"edit-key:{private_uuid}"]
    assert redis.values[f"blob:{private_uuid}"] == b"original"
    assert "x-edit-key" not in public_response.headers
    assert redis.values[f"edit-key:{public_uuid}"] == app.PUBLIC_EDIT_KEY
    assert supplied_response.headers["x-edit-key"] != "not-an-edit-key"
    assert redis.values[f"edit-key:{supplied_uuid}"] == supplied_response.headers["x-edit-key"]


def test_private_missing_and_wrong_keys_are_rejected_by_every_mutable_route():
    redis = FakeRedis()
    uuid, response = create(redis)
    edit_key = response.headers["x-edit-key"]

    operations = [
        lambda key: app.put_blob(uuid, Request(b"updated"), redis, key),
        lambda key: app.lock_blob(uuid, redis, key),
        lambda key: app.modify_locked_blob(Request(b"updated"), uuid, redis, "lock", key),
        lambda key: app.release_lock(uuid, redis, key),
        lambda key: app.delete_blob(uuid, redis, key),
    ]
    for operation in operations:
        assert_forbidden(operation(None))
        assert_forbidden(operation("wrong-key"))

    assert redis.values[f"blob:{uuid}"] == b"original"
    assert redis.values[f"edit-key:{uuid}"] == edit_key


def test_public_blobs_allow_anonymous_mutable_paths():
    redis = FakeRedis()
    uuid, _ = create(redis, edit_key=app.PUBLIC_EDIT_KEY)

    run(app.put_blob(uuid, Request(b"public update"), redis, None))
    lock_response = run(app.lock_blob(uuid, redis, None))
    lock_key = lock_response.headers["x-lock-key"]
    run(app.modify_locked_blob(Request(b"locked public update"), uuid, redis, lock_key, None))
    run(app.lock_blob(uuid, redis, None))
    run(app.release_lock(uuid, redis, None))
    run(app.delete_blob(uuid, redis, None))

    assert f"blob:{uuid}" not in redis.values
    assert f"edit-key:{uuid}" not in redis.values
    assert f"lock:{uuid}" not in redis.values


def test_legacy_blobs_are_readable_but_denied_by_every_mutable_route():
    redis = FakeRedis()
    uuid = UUID("00000000-0000-4000-8000-000000000001")
    redis.values[f"blob:{uuid}"] = b"legacy"

    assert run(app.get_blob(uuid, redis)).body == b"legacy"
    operations = [
        app.put_blob(uuid, Request(b"updated"), redis, None),
        app.lock_blob(uuid, redis, None),
        app.modify_locked_blob(Request(b"updated"), uuid, redis, "lock", None),
        app.release_lock(uuid, redis, None),
        app.delete_blob(uuid, redis, None),
    ]
    for operation in operations:
        assert_forbidden(operation)
    assert redis.values[f"blob:{uuid}"] == b"legacy"


def test_locked_content_requires_both_valid_edit_and_lock_credentials():
    redis = FakeRedis()
    uuid, response = create(redis)
    edit_key = response.headers["x-edit-key"]
    lock_key = run(app.lock_blob(uuid, redis, edit_key)).headers["x-lock-key"]

    assert_forbidden(app.modify_locked_blob(Request(b"blocked"), uuid, redis, lock_key, None))
    assert_forbidden(app.modify_locked_blob(Request(b"blocked"), uuid, redis, lock_key, "wrong-key"))
    with pytest.raises(app.HTTPException) as error:
        run(app.modify_locked_blob(Request(b"blocked"), uuid, redis, None, edit_key))
    assert error.value.status_code == 403
    assert error.value.detail == "Invalid or expired lock key"

    run(app.modify_locked_blob(Request(b"updated"), uuid, redis, lock_key, edit_key))
    assert redis.values[f"blob:{uuid}"] == b"updated"
    assert f"lock:{uuid}" not in redis.values


def test_release_and_delete_respect_locks_and_remove_metadata():
    redis = FakeRedis()
    uuid, response = create(redis)
    edit_key = response.headers["x-edit-key"]

    run(app.lock_blob(uuid, redis, edit_key))
    with pytest.raises(app.HTTPException) as error:
        run(app.delete_blob(uuid, redis, edit_key))
    assert error.value.status_code == 423

    run(app.release_lock(uuid, redis, edit_key))
    assert f"lock:{uuid}" not in redis.values
    with pytest.raises(app.HTTPException) as error:
        run(app.release_lock(uuid, redis, edit_key))
    assert error.value.status_code == 404

    run(app.delete_blob(uuid, redis, edit_key))
    assert f"blob:{uuid}" not in redis.values
    assert f"edit-key:{uuid}" not in redis.values
