"""FastAPI application factory.

Responsibilities:
  - configure CORS
  - register the v1 API router
  - initialize the database on startup
  - expose a custom OpenAPI schema with a Bearer security scheme

Importing this module does NOT start the server. Run with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database when the app starts."""
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Options trading platform for OptionFlow.",
        lifespan=lifespan,
    )

    # CORS — allow the configured origins (defaults to all for dev).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount all v1 routes under /api/v1.
    app.include_router(api_router)

    # Root + health endpoints.
    @app.get("/", tags=["meta"])
    def root():
        return {"message": settings.APP_NAME}

    @app.get("/health", tags=["meta"])
    def health_check():
        return {"status": "ok", "service": "options-trading-platform"}

    # Custom OpenAPI schema with a Bearer security scheme so protected
    # endpoints render a lock icon in Swagger UI.
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=settings.APP_NAME,
            version=settings.APP_VERSION,
            description=app.description,
            routes=app.routes,
        )
        openapi_schema["components"]["securitySchemes"] = {
            "Bearer": {
                "type": "http",
                "scheme": "bearer",
                "description": "Enter your access token",
            }
        }
        for path in openapi_schema["paths"]:
            for method in openapi_schema["paths"][path]:
                if method in {"get", "post", "put", "delete"}:
                    # Mark every authenticated route with a Bearer lock icon
                    # in Swagger UI. Add new protected path prefixes here.
                    # The option-chain export endpoint is PUBLIC (no JWT) per
                    # the team-lead's directive, so we exclude it from the
                    # Bearer lock — even though it lives under /market-data/.
                    is_option_chain = "/option-chain/export" in path
                    if not is_option_chain and any(
                        protected_prefix in path
                        for protected_prefix in ("/users/me", "/market-data/")
                    ):
                        openapi_schema["paths"][path][method]["security"] = [
                            {"Bearer": []}
                        ]
        app.openapi_schema = openapi_schema
        return openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()
