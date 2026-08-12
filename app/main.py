import logging
import os
import sys

import uvicorn
from fastapi import FastAPI

from api.health import router as health_router
from api.scale import router as scale_router
from core.config import load_kubernetes_config
from core.middleware import HandleExceptionsMiddleware

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)8s] %(message)s (%(filename)s:%(lineno)s)",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Snipod",
    description="Slim API to scale down a specific pod by name",
    version="0.1.0",
)

app.state.namespace = load_kubernetes_config()
app.include_router(health_router)
app.include_router(scale_router)
app.add_middleware(HandleExceptionsMiddleware)


def main():
    port = int(os.getenv("SNIPOD_PORT", "8080"))
    logger.info(f"Starting snipod on port {port}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
