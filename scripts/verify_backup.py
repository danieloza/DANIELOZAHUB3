import argparse
import io
import json
import sys
from pathlib import Path

from cryptography.fernet import Fernet
import tarfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def _latest_encrypted_backup(backups_dir: Path) -> Path:
    candidates = sorted(backups_dir.glob("*.enc"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise RuntimeError(f"No encrypted backup files found in: {backups_dir}")
    return candidates[0]


def _decrypt_backup(backup_file: Path) -> bytes:
    key = (settings.BACKUP_ENCRYPTION_KEY or "").strip()
    if not key:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY is required to verify encrypted backup")
    fernet = Fernet(key.encode("utf-8"))
    try:
        return fernet.decrypt(backup_file.read_bytes())
    except Exception as exc:
        raise RuntimeError(f"Backup decryption failed: {backup_file.name}") from exc


def _verify_archive_payload(archive_bytes: bytes) -> tuple[str, int]:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            names = [m.name for m in tar.getmembers() if m.isfile()]
            if "database.sqlite3" in names:
                payload_name = "database.sqlite3"
            elif "database.pg.dump" in names:
                payload_name = "database.pg.dump"
            else:
                raise RuntimeError("Backup archive missing expected DB payload file")

            payload_member = tar.getmember(payload_name)
            payload_size = int(payload_member.size or 0)
            if payload_size <= 0:
                raise RuntimeError("Backup payload file is empty")
            return payload_name, payload_size
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Backup archive integrity check failed") from exc


def _load_metadata(metadata_file: Path | None, backup_file: Path) -> dict:
    sidecar = metadata_file or backup_file.with_suffix(backup_file.suffix + ".json")
    if not sidecar.exists():
        return {"present": False, "file": str(sidecar)}
    try:
        parsed = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid backup metadata JSON: {sidecar}") from exc
    return {"present": True, "file": str(sidecar), "payload": parsed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify encrypted SalonOS backup integrity and payload readability")
    parser.add_argument("--backup-file", default="", help="Path to .enc backup file; defaults to latest in backups dir")
    parser.add_argument("--backups-dir", default=str(ROOT / "backups" / "pitr"))
    parser.add_argument("--metadata-file", default="", help="Optional explicit metadata file path")
    args = parser.parse_args()

    backups_dir = Path(args.backups_dir).resolve()
    backup_file = Path(args.backup_file).resolve() if args.backup_file else _latest_encrypted_backup(backups_dir)
    if not backup_file.exists():
        raise RuntimeError(f"Backup file not found: {backup_file}")

    metadata_file = Path(args.metadata_file).resolve() if args.metadata_file else None
    metadata = _load_metadata(metadata_file, backup_file)

    archive_bytes = _decrypt_backup(backup_file)
    payload_name, payload_size = _verify_archive_payload(archive_bytes)

    output = {
        "ok": True,
        "backup_file": str(backup_file),
        "backup_size_bytes": int(backup_file.stat().st_size),
        "payload_file": payload_name,
        "payload_size_bytes": int(payload_size),
        "metadata": metadata,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
