import subprocess
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migrations_up_down_up():
    def alembic(*args):
        r = subprocess.run(["alembic", *args], cwd=BACKEND_DIR, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    alembic("upgrade", "head")
    alembic("downgrade", "base")
    alembic("upgrade", "head")
