from fastapi import FastAPI

from app.api.routers.profile import router as profile_router

app = FastAPI(title="Shop Profile Ad Generator")
app.include_router(profile_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
