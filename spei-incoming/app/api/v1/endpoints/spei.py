import base64
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from app.schemas.spei import SPEIIncomingPayload, SPEIResponseStatus
from app.services.spei_service import spei_service
from app.db.redis import redis_client
from app.core.security import crypto_service

router = APIRouter()

class RegisterCertRequest(BaseModel):
    institucion_id: str = Field(..., description="Clave de la institución participante (ej. 40012)")
    cert_pem_base64: str = Field(..., description="Certificado X.509 en formato PEM codificado en Base64")

@router.post(
    "/incoming",
    response_model=SPEIResponseStatus,
    status_code=status.HTTP_200_OK,
    summary="Procesar transferencia SPEI entrante",
    description="Recibe una transferencia SPEI, valida su firma criptográfica, aplica idempotencia y abona al cliente."
)
async def process_incoming_spei(
    payload: SPEIIncomingPayload,
    background_tasks: BackgroundTasks
):
    """
    Procesa la transferencia SPEI entrante siguiendo la normativa de Banco de México:
    - Validación de firma digital RSA-SHA256 con certificado de la institución ordenante.
    - Idempotencia temporal en Redis para evitar duplicidad de abono.
    - Validación de CLABE y acreditación en la cuenta del beneficiario en Bankaool.
    - Ingesta asíncrona de datos en Google BigQuery para auditoría regulatoria.
    """
    response = await spei_service.process_incoming_transfer(payload, background_tasks)
    return response

@router.get(
    "/status/{clave_rastreo}",
    summary="Consultar estado de transferencia en Redis",
    description="Recupera el estado actual en caché de una clave de rastreo (PROCESSING, LIQUIDADA, DEVUELTA, RECHAZADA)"
)
async def get_transfer_status(clave_rastreo: str):
    state = await redis_client.get_transaction_state(clave_rastreo)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clave de rastreo {clave_rastreo} no encontrada en la ventana de operaciones recientes."
        )
    return {
        "clave_rastreo": clave_rastreo,
        "estado": state
    }

@router.post(
    "/certificates/register",
    status_code=status.HTTP_200_OK,
    summary="Registrar certificado X.509 de participante",
    description="Registra la clave pública de un participante del SPEI para verificar sus sellos digitales."
)
async def register_certificate(req: RegisterCertRequest):
    try:
        cert_bytes = base64.b64decode(req.cert_pem_base64)
        crypto_service.register_participant_certificate(req.institucion_id, cert_bytes)
        return {
            "institucion_id": req.institucion_id,
            "status": "Certificado registrado exitosamente para verificación de firmas."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error al decodificar o cargar el certificado: {str(e)}"
        )
