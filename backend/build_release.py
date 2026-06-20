import os
import sys
import subprocess
import zipfile

def build_local_exe():
    print("Iniciando compilación del EXE Local...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "TaqueriaPro",
        "--onedir",
        "--windowed",
        "--add-data", f"../frontend{os.pathsep}frontend",
        "--add-data", f"branding.json{os.pathsep}.",
        "--add-data", f"taqueria.db{os.pathsep}.",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "run_all.py"
    ]
    subprocess.run(cmd)
    print("Compilación EXE finalizada. Revisa la carpeta backend/dist/TaqueriaPro/")

def build_web_zip():
    print("Empaquetando versión WEB Nube...")
    zip_path = os.path.join(os.path.dirname(__file__), "..", "TaqueriaPro_Cloud.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        base_dir = os.path.join(os.path.dirname(__file__), "..")
        
        for folder in ["backend", "frontend"]:
            folder_path = os.path.join(base_dir, folder)
            for root, dirs, files in os.walk(folder_path):
                # Ignorar carpetas basura
                dirs[:] = [d for d in dirs if d not in ["venv", "__pycache__", "dist", "build", ".pytest_cache", "qrs", "tickets"]]
                for file in files:
                    if file.endswith(('.pyc', '.exe')): continue
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, base_dir)
                    zipf.write(abs_path, rel_path)
    print(f"Paquete WEB creado en la raíz del proyecto: {zip_path}")

if __name__ == "__main__":
    build_web_zip()
    build_local_exe()
