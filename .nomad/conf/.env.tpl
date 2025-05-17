DJANGO_SETTINGS_MODULE=orgchart.settings.development
{{ range $key, $value := (key (printf "org-chart/%s" (slice (env "NOMAD_JOB_NAME") 10)) | parseJSON) -}}
{{- $key | trimSpace -}}={{- $value | toJSON }}
{{ end -}}
SENTRY_ENVIRONMENT={{ slice (env "NOMAD_JOB_NAME") 10 }}
REDIS_URI=unix:///alloc/tmp/redis.sock
REDIS_PASSWORD={{ env "NOMAD_ALLOC_ID" }}
CELERY_BROKER_URL=redis+socket://:{{ env "NOMAD_ALLOC_ID" }}@/alloc/tmp/redis.sock?virtual_host=2
CELERY_RESULT_BACKEND=redis+socket://:{{ env "NOMAD_ALLOC_ID" }}@/alloc/tmp/redis.sock?virtual_host=3
