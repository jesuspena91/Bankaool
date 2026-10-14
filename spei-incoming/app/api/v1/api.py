from fastapi import APIRouter
from app.api.v1.endpoints import spei

api_router = APIRouter()
api_router.include_router(spei.router, prefix="/spei", tags=["SPEI Incoming"])
