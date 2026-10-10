"""Generate local RSA signing keys; preserve an existing complete pair."""
from pathlib import Path
import subprocess

directory = Path(__file__).resolve().parents[1] / ".secrets"
directory.mkdir(mode=0o700, exist_ok=True)
directory.chmod(0o700)
private, public = directory / "privateKey.pem", directory / "publicKey.pem"
if private.exists() != public.exists():
    raise SystemExit("Incomplete key pair: restore the missing key before continuing")
if not private.exists():
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private)], check=True, stderr=subprocess.DEVNULL)
    private.chmod(0o600)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, stderr=subprocess.DEVNULL)
print("Local JWT key pair ready.")
