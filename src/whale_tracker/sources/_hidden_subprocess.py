"""Shared helper for running a CLI subprocess with NO visible window on
Windows -- used by classify.py (Hermes) and analysis.py/proposal.py
(Claude Code CLI).

Three layered mechanisms, because the first two alone were NOT enough --
confirmed by the user still seeing a window titled "hermes.EXE" after
both were in place:
1. `creationflags=CREATE_NO_WINDOW` stops Windows from allocating a new
   console for a console-subsystem child process.
2. `startupinfo` with STARTF_USESHOWWINDOW + wShowWindow=SW_HIDE tells
   any window the child creates via a normal CreateWindow+ShowWindow
   call to start hidden.
3. **A live watcher that actively hides any window title-matching a
   given substring while the call runs.** This is the mechanism that
   actually matters here: the window's title bar showed the exe's full
   path with no custom title set, which is the standard signature of a
   *separately allocated* console (AllocConsole/CreateProcess with
   CREATE_NEW_CONSOLE) -- almost certainly created by a grandchild
   process Hermes's own launcher stub spawns internally with its own
   explicit console flags, which #1/#2 above (only controlling the
   DIRECT child this module launches) cannot reach. Enumerating and
   hiding by title, while the call is in flight, doesn't care what
   spawned the window or how many processes deep it is -- it does not
   depend on cooperation from Hermes/Claude's own process tree at all."""

from __future__ import annotations

import ctypes
import os
import subprocess
import threading
from ctypes import wintypes
from typing import Any, Self


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """Extra kwargs to merge into a subprocess.run(...) call. Empty dict
    on non-Windows platforms."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


class _WindowHider:
    """Background thread that repeatedly enumerates top-level windows
    and hides (SW_HIDE) any whose title contains `title_substring`
    (case-insensitive), until stopped. Windows-only; a no-op context
    manager elsewhere."""

    _SW_HIDE = 0
    # Real 2026-09-24 case: even with this watcher running, the user still
    # saw a brief flash on real Hermes calls -- the process-tree cleanup
    # (run_hidden_and_reap's taskkill) was confirmed to leave nothing
    # lingering, but that's a different guarantee from "never visible for
    # even one frame." A poll-based hider is inherently a race against
    # window creation; 0.1s was long enough for a fresh console to paint
    # and be perceived before the next poll caught it. 0.02s doesn't
    # eliminate the race (a true fix would need a Windows event hook,
    # e.g. SetWinEventHook, reacting to window creation instead of
    # polling for it) but cuts the exposure window 5x, which in practice
    # is below the threshold of a noticeable flash for a console that's
    # hidden within one or two repaints instead of several.
    _POLL_INTERVAL_S = 0.02

    def __init__(self, title_substring: str) -> None:
        self._needle = title_substring.lower()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _hide_matching_windows(self) -> None:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _callback(hwnd: int, _lparam: int) -> bool:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if self._needle in buffer.value.lower():
                    user32.ShowWindow(hwnd, self._SW_HIDE)
            return True

        user32.EnumWindows(WNDENUMPROC(_callback), 0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._hide_matching_windows()
            except OSError:
                pass  # best-effort -- never let the watcher itself break the real call
            self._stop.wait(self._POLL_INTERVAL_S)

    def __enter__(self) -> Self:
        if os.name == "nt":
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def hide_windows_matching(title_substring: str) -> _WindowHider:
    """Context manager: while active, any top-level window whose title
    contains `title_substring` gets hidden shortly after it appears.
    Use around a subprocess.run(...) call for a CLI known to pop a
    window no launch flag alone suppresses."""
    return _WindowHider(title_substring)


def run_hidden_and_reap(command: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    """Run `command` with every window-suppression mechanism applied, and
    ALWAYS force-kill its entire process tree (taskkill /F /T) once it
    finishes -- on success, on failure, AND on timeout, not just the
    error path.

    Why this exists, found the hard way: a Hermes call that hits its own
    internal retry loop against a rate-limited backend (observed: "API
    call failed after 3 retries: HTTP 429") can run long enough to trip
    this module's own subprocess timeout. subprocess.Popen.kill() (what
    subprocess.run's timeout handling calls) only terminates the DIRECT
    child -- it does not touch any grandchild process Hermes's own
    launcher stub spawns internally with its own separate console. That
    orphaned grandchild then keeps running (and re-showing its window)
    indefinitely after the parent it came from is already gone, which is
    what produced the "opens and closes, opens and closes" pattern the
    user kept seeing even after CREATE_NO_WINDOW/STARTUPINFO/the window-
    hider were all in place -- those only ever addressed the direct
    child, never orphaned grandchildren surviving a timeout kill.
    `taskkill /F /T /PID <pid>` kills the named process AND its full
    descendant tree; running it unconditionally after every call (even
    ones that finished normally) guards against a grandchild that's
    still alive as a background daemon even on the happy path."""
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_subprocess_kwargs(),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, returncode, timed_out = "", "", -1, True
    finally:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, check=False, **hidden_subprocess_kwargs(),
            )
        else:
            process.kill()
    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout)
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)
