# Blobse

_Simple small blob store over HTTP_

This is a simple server with an API to store arbitrary data blobs API operating
anonymously over HTTP. This is useful for use in small client-side applications and
command-line tools that need temporary storage.

## API

By default, newly created blobs are private: anyone with the blob URL can read
one, but its edit key is required to modify or delete it. Capture the
`X-Edit-Key` response header when creating a blob. Keep edit keys in headers,
not URLs, and share them only over a secure channel.

```console
$ # Create a private blob and capture its edit key
$ curl -X POST https://blobse.us.to/blob/new -d myData -D -
HTTP/1.1 200 OK
X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000

https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931

$ # Read a blob (public)
$ curl -X GET https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931
myData

$ # Modify a private blob using its edit key
$ curl -X PUT https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 \
    -H "X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000" -d myNewData
$ curl -X GET https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931
myNewData

$ # Delete a private blob using its edit key
$ curl -X DELETE https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 \
    -H "X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000"
$ curl -X GET https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 -D -
HTTP/1.1 404 Not Found
{"detail":"Blob not found"}

$ # Opt out of private edits when creating a blob
$ curl -X POST https://blobse.us.to/blob/new -H "X-Edit-Key: public" -d publicData
https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931
$ # Create an append-only blob. The response includes the private owner key.
$ curl -X POST https://blobse.us.to/blob/new \
    -H "X-Blob-Mode: append-only" -d first-item -D -
HTTP/1.1 200 OK
X-Blob-Mode: append-only
X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000

https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931

$ # Anyone can append an arbitrary byte string without an edit key
$ curl -X POST https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/append \
     -d 'item containing newlines, separators, or binary data'

$ # The GET response is a sequence of 8-byte big-endian length-prefixed items.
$ # The owner can still replace the blob with PUT or delete it with DELETE.

$ # Create an append-only queue whose contents are readable only with its edit key
$ curl -X POST https://blobse.us.to/blob/new \
     -H "X-Blob-Mode: owner-readable-append-only" -d first-item -D -
HTTP/1.1 200 OK
X-Blob-Mode: owner-readable-append-only
X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000

$ # Anonymous writers can append, but anonymous reads are rejected
$ curl -X POST https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/append -d second-item
$ curl https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 -D -
HTTP/1.1 403 Forbidden

$ # The owner supplies the same key to consume the queue
$ curl https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 \
     -H "X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000"
```

Append-only blobs use length prefixes rather than a delimiter, so no escaping is
needed and every byte value is safe. Anonymous callers can only use `/append`;
all existing edit, lock, replace, and delete routes still require the owner's
`X-Edit-Key`. The `owner-readable-append-only` mode has the same append behavior,
but GET also requires the owner key. Keep that key secret: it authorizes reads as
well as replacement, locking, and deletion. Missing mode metadata retains the
legacy public-read behavior.



The API provides a safe locking mechanism for modifying blobs to prevent race conditions.  
Once a blob is locked, it **cannot be modified or deleted** unless using the lock key.
Private blobs require their edit key for every locking operation; locked updates
require both the edit key and lock key.

```console
$ # Lock a private blob and retrieve its contents
$ curl -X POST https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/lock \
    -H "X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000" -D -
HTTP/1.1 200 OK
X-Lock-Key: 123e4567-e89b-12d3-a456-426614174000

myData

$ # Modify the locked blob using both keys
$ curl -X PUT https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/locked-content \
    -H "X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000" \
    -H "X-Lock-Key: 123e4567-e89b-12d3-a456-426614174000" -d myUpdatedData

$ # Trying to modify a locked blob without a lock key fails
$ curl -X PUT https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931 \
    -H "X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000" -d unauthorizedData -D -
HTTP/1.1 423 Locked
{"detail":"Blob is locked"}

$ # Delete the lock manually using the edit key
$ curl -X DELETE https://blobse.us.to/blob/cfb77270-320c-4970-a759-c31a39c7b931/lock \
    -H "X-Edit-Key: 550e8400-e29b-41d4-a716-446655440000"
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

## Dockstride containers

Install Dockstride (`dks`) separately; Docker Engine and Compose 2.24+ are needed
when running containers. `compose.ncl` and the pinned `libs/dockstride.ncl` are
checked in; deployment tooling is not a Python application dependency.

Create an ignored `env.yaml` (separate from the `.env` used by direct Python runs):

```yaml
project: blobse-dev
```

`dks config schema --json` describes the small configuration contract:

- `project`: required unique lowercase project/stack name; do not reuse an
  existing deployment's name for testing.
- `prod`: defaults to `false`; selects Compose, debug/reload, source watch, and
  loopback port 7330. `true` selects Swarm, disables debug/watch and published
  ports, and requires explicit `serverUrl` and registry-qualified `image`.
- `backend`: derived from `prod`; an incompatible explicit value is rejected.
- `serverUrl`: public origin for generated links; local default is
  `http://localhost:7330`. Include `http://` or `https://`.
- `redisHost`: defaults to `redis`, creating private Redis on port 6379 with
  `--save 60 1` persistence in `blobse-redis-volume`. Any other hostname omits
  the bundled Redis/volume and connects to your existing server on port 6379.
- `image`: development default `blobse-backend:local`; production requires a
  registry tag accessible to all nodes. The Dockerfile build remains available
  in the canonical/build render for Dockstride's build/publish workflow.

Validate without starting containers:

```bash
dks render --target compose
dks render --target swarm
dks render --target build
SERVER_URL=http://localhost:7330 uv run --locked pytest -q
```

`--target` converts the Docker document, not the environment policy: a Swarm
render with `prod: false` is **not** production-safe. Validate production with
`prod: true` and explicit production inputs before rendering Swarm/build targets.

For development, `dks setup` fills missing configuration, `dks up` starts the
services, and `dks dev` also watches source changes. These lifecycle commands
are not required for rendering or tests. In production, supply `prod: true`,
`serverUrl`, and `image` in `env.yaml`; configure your registry, Swarm manager,
and reverse proxy before explicitly running `dks deploy`. The production service
exposes 7330 only on its Docker network; proxy/TLS configuration is external.

The bundled Redis is single-instance with a node-local volume constrained to
manager nodes. With multiple managers, pin it to a specific node or use external
Redis; moving it does not move its data. This does not adopt the parent's existing
`machazat-redis-volume`, migrate data, or provide high availability.

### Parent stack integration

Import `deployment.ncl`, not this checkout's `compose.ncl`. The exported function
returns only `services."blobse-backend"`; it does not read environment files,
create Redis/volumes, publish ports, or configure a proxy. For example, inside a
parent `dc.ComposeFile` (with the parent's own `dockstride.Config` metadata):

```nickel
let blobse = (import "blobse/deployment.ncl") {
  backend = env.backend,
  prod = env.prod,
  serverUrl = env.blobseUrl,
  redisHost = "redis",
  image = env.blobseImage,
  buildContext = "./blobse",
} in
blobse & {
  services."blobse-backend" = {
    networks = ["machazat-network"],
    # Add the parent's Docker-native proxy labels here.
  },
}
```

Build/watch paths are relative to the parent project; standalone defaults use
`.`. The parent owns the shared Redis, persistent volume, network, proxy labels,
and any Compose `depends_on` ordering. Swarm drops build/watch/dependencies from
runtime rendering. Keep the old parent Jsonnet/Compose definition until rendered
configuration and an explicitly authorized runtime/data cutover are verified;
this checkout does not modify it.

No deployment secrets are needed or declared. Do not put credentials in
`env.yaml`, `.env`, or checked-in definitions. If authentication is added later,
use Dockstride file-backed secret references and application-supported file
inputs; `_FILE` is not automatic Docker behavior. Local environment files,
Dockstride state, virtual environments and Git metadata are excluded from the
Docker build context.

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
