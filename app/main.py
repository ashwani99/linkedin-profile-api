"""
App entrypoint: FastAPI instance, router registration, exception handlers,
and the lifespan hook that closes VoyagerClient's curl_cffi AsyncSession
cleanly on shutdown.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth, health, profile
from app.exceptions import register_exception_handlers
from app.linkedin.voyager_client import voyager_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await voyager_client.aclose()


app = FastAPI(
    title="LinkedIn Profile API",
    description="Accepts a LinkedIn profile URL and returns structured profile data.",
    version="0.1.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(profile.router)