from fastapi import FastAPI

app = FastAPI(title="Shop Profile Ad Generator")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
