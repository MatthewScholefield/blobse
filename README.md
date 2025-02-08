# Blobse

_Simple small blob store over HTTP_

This is a simple server with an API to store arbitrary data blobs API operating
anonymously over HTTP. This is useful for use in small client-side applications and
command-line tools that need temporary storage.

## API

```console
$ # Create new blob
$ curl -X POST https://blobse.us.to/new -d myData
{"resource":"https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931"}

$ # Get blob
$ curl -X GET https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931
myData

$ # Modify blob
$ curl -X PUT https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 -d myNewData
$ curl -X GET https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931
myNewData

$ # Delete blob
$ curl -X DELETE https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931
$ curl -X GET https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 -D -
HTTP/1.1 404 Not Found
{"detail":"Blob not found"}
```

## Locking Workflow

The API provides a safe locking mechanism for modifying blobs to prevent race conditions.  
Once a blob is locked, it **cannot be modified or deleted** unless using the lock key.

```console
$ # Lock a blob and retrieve its contents
$ curl -X POST https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/lock -D -
HTTP/1.1 200 OK
X-Lock-Key: 550e8400-e29b-41d4-a716-446655440000

myData

$ # Modify the locked blob using the lock key
$ curl -X PUT https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/locked-content \
    -H "X-Lock-Key: 550e8400-e29b-41d4-a716-446655440000" -d myUpdatedData

$ # Trying to modify a locked blob without a lock key fails
$ curl -X PUT https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 -d unauthorizedData -D -
HTTP/1.1 423 Locked
{"detail":"Blob is locked"}

$ # Delete the lock manually if needed
$ curl -X DELETE https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/lock
```

Locks expire automatically **after 30 seconds** if not used.

## Setup

First, install `redis-server` and have it running on the default port (6379).

Then, you can install this as a standard Python package or run:

```bash
./setup.sh
```

This installs the `blobse` executable into a new `.venv/` virtual environment.

### Configuring Environment

After running `setup.sh`, you might want to edit `.env` to set a custom server URL.

## Running

First, source the virtual environment created under `.venv`:

```bash
source .venv/bin/activate
```

Now, to run the backend, use the `blobse` executable:

```bash
blobse run
```

## Production

You can set up production-related aspects using `nginx`. Here is a conservative site
config used for [blobse.us.to](https://blobse.us.to):

```nginx
limit_req_zone $binary_remote_addr zone=blobse_doc:50k rate=30r/m;
limit_req_zone $binary_remote_addr zone=blobse_new_blob:50k rate=3r/m;
limit_req_zone $binary_remote_addr zone=blobse_mod_blob:50k rate=30r/m;

server {
    server_name blobse.us.to;
    listen *:80;

    location / {
        limit_req zone=blobse_doc burst=3 nodelay;
        proxy_pass http://0.0.0.0:7330/redoc;
    }

    location /openapi.json {
        limit_req zone=blobse_doc burst=3 nodelay;
        proxy_pass http://0.0.0.0:7330/openapi.json;
    }

    location /new {
        limit_req zone=blobse_new_blob burst=10 nodelay;
        proxy_pass http://0.0.0.0:7330/new;
    }

    location /blob {
        limit_req zone=blobse_mod_blob burst=5 nodelay;
        proxy_pass http://0.0.0.0:7330/blob;
    }
}
```

Additionally, you might want to configure `https` through
[certbot](https://certbot.eff.org/) and enable
[maxmemory and eviction options](https://redis.io/topics/lru-cache#maxmemory-configuration-directive)
in Redis's config.
