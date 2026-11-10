"""Per-user isolation: one user must never see or change another user's data."""


def test_documents_are_private(make_client):
    a, b = make_client(), make_client()
    doc = a.post("/api/documents", json={"filename": "transcript_final.pdf"}).json()

    assert [d["id"] for d in a.get("/api/documents").json()] == [doc["id"]]
    assert b.get("/api/documents").json() == []

    b.delete(f"/api/documents/{doc['id']}")  # must not touch A's row
    assert len(a.get("/api/documents").json()) == 1


def test_programs_and_sources_are_private(make_client):
    a, b = make_client(), make_client()
    programs = a.post("/api/demo/seed").json()
    assert programs, "demo seed should create at least one program"
    pid = programs[0]["id"]

    assert len(a.get("/api/programs").json()) == len(programs)
    assert b.get("/api/programs").json() == []
    assert b.get(f"/api/programs/{pid}").status_code == 404
    assert b.get("/api/timeline").json() == []

    detail = a.get(f"/api/programs/{pid}").json()
    cited = [r["citation"]["source_id"] for r in detail["requirements"] if r.get("citation")]
    if cited:
        assert a.get(f"/api/sources/{cited[0]}").status_code == 200
        assert b.get(f"/api/sources/{cited[0]}").status_code == 404

    b.delete(f"/api/programs/{pid}")  # must not touch A's row
    assert a.get(f"/api/programs/{pid}").status_code == 200


def test_delete_me_only_deletes_my_data(make_client):
    a, b = make_client(), make_client()
    a.post("/api/documents", json={"filename": "cv.pdf"})
    b.post("/api/documents", json={"filename": "passport.pdf"})

    b.delete("/api/me")

    assert b.get("/api/documents").json() == []
    assert len(a.get("/api/documents").json()) == 1


def test_delete_program_also_deletes_its_source_text(make_client):
    a = make_client()
    pid = a.post("/api/demo/seed").json()[0]["id"]
    detail = a.get(f"/api/programs/{pid}").json()
    cited = [r["citation"]["source_id"] for r in detail["requirements"] if r.get("citation")]

    a.delete(f"/api/programs/{pid}")

    assert a.get(f"/api/programs/{pid}").status_code == 404
    for source_id in cited[:1]:
        assert a.get(f"/api/sources/{source_id}").status_code == 404
