from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.emails import router as emails_router
from app.api.threads import router as threads_router
from app.config import Settings, get_settings


def create_app() -> FastAPI:
    startup_settings = get_settings()
    app = FastAPI(title=startup_settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=startup_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(emails_router)
    app.include_router(threads_router)

    @app.get("/")
    def root(settings: Settings = Depends(get_settings)) -> dict[str, str]:
        return {"message": f"{settings.app_name} backend is running."}

    @app.get("/health")
    def health(settings: Settings = Depends(get_settings)) -> dict[str, str | bool]:
        return {
            "status": "ok",
            "email_configured": settings.imap_is_configured(),
        }

    return app


app = create_app()
