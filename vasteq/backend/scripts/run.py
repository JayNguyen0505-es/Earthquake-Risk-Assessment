"""Run the packaged backend with local database credentials and signing keys."""
import os
from pathlib import Path

backend = Path(__file__).resolve().parents[1]
env = os.environ.copy()
if "DB_PASSWORD" not in env:
    env["DB_PASSWORD"] = (backend.parent / "deployment/.secrets/mysql_app_password").read_text().strip()
env.setdefault("JWT_PRIVATE_KEY", (backend / ".secrets/privateKey.pem").as_uri())
env.setdefault("JWT_PUBLIC_KEY", (backend / ".secrets/publicKey.pem").as_uri())
jar = backend / "target/quarkus-app/quarkus-run.jar"
if not jar.exists():
    raise SystemExit("Build the backend with ./mvnw package first")
os.execvpe("java", ["java", "-jar", str(jar)], env)
