variable "image" {
  type = string
  description = "The image to use for running the service"
}

variable "hostname" {
  type = string
  description = "The hostname for this instance of the service"
}

locals {
  # compressed in this context refers to the config string itself, not the assets
  compressed_nginx_configuration = trimspace(
    trimsuffix(
      trimspace(
        regex_replace(
          regex_replace(
            regex_replace(
              regex_replace(
                regex_replace(
                  regex_replace(
                    regex_replace(
                      regex_replace(
                        trimspace(
                          file("conf/nginx.conf")
                        ),
                        "server\\s{\\s",      # remove server keyword and opening bracket (autogenerated in nginx nomad job)
                        ""
                      ),
                      "server_name\\s\\S+;",  # remove server_name directive (autogenerated in nginx nomad job)
                      ""
                    ),
                    "root\\s\\S+;",           # remove root directive (autogenerated in nginx nomad job)
                    ""
                  ),
                  "listen\\s.+;",             # remove listen directive  (autogenerated in nginx nomad job)
                  ""
                ),
                "#.+\\n",                     # remove comments (no semantic difference)
                ""
              ),
              ";\\s+",                        # remove whitespace after semicolons (no semantic difference)
              ";"
            ),
            "{\\s+",                          # remove whitespace after opening brackets (no semantic difference)
            "{"
          ),
          "\\s+",                             # replace any occurrence of one or more whitespace characters with single space (no semantic difference)
          " "
        )
      ),
      "}"                                     # remove trailing closing bracket (autogenerated in nginx nomad job)
    )
  )
}

job "org-chart" {
  region = "campus"

  datacenters = ["bcdc"]

  type = "service"

  group "org-chart" {
    network {
      port "http" {}

      port "resp" {}
    }

    volume "run" {
      type = "host"
      source = "run"
    }

    task "prestart" {
      driver = "docker"

      lifecycle {
        hook = "prestart"
      }

      config {
        image = var.image

        network_mode = "host"

        entrypoint = [
          "/bin/bash",
          "-xeuo",
          "pipefail",
          "-c",
          trimspace(file("scripts/prestart.sh"))
        ]

        mount {
          type = "volume"
          target = "/assets/"
          source = "assets"
          readonly = false

          volume_options {
            no_copy = true
          }
        }
      }

      resources {
        cpu = 100
        memory = 128
        memory_max = 2048
      }
    }

    task "web" {
      driver = "docker"

      config {
        image = var.image

        network_mode = "host"

        entrypoint = [
          "/usr/local/bin/uwsgi",
          "--master",
          "--enable-threads",
          "--processes=4",
          "--uwsgi-socket",
          "/var/opt/nomad/run/${NOMAD_JOB_NAME}-${NOMAD_ALLOC_ID}.sock",
          "--chmod-socket=777",
          "--http-socket",
          "0.0.0.0:${NOMAD_PORT_http}",
          "--chdir=/app/",
          "--module=orgchart.wsgi:application",
          "--buffer-size=8192",
          "--single-interpreter",
          "--lazy-apps",
          "--need-app",
        ]
      }

      resources {
        cpu = 100
        memory = 256
        memory_max = 2048
      }

      volume_mount {
        volume = "run"
        destination = "/var/opt/nomad/run/"
      }

      template {
        data = trimspace(file("conf/.env.tpl"))

        destination = "/secrets/.env"
        env = true
      }

      template {
        data = "SENTRY_RELEASE=\"${split("@", var.image)[1]}\""

        destination = "/secrets/.sentry_release"
        env = true
      }

      service {
        name = "${NOMAD_JOB_NAME}"

        port = "http"

        tags = [
          "uwsgi",
          "http",
        ]

        check {
          success_before_passing = 3
          failures_before_critical = 2

          interval = "5s"

          name = "GET /ping"
          path = "/ping"
          port = "http"
          protocol = "http"
          timeout = "1s"
          type = "http"
          header {
            Host = [var.hostname]
          }
        }

        check_restart {
          limit = 5
          grace = "20s"
        }

        meta {
          nginx-config = local.compressed_nginx_configuration
          socket = "/var/opt/nomad/run/${NOMAD_JOB_NAME}-${NOMAD_ALLOC_ID}.sock"
          firewall-rules = jsonencode(["internet"])
          referrer-policy = "no-referrer"
        }
      }

      restart {
        attempts = 1
        delay = "10s"
        interval = "1m"
        mode = "fail"
      }

      shutdown_delay = "30s"
    }

    task "redis" {
      driver = "docker"

      lifecycle {
        hook = "prestart"
        sidecar = true
      }

      config {
        image = "redis"

        args = [
          "/usr/local/etc/redis/redis.conf"
        ]

        force_pull = true

        network_mode = "host"

        mount {
          type   = "bind"
          source = "secrets/"
          target = "/usr/local/etc/redis/"
        }
      }

      resources {
        cpu = 100
        memory = 256
        memory_max = 2048
      }

      template {
        data = <<EOH
bind 127.0.0.1
port {{ env "NOMAD_PORT_resp" }}
unixsocket /alloc/tmp/redis.sock
unixsocketperm 777
requirepass {{ env "NOMAD_ALLOC_ID" }}
maxmemory {{ env "NOMAD_MEMORY_MAX_LIMIT" }}mb
maxmemory-policy allkeys-lru
EOH

        destination = "secrets/redis.conf"
      }

      service {
        name = "${NOMAD_JOB_NAME}-redis"

        port = "resp"

        address = "127.0.0.1"

        tags = [
          "resp"
        ]

        check {
          success_before_passing = 3
          failures_before_critical = 2

          interval = "5s"

          name = "TCP"
          port = "resp"
          timeout = "1s"
          type = "tcp"
        }

        check_restart {
          limit = 5
          grace = "20s"
        }
      }

      restart {
        attempts = 5
        delay = "10s"
        interval = "1m"
        mode = "fail"
      }

      shutdown_delay = "60s"
    }
  }

  reschedule {
    delay = "10s"
    delay_function = "fibonacci"
    max_delay = "60s"
    unlimited = true
  }

  update {
    healthy_deadline = "5m"
    progress_deadline = "10m"
    auto_revert = true
    auto_promote = true
    canary = 1
  }
}
