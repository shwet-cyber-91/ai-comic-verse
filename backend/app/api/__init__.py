"""HTTP layer: one router, mounted at ``/api`` by ``app.main``."""

from .routes import router

__all__ = ["router"]
