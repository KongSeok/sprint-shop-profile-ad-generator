from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.profile import router as profile_router
from app.api.routers.copy import router as copy_router
from app.api.routers.render import router as render_router
from app.services.shop_store import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Shop Profile Ad Generator", lifespan=lifespan)
app.include_router(profile_router)
app.include_router(copy_router)
app.include_router(render_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
