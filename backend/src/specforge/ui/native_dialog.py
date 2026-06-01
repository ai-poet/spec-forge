from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def pick_folder(*, prompt: str = "选择项目文件夹") -> str | None:
    system = platform.system()
    if system == "Darwin":
        return _pick_folder_macos(prompt)
    if system == "Windows":
        return _pick_folder_tk(prompt)
    picked = _pick_folder_linux(prompt)
    if picked:
        return picked
    return _pick_folder_tk(prompt)


def _pick_folder_macos(prompt: str) -> str | None:
    escaped = prompt.replace("\\", "\\\\").replace('"', '\\"')
    script = f'POSIX path of (choose folder with prompt "{escaped}")'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    path = result.stdout.strip()
    return path or None


def _pick_folder_linux(prompt: str) -> str | None:
    try:
        result = subprocess.run(
            ["zenity", "--file-selection", "--directory", f"--title={prompt}"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    path = result.stdout.strip()
    return path or None


def _pick_folder_tk(prompt: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    path = filedialog.askdirectory(title=prompt, mustexist=True)
    root.destroy()
    return path or None


def resolve_picked_folder(path: str) -> str:
    return str(Path(path).expanduser().resolve())
