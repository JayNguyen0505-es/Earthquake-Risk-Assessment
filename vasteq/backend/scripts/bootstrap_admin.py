"""Create the first administrator through the local Docker database connection."""
import argparse
import base64
import getpass
import hashlib
from pathlib import Path
import secrets
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--email", required=True)
parser.add_argument("--name", required=True)
args = parser.parse_args()
email, name = args.email.strip().lower(), args.name.strip()
if "@" not in email or len(email) > 254 or not name or len(name) > 120:
    raise SystemExit("Provide a valid email and a display name of at most 120 characters")
password = getpass.getpass("Administrator password (12–128 characters): ")
if not 12 <= len(password) <= 128 or password != getpass.getpass("Confirm password: "):
    raise SystemExit("Invalid password length or confirmation")
salt = secrets.token_bytes(16)
encode = lambda value: base64.b64encode(value).decode().rstrip("=")
hashed = "pbkdf2-sha256$600000$" + encode(salt) + "$" + encode(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000))
literal = lambda value: "CONVERT(X'" + value.encode().hex() + "' USING utf8mb4)"
sql = f"""SET NAMES utf8mb4;
INSERT INTO users(email,password_hash,display_name,role,enabled)
SELECT {literal(email)}, {literal(hashed)}, {literal(name)}, 'admin', true
WHERE NOT EXISTS (SELECT id FROM users WHERE role='admin' AND enabled=true);
SELECT ROW_COUNT() AS administrators_created;
"""
root = Path(__file__).resolve().parents[3]
subprocess.run(["docker", "compose", "-f", "vasteq/deployment/compose.yaml", "exec", "-T", "mysql", "sh", "-c",
    'MYSQL_PWD="$(cat /run/secrets/mysql_app_password)" exec mysql --default-character-set=utf8mb4 -u vasteq -D vasteq'], input=sql, text=True, cwd=root, check=True)
