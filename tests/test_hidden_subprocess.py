from whale_tracker.sources._hidden_subprocess import hidden_subprocess_kwargs, hide_windows_matching


def test_hidden_subprocess_kwargs_returns_windows_specific_keys_on_nt(monkeypatch):
    import subprocess

    monkeypatch.setattr("whale_tracker.sources._hidden_subprocess.os.name", "nt")
    # STARTUPINFO & co. only exist on Windows; stand them in so this runs
    # (and is a real check of the nt branch) on Linux CI as well.
    if not hasattr(subprocess, "STARTUPINFO"):
        class _FakeStartupInfo:
            dwFlags = 0
            wShowWindow = 0

        monkeypatch.setattr(subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
        monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    kwargs = hidden_subprocess_kwargs()
    assert "creationflags" in kwargs
    assert "startupinfo" in kwargs


def test_hidden_subprocess_kwargs_empty_on_non_windows(monkeypatch):
    monkeypatch.setattr("whale_tracker.sources._hidden_subprocess.os.name", "posix")
    assert hidden_subprocess_kwargs() == {}


def test_hide_windows_matching_enters_and_exits_cleanly():
    # Real, unmocked: runs the actual EnumWindows-based watcher thread
    # for a brief span against a needle unlikely to match any real
    # window, just proving it starts, runs, and stops without error.
    with hide_windows_matching("__whale_tracker_test_needle_unlikely_to_exist__"):
        pass  # entering/exiting is the whole test
