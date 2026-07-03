import importlib


def test_default_title_eligibility_and_concise_title():
    history = importlib.import_module("backend.state.history")

    assert history.is_default_session_title("Session - 03:45 PM")
    assert not history.is_default_session_title("QLoRA author review")

    title = history.concise_title_from_exchange(
        "who are the authors of @Qlora_Paper.pdf?",
        "The authors are Tim Dettmers, Artidoro Pagnoni, Ari Holtzman, and Luke Zettlemoyer.",
    )

    assert "Qlora_Paper" not in title
    assert "Authors" in title or "Qlora" in title


def test_recent_targeted_docs_reads_latest_persisted_context(tmp_path, monkeypatch):
    history = importlib.import_module("backend.state.history")
    existing = getattr(history._local, "connection", None)
    if existing is not None:
        existing.close()
        history._local.connection = None

    monkeypatch.setattr(history, "DB_PATH", str(tmp_path / "sessions.db"))
    monkeypatch.setattr(history, "_db_initialized", False)

    history.add_message("s1", "bot", "first", metadata={"targeted_docs": ["FAQ_LTDP_28Dec11.pdf"]})
    history.add_message("s1", "user", "who are the authors")
    history.add_message("s1", "bot", "second", metadata={"targeted_docs": ["Qlora_Paper.pdf"]})

    assert history.get_recent_targeted_docs("s1") == ["Qlora_Paper.pdf"]

    temp_conn = getattr(history._local, "connection", None)
    if temp_conn is not None:
        temp_conn.close()
        history._local.connection = None
    history._db_initialized = False
