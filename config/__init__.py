"""IHMS project package.

The Celery app is imported lazily so Django always loads before Celery.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
