import uvicorn
import os
import sys

def run_api():
    import api
    print("Iniciando Servidor Web de Taquería Pro en http://localhost:8000")
    print(" - Caja Web: http://localhost:8000/cashier.html")
    print(" - Admin Web: http://localhost:8000/admin.html")
    print(" - Meseros Web: http://localhost:8000/waiter.html")
    uvicorn.run(api.app, host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    try:
        run_api()
    except KeyboardInterrupt:
        print("\nServidor apagado.")
