"""
Script de Empaquetado Seguro para Producción (Audit Finding A).
Genera un archivo ZIP limpio para despliegue, excluyendo estrictamente:
- Entornos virtuales (venv/, .venv/)
- Bases de datos locales (instance/, *.db, *.sqlite3)
- Archivos compilados y cachés (__pycache__/, *.pyc)
- Archivos de secretos locales (.env)
"""
import os
import zipfile
from pathlib import Path
from datetime import datetime

EXCLUDED_DIRS = {
    'venv', '.venv', 'env', 'ENV', '__pycache__', 'instance',
    '.git', '.vscode', '.idea', 'logs', 'releases', 'build', '.dart_tool'
}

EXCLUDED_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.db', '.sqlite', '.sqlite3',
    '.db-shm', '.db-wal', '.db-journal', '.log', '.pem', '.key', '.zip'
}

EXCLUDED_FILES = {
    '.env', '.env.local', '.DS_Store', 'Thumbs.db'
}


def should_exclude(rel_path_str: str) -> bool:
    """Determina si una ruta relativa debe ser excluida del paquete de producción."""
    norm_path = Path(rel_path_str.replace('\\', '/'))
    for part in norm_path.parts[:-1]:
        if part in EXCLUDED_DIRS:
            return True
    if norm_path.name in EXCLUDED_DIRS:
        return True
    if norm_path.name in EXCLUDED_FILES:
        return True
    if norm_path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True
    return False



def build_clean_package(project_root: Path, output_zip: Path) -> dict:
    included_files = []
    skipped_items = []

    output_zip.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_root):
            # Filtrar directorios prohibidos in-place para no recorrerlos
            removed_dirs = [d for d in dirs if d in EXCLUDED_DIRS]
            for d in removed_dirs:
                skipped_items.append(str(Path(root, d).relative_to(project_root)) + '/')
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(project_root)

                if file in EXCLUDED_FILES or file_path.suffix.lower() in EXCLUDED_EXTENSIONS:
                    skipped_items.append(str(rel_path))
                    continue

                zf.write(file_path, arcname=str(rel_path))
                included_files.append(str(rel_path))

    return {
        'output_zip': str(output_zip),
        'included_count': len(included_files),
        'skipped_count': len(skipped_items),
        'included_files': included_files
    }


if __name__ == '__main__':
    root_dir = Path(__file__).resolve().parent.parent
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target_zip = root_dir / 'releases' / f'josepo_prod_clean_{timestamp}.zip'
    report = build_clean_package(root_dir, target_zip)
    print(f"[OK] Paquete limpio generado en: {report['output_zip']}")
    print(f"     Archivos incluidos: {report['included_count']} | Artefactos excluidos: {report['skipped_count']}")
