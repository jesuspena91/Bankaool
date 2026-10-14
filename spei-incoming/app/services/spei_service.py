import logging
import uuid
from typing import Optional
from fastapi import BackgroundTasks
from app.schemas.spei import SPEIIncomingPayload, SPEIResponseStatus
from app.core.config import settings
from app.core.security import crypto_service
from app.db.redis import redis_client
from app.db.bigquery import bigquery_persister

logger = logging.getLogger("spei.service")

class SPEIProcessingService:
    """
    Servicio orquestador del procesamiento de transferencias SPEI entrantes en Bankaool.
    Maneja validación criptográfica, idempotencia con Redis, liquidación contable y persistencia en BigQuery.
    """

    async def process_incoming_transfer(
        self,
        payload: SPEIIncomingPayload,
        background_tasks: BackgroundTasks
    ) -> SPEIResponseStatus:
        logger.info(f"Iniciando procesamiento de SPEI entrante: {payload.clave_rastreo} por ${payload.monto}")

        # 1. Validación de Firma Criptográfica (PKI Banxico)
        if settings.ENFORCE_SIGNATURE_VERIFICATION:
            cadena_original = payload.build_cadena_original()
            is_valid = crypto_service.verify_spei_signature(
                cadena_original=cadena_original,
                sello_base64=payload.sello,
                institucion_ordenante=payload.institucion_ordenante
            )

            if not is_valid:
                logger.warning(f"Rechazo SPEI por firma inválida. Clave: {payload.clave_rastreo}")
                background_tasks.add_task(
                    bigquery_persister.persist_transaction_async,
                    payload,
                    "RECHAZADA",
                    None
                )
                return SPEIResponseStatus(
                    estado="RECHAZADA",
                    clave_rastreo=payload.clave_rastreo,
                    codigo_respuesta="13",
                    mensaje="Firma digital RSA-SHA256 no válida o certificado emisor no registrado"
                )

        # 2. Control de Idempotencia y Prevención de Doble Abono (Redis)
        lock_acquired = await redis_client.check_and_lock_idempotency(payload.clave_rastreo)
        if not lock_acquired:
            current_state = await redis_client.get_transaction_state(payload.clave_rastreo) or "DESCONOCIDO"
            logger.warning(f"Intento de duplicidad detectado para clave {payload.clave_rastreo} (estado actual: {current_state})")
            return SPEIResponseStatus(
                estado="DUPLICADA",
                clave_rastreo=payload.clave_rastreo,
                codigo_respuesta="10",
                mensaje=f"Transferencia previamente recibida y registrada con estado: {current_state}"
            )

        # 3. Validación de la Cuenta Beneficiaria en Bankaool (Código 148)
        # Una CLABE de Bankaool debe iniciar con los dígitos de institución 148
        if not payload.cuenta_beneficiaria.startswith("148"):
            logger.warning(f"CLABE {payload.cuenta_beneficiaria} no corresponde a la institución Bankaool (148)")
            await redis_client.set_transaction_state(payload.clave_rastreo, "DEVUELTA")
            background_tasks.add_task(
                bigquery_persister.persist_transaction_async,
                payload,
                "DEVUELTA",
                None
            )
            return SPEIResponseStatus(
                estado="DEVUELTA",
                clave_rastreo=payload.clave_rastreo,
                codigo_respuesta="1",
                mensaje="La cuenta receptora no pertenece al catálogo de cuentas Bankaool"
            )

        # Simulación de validación de estatus de cuenta en Core Bancario
        # Por ejemplo, si la cuenta termina en '00000', se considera cuenta inactiva o bloqueada por PLD
        if payload.cuenta_beneficiaria.endswith("00000"):
            logger.warning(f"Cuenta beneficiaria bloqueada/inactiva en Core Bancario: {payload.cuenta_beneficiaria}")
            await redis_client.set_transaction_state(payload.clave_rastreo, "DEVUELTA")
            background_tasks.add_task(
                bigquery_persister.persist_transaction_async,
                payload,
                "DEVUELTA",
                None
            )
            return SPEIResponseStatus(
                estado="DEVUELTA",
                clave_rastreo=payload.clave_rastreo,
                codigo_respuesta="2",
                mensaje="Cuenta beneficiaria cancelada, bloqueada o inactiva en Bankaool"
            )

        # 4. Liquidación Contable y Abono en Core Banking
        folio_abono = f"BNK-AB-{uuid.uuid4().hex[:10].upper()}"
        logger.info(f"Abono exitoso en Core Bancario. Folio generado: {folio_abono}")

        # 5. Actualización de estado en Redis
        await redis_client.set_transaction_state(payload.clave_rastreo, "LIQUIDADA")

        # 6. Despacho Asíncrono a BigQuery para trazabilidad y comprobante CEP
        background_tasks.add_task(
            bigquery_persister.persist_transaction_async,
            payload,
            "LIQUIDADA",
            folio_abono
        )

        return SPEIResponseStatus(
            estado="LIQUIDADA",
            clave_rastreo=payload.clave_rastreo,
            folio_abono_interno=folio_abono,
            codigo_respuesta="0",
            mensaje="Transferencia SPEI liquidada y abonada exitosamente en Bankaool"
        )

spei_service = SPEIProcessingService()
