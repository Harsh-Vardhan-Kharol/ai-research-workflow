"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.connection import connect_database
from app.database.repository import initialize_schema
from app.api.errors import register_error_handlers
from app.api.routes.papers import router as papers_router

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Verify the local database is available when the API starts."""
    connection = connect_database(settings.database_path)
    try:
        initialize_schema(connection)
        connection.execute("SELECT 1").fetchone()
        logger.info(
            "APPLICATION_DATABASE_READY",
            extra={"database_path": str(settings.database_path)},
        )
        yield
    finally:
        connection.close()


app = FastAPI(title="ResearchFlow AI", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(papers_router)
