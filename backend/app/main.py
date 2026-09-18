import logging, time, uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from .core.db import init_mongo
from .core.logging import setup_logging, request_id

def create_app() -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_mongo()
        from .core.config import settings
        from .modules.users import service
        await service.ensure_admin(
            login=settings.admin_login, password=settings.admin_password,
            full_name=settings.admin_name)
        yield

    app = FastAPI(title="School Hub", lifespan=lifespan)

    @app.middleware("http")
    async def rid_middleware(request: Request, call_next):
        request_id.set(uuid.uuid4().hex[:12])
        t = time.perf_counter()
        response = await call_next(request)
        logging.getLogger("api").info(
            "%s %s -> %s", request.method, request.url.path, response.status_code,
            extra={"duration_ms": round((time.perf_counter() - t) * 1000, 1)})
        return response

    from .modules.users.router import router as users_router
    app.include_router(users_router)
    from .modules.pulse.router import router as pulse_router
    app.include_router(pulse_router)
    from .modules.bridge.router import router as bridge_router
    app.include_router(bridge_router)
    from .modules.duty.router import router as duty_router
    app.include_router(duty_router)
    from .modules.navigator.router import router as navigator_router
    app.include_router(navigator_router)
    from .modules.builder.router import router as builder_router
    app.include_router(builder_router)
    from .modules.media.router import router as media_router
    app.include_router(media_router)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    return app

app = create_app()
