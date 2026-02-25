import argparse
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def _decrypt_file(input_path: Path, output_path: Path) -> None:
    key = settings.BACKUP_ENCRYPTION_KEY.strip()
    if not key:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY is required for restore")
    fernet = Fernet(key.encode("utf-8"))
    payload = input_path.read_bytes()
    output_path.write_bytes(fernet.decrypt(payload))


def _restore_sqlite(dump_file: Path, db_url: str) -> None:
    dst = Path(db_url.replace("sqlite:///", "", 1)).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dump_file, dst)


def _restore_postgres(dump_file: Path, db_url: str) -> None:
    cmd = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--dbname",
        db_url,
        str(dump_file),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore encrypted PITR backup")
    parser.add_argument("--backup-file", required=True, help="Path to .enc backup file")
    parser.add_argument("--work-dir", default=str(ROOT / "backups" / "restore_tmp"))
    args = parser.parse_args()

    backup_file = Path(args.backup_file).resolve()
    if not backup_file.exists():
        raise RuntimeError(f"Backup file not found: {backup_file}")

    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    archive_path = work_dir / "restore.tar.gz"
    _decrypt_file(backup_file, archive_path)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=work_dir)

    db_url = settings.DATABASE_URL.strip()
    if db_url.startswith("sqlite:///"):
        dump_file = work_dir / "database.sqlite3"
        if not dump_file.exists():
            raise RuntimeError("SQLite dump payload not found in archive")
        _restore_sqlite(dump_file, db_url)
    elif db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        dump_file = work_dir / "database.pg.dump"
        if not dump_file.exists():
            raise RuntimeError("Postgres dump payload not found in archive")
        _restore_postgres(dump_file, db_url)
    else:
        raise RuntimeError(f"Unsupported DATABASE_URL: {db_url}")

    print('{"ok": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
