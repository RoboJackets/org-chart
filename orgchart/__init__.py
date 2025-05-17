from .celery import app as celery_app

__all__ = [celery_app]  # type: ignore  # pylint: disable=invalid-all-object
