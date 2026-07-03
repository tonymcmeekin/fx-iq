from fastapi import FastAPI

from app.backtesting.router import router as backtesting_router
from app.decision.router import router as decision_router
from app.market_data.router import router as market_data_router
from app.risk.router import router as risk_router
from app.signals.router import router as signals_router
from app.strategies.router import router as strategy_router

app = FastAPI(title="FX IQ API", version="0.1.0")

app.include_router(market_data_router)
app.include_router(strategy_router)
app.include_router(signals_router)
app.include_router(risk_router)
app.include_router(decision_router)
app.include_router(backtesting_router)


@app.get("/")
def root():
    return {
        "message": "FX IQ backend is running",
        "status": "ok",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
    }
