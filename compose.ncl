let lib = import "libs/dockstride.ncl" in
let deployment = import "deployment.ncl" in
let inputs = {
  prod | Bool | doc "Enable production defaults and Swarm; false selects local Compose development." | default = false,
} in
let selected = inputs & (import "env.yaml") in
let cfg = inputs & {
  project | String | doc "Unique lowercase Compose project or Swarm stack name; use a distinct name for verification.",
  redisHost | String | doc "Redis hostname on port 6379; redis creates private persistent Redis, otherwise use an existing reachable server." | default = "redis",
} & (if selected.prod then {
  backend | lib.Choice ["swarm"] | doc "Runtime fixed to Swarm by prod=true." | default = "swarm",
  serverUrl | String | doc "Public HTTP(S) origin used for generated blob links; production requires an explicit origin.",
  image | String | doc "Registry-qualified blobse image tag reachable by every Swarm node; built from this checkout during deployment.",
} else {
  backend | lib.Choice ["compose"] | doc "Runtime fixed to Compose by prod=false." | default = "compose",
  serverUrl | String | doc "Origin used for generated blob links; defaults to the loopback development endpoint." | default = "http://localhost:7330",
  image | String | doc "Local blobse build tag; use a registry-qualified tag for production." | default = "blobse-backend:local",
}) in
let env | cfg = import "env.yaml" in
let dc = lib.forEnvironment env in
let app = deployment {
  backend = env.backend,
  prod = env.prod,
  serverUrl = env.serverUrl,
  redisHost = env.redisHost,
  image = env.image,
} in
dc.ComposeFile (app & {
  name = env.project,
  dockstride | not_exported = {
    Config = cfg,
    endpoints.api = env.serverUrl,
  },
  services."blobse-backend" =
    (if env.prod then {} else { ports = ["127.0.0.1:7330:7330"] }) &
    (if !env.prod && env.redisHost == "redis" then {
      depends_on.redis.condition = "service_healthy",
    } else {}),
} & (if env.redisHost == "redis" then {
  services.redis = dc.Service {
    image = "redis:7.4-alpine",
    expose = ["6379"],
    command = ["redis-server", "--save", "60", "1", "--loglevel", "warning"],
    volumes = ["blobse-redis-volume:/data"],
    healthcheck = {
      test = ["CMD", "redis-cli", "ping"],
      interval = "10s",
      timeout = "5s",
      retries = 5,
      start_period = "10s",
    },
    restart = "unless-stopped",
    deploy = {
      replicas = 1,
      restart_policy.condition = "on-failure",
    } & (if env.prod then {
      placement.constraints = ["node.role == manager"],
    } else {}),
  },
  volumes."blobse-redis-volume" = {},
} else {}))
