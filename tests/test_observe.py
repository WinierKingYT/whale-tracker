from whale_tracker import observe


def test_log_file_appends_with_timestamp_header(tmp_path, monkeypatch):
    def fake_run_once(db_path, *, min_usd, classify_limit):
        return "sahte rapor içeriği"

    monkeypatch.setattr(observe, "run_once", fake_run_once)

    log_path = tmp_path / "nested" / "observer.log"
    monkeypatch.setattr(
        "sys.argv",
        ["observe", "--db", str(tmp_path / "x.db"), "--log-file", str(log_path)],
    )
    observe.main()

    assert log_path.is_file()
    content = log_path.read_text(encoding="utf-8")
    assert "sahte rapor içeriği" in content
    assert "-----" in content  # timestamp header separator

    # second run appends, does not overwrite
    observe.main()
    content_after = log_path.read_text(encoding="utf-8")
    assert content_after.count("sahte rapor içeriği") == 2
