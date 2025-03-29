DJANGO_SETTINGS_MODULE=orgchart.settings.development
{{ range $key, $value := (key (printf "org-chart/%s" (slice (env "NOMAD_JOB_NAME") 10)) | parseJSON) -}}
{{- $key | trimSpace -}}={{- $value | toJSON }}
{{ end -}}
SENTRY_ENVIRONMENT={{ slice (env "NOMAD_JOB_NAME") 10 }}
