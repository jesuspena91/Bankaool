import logging
from typing import Dict, Any
from datetime import datetime
from app.core.config import settings
from app.schemas.spei import SPEIIncomingPayload

logger = logging.getLogger("spei.bigquery")

class BigQueryPersister:
    def __init__(self):
        self.project_id = settings.GCP_PROJECT_ID
        self.dataset_id = settings.BIGQUERY_DATASET
        self.table_id = settings.BIGQUERY_TABLE
        self._client = None

    def _get_client(self):
        if not self._client:
            try:
                from google.cloud import bigquery
                self._client = bigquery.Client(project=self.project_id)
            except Exception as e:
                logger.warning(f"BigQuery SDK Client no inicializado en entorno local: {e}")
        return self._client

    async def persist_transaction_async(self, payload: SPEIIncomingPayload, estado: str, folio_abono: str = None):
        """
        Inserta la transacción en Google BigQuery para trazabilidad y auditoría de Banxico.
        Diseñado para invocarse en BackgroundTasks sin impactar el SLA del webhook.
        """
        row: Dict[str, Any] = {
            "fecha_operacion": payload.fecha_operacion,
            "clave_rastreo": payload.clave_rastreo,
            "institucion_ordenante": payload.institucion_ordenante,
            "institucion_beneficiaria": payload.institucion_beneficiaria,
            "nombre_ordenante": payload.nombre_ordenante,
            "cuenta_ordenante": payload.cuenta_ordenante,
            "rfc_curp_ordenante": payload.rfc_curp_ordenante,
            "nombre_beneficiario": payload.nombre_beneficiario,
            "cuenta_beneficiaria": payload.cuenta_beneficiaria,
            "rfc_curp_beneficiario": payload.rfc_curp_beneficiario,
            "monto": float(payload.monto),
            "iva": float(payload.iva),
            "concepto_pago": payload.concepto_pago,
            "referencia_numerica": payload.referencia_numerica,
            "sello": payload.sello,
            "estado": estado,
            "folio_abono_interno": folio_abono,
            "fecha_recepcion_utc": datetime.utcnow().isoformat()
        }

        client = self._get_client()
        if client:
            try:
                table_ref = f"{self.project_id}.{self.dataset_id}.{self.table_id}"
                errors = client.insert_rows_json(table_ref, [row])
                if errors:
                    logger.error(f"Errores al insertar en BigQuery: {errors}")
                else:
                    logger.info(f"Transacción {payload.clave_rastreo} persistida con éxito en BigQuery.")
            except Exception as e:
                logger.error(f"Excepción persistiendo en BigQuery para {payload.clave_rastreo}: {e}")
        else:
            logger.info(f"[Mock BQ Log] Registro persistido en BigQuery ({payload.clave_rastreo}): {row['monto']} MXN -> {row['cuenta_beneficiaria']}")

bigquery_persister = BigQueryPersister()
