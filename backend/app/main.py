import logging, time, uuid
from fastapi import FastAPI, Request
from .core.logging import setup_logging, request_id

def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="School Hub")

    @app.middleware("http")
    async def rid_middleware(request: Request, call_next):
        request_id.set(uuid.uuid4().hex[:12])
        t = time.perf_counter()
        response = await call_next(request)
        logging.getLogger("api").info(
            "%s %s -> %s in %.1fms", request.method, request.url.path,
            response.status_code, (time.perf_counter() - t) * 1000)
        return response

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    return app

app = create_app()
