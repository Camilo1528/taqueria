import multiprocessing
import uvicorn
import os
import sys

def run_api():
    import api
    # En producción uvicorn debe recibir el objeto directamente
    uvicorn.run(api.app, host="0.0.0.0", port=8000, log_level="info")

def run_gui():
    import main
    app = main.App()
    app.mainloop()

if __name__ == "__main__":
    multiprocessing.freeze_support() # Vital para compilar EXEs con múltiples procesos en Windows
    
    # Inicia el servidor de la Nube Local (Meseros y WebSockets) en segundo plano
    p_api = multiprocessing.Process(target=run_api)
    p_api.daemon = True
    p_api.start()
    
    # Inicia la Caja Registradora principal
    run_gui()
    
    # Al cerrar la caja, apaga el servidor
    p_api.terminate()
