import os
os.environ["ORBIS_DB"] = ":memory:"
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_end_to_end_flow(client):
    assert client.get("/api/health").json()["extractor"] == "rules-v1"
    seeded = client.post("/api/demo/seed").json()
    assert len(seeded) == 2

    pid = next(p["id"] for p in seeded if "Northfield" in p["name"])
    before = client.get(f"/api/checklist/{pid}").json()
    assert before["counts"].get("missing", 0) >= 3

    client.post("/api/documents", json={"filename": "my_transcript.pdf"})
    client.post("/api/documents", json={"filename": "resume_2026.pdf"})
    after = client.get(f"/api/checklist/{pid}").json()
    assert after["counts"]["satisfied"] >= 2
    assert after["counts"].get("missing", 0) < before["counts"]["missing"]

    tl = client.get("/api/timeline").json()
    assert [d["due"] for d in tl] == sorted(d["due"] for d in tl)

    task = after["tasks"][0]
    src = client.get(f"/api/sources/{task['citation']['source_id']}").json()
    assert task["citation"]["quote"].split()[0] in " ".join(src["pages"])


def test_rejects_private_urls_and_empty_input(client):
    assert client.post("/api/programs", json={"name": "x"}).status_code == 422
    assert client.post("/api/programs", json={"name": "x", "url": "http://127.0.0.1:8000/"}).status_code == 400


def test_delete_my_data(client):
    client.post("/api/demo/seed")
    client.delete("/api/me")
    assert client.get("/api/programs").json() == []


def test_landing_and_app_pages(client):
    assert "Orbis" in client.get("/").text
    r = client.get("/app")
    assert r.status_code == 200 and "Try sample programs" in r.text
