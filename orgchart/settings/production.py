from .development import *  # pylint: disable=wildcard-import,unused-wildcard-import

# mypy: ignore-errors

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
DEBUG = False
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URI") + "?db=0",
        "OPTIONS": {
            "PASSWORD": os.environ.get("REDIS_PASSWORD"),
        },
    },
    "session": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URI") + "?db=1",
        "OPTIONS": {
            "PASSWORD": os.environ.get("REDIS_PASSWORD"),
        },
    },
}
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE"),
        "USER": os.environ.get("MYSQL_USER"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD"),
        "HOST": "127.0.0.1",
        "PORT": 3306,
    }
}
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "session"
