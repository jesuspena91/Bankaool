import base64
import logging
from typing import Dict
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature
from cryptography.x509 import load_pem_x509_certificate

logger = logging.getLogger("spei.security")

class CryptoService:
    """
    Servicio de validación y gestión de firmas digitales PKI (RSA-SHA256)
    conforme a las directrices de SPEI / Banxico.
    """
    def __init__(self):
        # Cache local de certificados públicos X.509 de instituciones participantes
        self._certificates_cache: Dict[str, bytes] = {}

    def register_participant_certificate(self, institucion_id: str, cert_pem: bytes):
        """Registra o actualiza el certificado de un participante emisario."""
        self._certificates_cache[institucion_id] = cert_pem

    def verify_spei_signature(
        self,
        cadena_original: str,
        sello_base64: str,
        institucion_ordenante: str
    ) -> bool:
        """
        Valida que el sello digital corresponda a la cadena original generada
        por la institución ordenante utilizando su clave pública RSA.
        """
        try:
            cert_pem = self._certificates_cache.get(institucion_ordenante)
            if not cert_pem:
                logger.error(f"Certificado no encontrado para la institución: {institucion_ordenante}")
                return False

            cert = load_pem_x509_certificate(cert_pem)
            public_key = cert.public_key()

            if not isinstance(public_key, rsa.RSAPublicKey):
                logger.error("La clave pública no es del tipo RSA.")
                return False

            signature = base64.b64decode(sello_base64)
            data_bytes = cadena_original.encode("utf-8")

            # Verificación RSA con relleno PKCS#1 v1.5 y algoritmo SHA-256 (Norma SPEI)
            public_key.verify(
                signature,
                data_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True

        except InvalidSignature:
            logger.warning(f"Firma digital inválida para ordenante {institucion_ordenante}.")
            return False
        except Exception as e:
            logger.error(f"Error durante la validación de la firma: {str(e)}")
            return False

crypto_service = CryptoService()
