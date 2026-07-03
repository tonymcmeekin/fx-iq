from fastapi import FastAPI

app = FastAPI(title="FX IQ API", version="0.1.0")


@app.get("/")
def root():
    return {
        "message": "FX IQ backend is running",
        "status": "ok"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }
