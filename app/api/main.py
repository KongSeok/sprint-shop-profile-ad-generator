from contextlib import asynccontextmanager
import logging
from time import perf_counter

from fastapi import FastAPI

from app.api.routers.profile import router as profile_router
from app.api.routers.copy import router as copy_router
from app.api.routers.render import router as render_router
from app.api.routers.image import router as image_router
from app.services.shop_store import init_db
from app.core import config
from app.services import image_models


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.background_model = None
    app.state.image_load_seconds = None
    if config.IMAGE_ENABLED:
        started = perf_counter()
        try:
            app.state.background_model = image_models.load_background_model(config.IMAGE_CPU_OFFLOAD)
        except Exception:
            logging.getLogger(__name__).exception("SD 1.5 모델을 불러오지 못했습니다")
        finally:
            app.state.image_load_seconds = perf_counter() - started
    try:
        yield
    finally:
        app.state.background_model = None


app = FastAPI(title="Shop Profile Ad Generator", lifespan=lifespan)
app.include_router(profile_router)
app.include_router(copy_router)
app.include_router(render_router)
app.include_router(image_router)


@app.get("/health")
def health():
    model = getattr(app.state, "background_model", None)
    return {
        "status": "ok", "image_enabled": config.IMAGE_ENABLED,
        "image_loaded": model is not None,
        "image_load_seconds": getattr(app.state, "image_load_seconds", None),
        "image_cpu_offload": getattr(model, "cpu_offload", None),
    }
