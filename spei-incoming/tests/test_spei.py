import base64
import datetime
import pytest
from decimal import Decimal
from httpx import AsyncClient, ASGITransport
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.x509.oid import NameOID

from app.main import app
from app.core.security import crypto_service
from app.db.redis import redis_client
from app.schemas.spei import SPEIIncomingPayload

# Fixture para generar un par de llaves RSA y un Certificado X.509 válido de prueba
@pytest.fixture(scope="session")
def test_pki():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Institucion Emisora 40012"),
        x509.NameAttribute(NameOID.COMMON_NAME, "SPEI Gateway 40012"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
    ).sign(private_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return private_key, cert_pem

def sign_data(private_key, data: str) -> str:
    """Firma los datos con RSA-SHA256 y PKCS#1 v1.5 conforme a Banxico."""
    signature = private_key.sign(
        data.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode("utf-8")

@pytest.mark.asyncio
async def test_cadena_original_building():
    payload = SPEIIncomingPayload(
        fecha_operacion="20261014",
        clave_rastreo="BNK202610140001",
        institucion_ordenante="40012",
        institucion_beneficiaria="148",
        nombre_ordenante="Juan Perez",
        cuenta_ordenante="012180001234567890",
        nombre_beneficiario="Maria Lopez",
        cuenta_beneficiaria="148180001234567890",
        monto=Decimal("2500.50"),
        concepto_pago="Pago de Servicios",
        referencia_numerica=123456,
        sello="dummy"
    )
    cadena = payload.build_cadena_original()
    assert cadena == "||20261014|BNK202610140001|40012|148|148180001234567890|2500.50|Pago de Servicios|123456||"

@pytest.mark.asyncio
async def test_crypto_signature_verification(test_pki):
    private_key, cert_pem = test_pki
    institucion_id = "40012"
    crypto_service.register_participant_certificate(institucion_id, cert_pem)

    data = "||20261014|BNK999|40012|148|148180001234567890|100.00|Prueba|1||"
    valid_signature = sign_data(private_key, data)

    # 1. Verificación exitosa
    assert crypto_service.verify_spei_signature(data, valid_signature, institucion_id) is True

    # 2. Verificación fallida por datos alterados (tampering)
    tampered_data = "||20261014|BNK999|40012|148|148180001234567890|99999.00|Prueba|1||"
    assert crypto_service.verify_spei_signature(tampered_data, valid_signature, institucion_id) is False

@pytest.mark.asyncio
async def test_successful_spei_incoming(test_pki):
    private_key, cert_pem = test_pki
    institucion_id = "40012"
    crypto_service.register_participant_certificate(institucion_id, cert_pem)

    payload_dict = {
        "fecha_operacion": "20261014",
        "clave_rastreo": "BNK_TEST_SUCCESS_01",
        "institucion_ordenante": institucion_id,
        "institucion_beneficiaria": "148",
        "nombre_ordenante": "Carlos Slim",
        "cuenta_ordenante": "012180009876543210",
        "nombre_beneficiario": "Bankaool Cliente",
        "cuenta_beneficiaria": "148180009876543210",
        "monto": "1500.00",
        "iva": "0.00",
        "concepto_pago": "Deposito Quincenal",
        "referencia_numerica": 88291,
        "sello": "PENDING"
    }

    # Construir cadena y firmar
    temp_payload = SPEIIncomingPayload(**payload_dict)
    cadena = temp_payload.build_cadena_original()
    sello = sign_data(private_key, cadena)
    payload_dict["sello"] = sello

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/v1/spei/incoming", json=payload_dict)
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] == "LIQUIDADA"
        assert data["codigo_respuesta"] == "0"
        assert data["clave_rastreo"] == "BNK_TEST_SUCCESS_01"
        assert data["folio_abono_interno"].startswith("BNK-AB-")

@pytest.mark.asyncio
async def test_idempotency_duplicate_transfer(test_pki):
    private_key, cert_pem = test_pki
    institucion_id = "40012"
    crypto_service.register_participant_certificate(institucion_id, cert_pem)

    payload_dict = {
        "fecha_operacion": "20261014",
        "clave_rastreo": "BNK_TEST_IDEMPOTENCY_01",
        "institucion_ordenante": institucion_id,
        "institucion_beneficiaria": "148",
        "nombre_ordenante": "Ana Sofia",
        "cuenta_ordenante": "012180009876543210",
        "nombre_beneficiario": "Bankaool Usuario",
        "cuenta_beneficiaria": "148180009876543210",
        "monto": "200.00",
        "concepto_pago": "Tacos",
        "sello": "PENDING"
    }

    temp_payload = SPEIIncomingPayload(**payload_dict)
    cadena = temp_payload.build_cadena_original()
    sello = sign_data(private_key, cadena)
    payload_dict["sello"] = sello

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Primer envío -> LIQUIDADA
        res1 = await ac.post("/v1/spei/incoming", json=payload_dict)
        assert res1.status_code == 200
        assert res1.json()["estado"] == "LIQUIDADA"

        # Segundo envío idéntico -> DUPLICADA
        res2 = await ac.post("/v1/spei/incoming", json=payload_dict)
        assert res2.status_code == 200
        assert res2.json()["estado"] == "DUPLICADA"
        assert res2.json()["codigo_respuesta"] == "10"

@pytest.mark.asyncio
async def test_invalid_signature_rejected(test_pki):
    _, cert_pem = test_pki
    institucion_id = "40012"
    crypto_service.register_participant_certificate(institucion_id, cert_pem)

    payload_dict = {
        "fecha_operacion": "20261014",
        "clave_rastreo": "BNK_TEST_FAKE_SIGNATURE",
        "institucion_ordenante": institucion_id,
        "institucion_beneficiaria": "148",
        "nombre_ordenante": "Hacker",
        "cuenta_ordenante": "012180009876543210",
        "nombre_beneficiario": "Bankaool Usuario",
        "cuenta_beneficiaria": "148180009876543210",
        "monto": "1000000.00",
        "concepto_pago": "Fake transfer",
        "sello": base64.b64encode(b"invalid_signature_bytes_here").decode("utf-8")
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/v1/spei/incoming", json=payload_dict)
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] == "RECHAZADA"
        assert data["codigo_respuesta"] == "13"

@pytest.mark.asyncio
async def test_account_not_bankaool(test_pki):
    private_key, cert_pem = test_pki
    institucion_id = "40012"
    crypto_service.register_participant_certificate(institucion_id, cert_pem)

    # CLABE que inicia con 012 (BBVA) en vez de 148 (Bankaool)
    payload_dict = {
        "fecha_operacion": "20261014",
        "clave_rastreo": "BNK_TEST_WRONG_CLABE",
        "institucion_ordenante": institucion_id,
        "institucion_beneficiaria": "148",
        "nombre_ordenante": "Emisor",
        "cuenta_ordenante": "012180009876543210",
        "nombre_beneficiario": "Beneficiario",
        "cuenta_beneficiaria": "012180009876543210",
        "monto": "350.00",
        "concepto_pago": "Prueba",
        "sello": "PENDING"
    }

    temp_payload = SPEIIncomingPayload(**payload_dict)
    cadena = temp_payload.build_cadena_original()
    sello = sign_data(private_key, cadena)
    payload_dict["sello"] = sello

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/v1/spei/incoming", json=payload_dict)
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] == "DEVUELTA"
        assert data["codigo_respuesta"] == "1"

@pytest.mark.asyncio
async def test_health_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res_h = await ac.get("/healthz")
        assert res_h.status_code == 200
        assert res_h.json()["status"] == "healthy"

        res_r = await ac.get("/readyz")
        assert res_r.status_code == 200
        assert "institution_id" in res_r.json()
