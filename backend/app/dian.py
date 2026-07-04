import uuid
import datetime
import hashlib

def simulate_dian_invoice(order_data: dict, customer_data: dict):
    """
    Simula el proceso de emisión de una Factura Electrónica de Venta (FEV)
    ante la DIAN (Colombia).
    En producción, esto enviaría un XML firmado a un Proveedor Tecnológico.
    """
    
    # 1. Generar un CUFE Simulado (Código Único de Facturación Electrónica)
    # CUFE real is a SHA384 hash of invoice data + technical key
    raw_str = f"{order_data['id']}{customer_data['nit']}{order_data['total_cop']}{datetime.datetime.now().isoformat()}"
    cufe = hashlib.sha384(raw_str.encode()).hexdigest()
    
    # 2. Simular generación de QR
    qr_url = f"https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey={cufe}"
    
    # 3. Retornar los metadatos fiscales
    return {
        "status": "APPROVED",
        "cufe": cufe,
        "qr_url": qr_url,
        "issue_date": datetime.datetime.now().isoformat(),
        "invoice_number": f"FEV-{order_data['id'].zfill(6)}",
        "dian_message": "Procesado correctamente (Simulación)"
    }
