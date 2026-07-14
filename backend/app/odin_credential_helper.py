from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path


class CredentialStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def credential_file() -> Path:
    override = os.getenv("ODIN_CREDENTIAL_FILE")
    if override:
        return Path(override).expanduser()
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return root / "Vault" / "odin-credentials.json"


def protect(secret: str) -> str:
    if os.name != "nt":
        raise CredentialStoreError("Odin credential storage currently requires Windows DPAPI.")
    raw = secret.encode("utf-8")
    source_buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    output = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "Vault Odin credential", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def unprotect(encoded: str) -> str:
    if os.name != "nt":
        raise CredentialStoreError("Odin credential storage currently requires Windows DPAPI.")
    raw = base64.b64decode(encoded, validate=True)
    source_buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    output = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def store(client_id: str, credential: str) -> dict:
    if not client_id.strip() or not credential:
        raise CredentialStoreError("A client ID and credential are required.")
    target = credential_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "client_id": client_id.strip(), "protected_credential": protect(credential)}
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return {"stored": True, "client_id": client_id.strip()}


def read() -> dict:
    target = credential_file()
    if not target.exists():
        raise CredentialStoreError("Odin is not paired with Vault.")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return {"client_id": str(payload["client_id"]), "credential": unprotect(payload["protected_credential"])}
    except (KeyError, ValueError, OSError) as exc:
        raise CredentialStoreError("The stored Odin credential is invalid or unavailable.") from exc


def forget() -> dict:
    target = credential_file()
    existed = target.exists()
    target.unlink(missing_ok=True)
    return {"forgotten": existed}


def status() -> dict:
    target = credential_file()
    if not target.exists():
        return {"stored": False}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return {"stored": True, "client_id": str(payload["client_id"])}
    except (KeyError, ValueError, OSError):
        return {"stored": True, "valid": False}


def main() -> int:
    parser = argparse.ArgumentParser(prog="odin-credential-helper")
    commands = parser.add_subparsers(dest="command", required=True)
    store_parser = commands.add_parser("store")
    store_parser.add_argument("--client-id", required=True)
    commands.add_parser("read")
    commands.add_parser("forget")
    commands.add_parser("status")
    args = parser.parse_args()
    try:
        if args.command == "store":
            result = store(args.client_id, sys.stdin.read().rstrip("\r\n"))
        elif args.command == "read":
            result = read()
        elif args.command == "forget":
            result = forget()
        else:
            result = status()
        print(json.dumps(result))
        return 0
    except CredentialStoreError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
