from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from decimal import Decimal

class SPEIIncomingPayload(BaseModel):
    fecha_operacion: str = Field(..., description="Fecha de operación en formato YYYYMMDD o YYYY-MM-DD", example="20261008")
    clave_rastreo: str = Field(..., max_length=30, description="Clave de rastreo única generada por la institución emisora", example="BNK20261008000123")
    institucion_ordenante: str = Field(..., min_length=3, max_length=5, description="Clave de la institución participante emisora (ej. 40012)", example="40012")
    institucion_beneficiaria: str = Field(..., min_length=3, max_length=5, description="Clave de Bankaool (ej. 148 o 40148)", example="148")
    
    # Datos de las cuentas
    nombre_ordenante: str = Field(..., max_length=120, description="Nombre del titular de la cuenta ordenante")
    cuenta_ordenante: str = Field(..., min_length=10, max_length=18, description="CLABE, Tarjeta o Cuenta del ordenante")
    rfc_curp_ordenante: Optional[str] = Field(None, max_length=18, description="RFC o CURP del ordenante")
    
    nombre_beneficiario: str = Field(..., max_length=120, description="Nombre del titular en Bankaool")
    cuenta_beneficiaria: str = Field(..., min_length=18, max_length=18, description="CLABE Interbancaria Bankaool (18 dígitos)")
    rfc_curp_beneficiario: Optional[str] = Field(None, max_length=18, description="RFC o CURP del beneficiario")
    
    # Monto y Concepto
    monto: Decimal = Field(..., gt=0, decimal_places=2, description="Monto transferido en MXN", example=1500.50)
    iva: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2, description="Monto del IVA")
    concepto_pago: str = Field(..., max_length=40, description="Concepto de pago")
    referencia_numerica: Optional[int] = Field(None, ge=0, le=9999999, description="Referencia numérica de hasta 7 dígitos")
    
    # Firma y Seguridad
    sello: str = Field(..., description="Firma digital RSA-SHA256 codificada en Base64")
    certificado_numero_serie: Optional[str] = Field(None, description="Número de serie del certificado digital del emisor")

    @field_validator("cuenta_beneficiaria")
    def validate_clabe(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 18:
            raise ValueError("La cuenta beneficiaria debe ser una CLABE válida de 18 dígitos numéricos.")
        return v

    def build_cadena_original(self) -> str:
        """
        Construye la Cadena Original conforme a las normas técnicas de Banco de México (SPEI).
        Formato delimitado por barras verticales (piping '|').
        """
        campos = [
            str(self.fecha_operacion),
            str(self.clave_rastreo),
            str(self.institucion_ordenante),
            str(self.institucion_beneficiaria),
            str(self.cuenta_beneficiaria),
            f"{self.monto:.2f}",
            str(self.concepto_pago),
            str(self.referencia_numerica or "")
        ]
        return "||" + "|".join(campos) + "||"


class SPEIResponseStatus(BaseModel):
    estado: str = Field(..., example="LIQUIDADA") # LIQUIDADA, DEVUELTA, DUPLICADA, RECHAZADA
    clave_rastreo: str
    folio_abono_interno: Optional[str] = None
    codigo_respuesta: str = Field("0", example="0") # 0 = Aceptada/Liquidada
    mensaje: str = Field("Transferencia procesada exitosamente")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
