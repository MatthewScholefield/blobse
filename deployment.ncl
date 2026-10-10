let lib = import "libs/dockstride.ncl" in
fun options =>
let settings = options | {
  backend | lib.Backend,
  prod | Bool,
  serverUrl | String,
  redisHost | String,
  image | String,
  buildContext | String | default = ".",
} in
let dc = lib.forEnvironment settings in
{
  services."blobse-backend" = dc.Service {
    image = settings.image,
    build.context = settings.buildContext,
    expose = ["7330"],
    environment = dc.Env {
      SERVER_URL = settings.serverUrl,
      REDIS_HOST = settings.redisHost,
      DEBUG = !settings.prod,
    },
    healthcheck = {
      test = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7330/openapi.json', timeout=3)"],
      interval = "10s",
      timeout = "5s",
      retries = 5,
      start_period = "20s",
    },
    restart = "unless-stopped",
    deploy = {
      replicas = 1,
      restart_policy.condition = "on-failure",
    },
  } & (if settings.prod then {} else {
    develop.watch = [{
      action = "sync+restart",
      path = "%{settings.buildContext}/blobse",
      target = "/app/blobse",
    }],
  }),
}
