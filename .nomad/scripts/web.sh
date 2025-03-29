/app/manage.py migrate
exec /usr/local/bin/uwsgi --master --enable-threads --processes=4 --uwsgi-socket /var/opt/nomad/run/${NOMAD_JOB_NAME}-${NOMAD_ALLOC_ID}.sock --chmod-socket=777 --http-socket 127.0.0.1:${NOMAD_PORT_http} --chdir=/app/ --module=orgchart.wsgi:application --buffer-size=8192 --single-interpreter --lazy-apps --need-app
