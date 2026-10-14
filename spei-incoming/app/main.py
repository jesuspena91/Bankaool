import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.api import api_router
from app.db.redis import redis_client

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("spei.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Conexión con Redis y precarga de recursos
    logger.info("Iniciando servicio de SPEI Entrante Bankaool...")
    await redis_client.connect()
    yield
    # Shutdown: Cierre ordenado de conexiones
    logger.info("Cerrando conexiones del servicio SPEI Entrante...")
    await redis_client.close()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
    description="Microservicio de alta disponibilidad para el procesamiento y acreditación de transferencias SPEI entrantes en Bankaool."
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Healthchecks
@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check():
    """Liveness probe para Kubernetes / Cloud Run."""
    return {"status": "healthy", "service": settings.PROJECT_NAME}

@app.get("/readyz", status_code=status.HTTP_200_OK, tags=["Health"])
async def readiness_check():
    """Readiness probe verificando conectividad a Redis."""
    redis_ready = False
    if redis_client.client:
        try:
            await redis_client.client.ping()
            redis_ready = True
        except Exception:
            redis_ready = False

    return {
        "status": "ready" if redis_ready else "degraded",
        "redis_connected": redis_ready,
        "institution_id": settings.BANKAOOL_INSTITUTION_ID
    }

# Montar rutas de API v1
app.include_router(api_router, prefix=settings.API_V1_STR)
