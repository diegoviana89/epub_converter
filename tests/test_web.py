"""Pruebas del servicio web: descarga por partes, limpieza de temporales y CORS."""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("flask")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_sample_pdf import build  # noqa: E402
import web.app as webapp  # noqa: E402

ORIGEN = "https://epubtailor.pages.dev"


@pytest.fixture(scope="module")
def pdf_bytes(tmp_path_factory):
    p = tmp_path_factory.mktemp("w") / "sample.pdf"
    build(str(p))
    return p.read_bytes()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # los temporales del servicio, aquí
    monkeypatch.setattr(webapp, "ALLOWED_ORIGINS", {ORIGEN})
    return webapp.app.test_client()


def subir(client, data, nombre="Mi libro.pdf", **headers):
    return client.post("/api/convert", data={"pdf": (io.BytesIO(data), nombre)},
                       content_type="multipart/form-data", headers=headers)


def test_epub_se_envia_por_partes_y_se_borra_el_temporal(client, pdf_bytes, tmp_path):
    r = subir(client, pdf_bytes)
    assert r.status_code == 200
    assert r.is_streamed and "Content-Length" not in r.headers  # chunked: sin límite de 32 MiB en Cloud Run
    assert r.headers["Content-Disposition"] == 'attachment; filename="Mi_libro.epub"'
    z = zipfile.ZipFile(io.BytesIO(r.get_data()))
    assert z.namelist()[0] == "mimetype"
    r.close()
    assert os.listdir(tmp_path) == []


def test_error_borra_el_temporal(client, tmp_path):
    r = subir(client, b"esto no es un pdf")
    assert r.status_code == 400
    assert os.listdir(tmp_path) == []


def test_cors_origen_permitido(client, pdf_bytes):
    r = subir(client, pdf_bytes, Origin=ORIGEN)
    assert r.headers["Access-Control-Allow-Origin"] == ORIGEN
    assert "Content-Disposition" in r.headers["Access-Control-Expose-Headers"]
    r.close()


def test_cors_preflight(client):
    r = client.options("/api/convert", headers={"Origin": ORIGEN, "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == ORIGEN
    assert "POST" in r.headers["Access-Control-Allow-Methods"]


def test_cors_origen_no_permitido(client):
    r = client.get("/api/config", headers={"Origin": "https://otro.example"})
    assert "Access-Control-Allow-Origin" not in r.headers


def test_pdf_demasiado_grande(client, monkeypatch):
    monkeypatch.setitem(webapp.app.config, "MAX_CONTENT_LENGTH", 1024)
    r = subir(client, b"%PDF-" + b"0" * 4096, Origin=ORIGEN)
    assert r.status_code == 413
    assert r.headers["Access-Control-Allow-Origin"] == ORIGEN  # el error llega legible a la página
