import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import app


def test_generated_images_rejects_path_traversal():
    client = app.test_client()
    response = client.get("/generated_images/../app.py")
    assert response.status_code == 404
