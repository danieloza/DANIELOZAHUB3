import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _db_dump_file(tmp_dir: Path) -> Path:
    db_url = settings.DATABASE_URL.strip()
    if db_url.startswith("sqlite:///"):
        src = Path(db_url.replace("sqlite:///", "", 1)).resolve()
        if not src.exists():
            raise RuntimeError(f"SQLite DB file not found: {src}")
        dst = tmp_dir / "database.sqlite3"
        shutil.copy2(src, dst)
        return dst

    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        out = tmp_dir / "database.pg.dump"
        cmd = ["pg_dump", "--format=custom", "--file", str(out), db_url]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return out

    raise RuntimeError(f"Unsupported DATABASE_URL: {db_url}")


def _encrypt_file(input_path: Path, output_path: Path) -> None:
    key = settings.BACKUP_ENCRYPTION_KEY.strip()
    if not key:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY is required for encrypted backups")
    fernet = Fernet(key.encode("utf-8"))
    payload = input_path.read_bytes()
    output_path.write_bytes(fernet.encrypt(payload))


def _upload_offsite(file_path: Path, object_key: str) -> dict:
    bucket = settings.OFFSITE_S3_BUCKET.strip()
    if not bucket:
        return {"uploaded": False, "reason": "OFFSITE_S3_BUCKET not configured"}

    kwargs = {}
    if settings.OFFSITE_S3_REGION:
        kwargs["region_name"] = settings.OFFSITE_S3_REGION
    if settings.OFFSITE_S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.OFFSITE_S3_ENDPOINT_URL
    s3 = boto3.client("s3", **kwargs)
    s3.upload_file(str(file_path), bucket, object_key)
    return {"uploaded": True, "bucket": bucket, "object_key": object_key}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create encrypted PITR-style backup and optional offsite upload"
    )
    parser.add_argument("--out-dir", default=str(ROOT / "backups" / "pitr"))
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    work_dir = out_dir / f"tmp_{stamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    dump_file = _db_dump_file(work_dir)
    archive_path = out_dir / f"salonos_pitr_{stamp}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(dump_file, arcname=dump_file.name)

    encrypted_path = out_dir / f"{archive_path.name}.enc"
    _encrypt_file(archive_path, encrypted_path)

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database_url_scheme": settings.DATABASE_URL.split(":", 1)[0],
        "archive_file": archive_path.name,
        "encrypted_file": encrypted_path.name,
        "size_bytes": encrypted_path.stat().st_size,
    }
    upload = _upload_offsite(
        encrypted_path, object_key=f"salonos/{encrypted_path.name}"
    )
    metadata["offsite"] = upload

    metadata_path = out_dir / f"{encrypted_path.name}.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    shutil.rmtree(work_dir, ignore_errors=True)
    archive_path.unlink(missing_ok=True)

    print(
        json.dumps(
            {
                "ok": True,
                "backup_file": str(encrypted_path),
                "metadata_file": str(metadata_path),
                "offsite": upload,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
