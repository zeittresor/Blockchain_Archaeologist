from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Iterable

from .profiles import ChainProfile


class NodeManager:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None

    def start(
        self,
        executable: str,
        datadir: str,
        profile: ChainProfile,
        extra_args: str = "",
        disable_wallet: bool = True,
        listen: bool = False,
    ) -> list[str]:
        if not executable:
            raise ValueError("No node executable selected")
        exe = Path(executable)
        if not exe.exists():
            raise FileNotFoundError(executable)
        Path(datadir).mkdir(parents=True, exist_ok=True)
        args = [
            str(exe), f"-datadir={datadir}", "-server=1", "-prune=0",
            "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.1",
        ]
        if disable_wallet:
            args.append("-disablewallet=1")
        if not listen:
            args.append("-listen=0")
        if profile.extra_start_args:
            args.extend(profile.extra_start_args)
        if extra_args.strip():
            args.extend(shlex.split(extra_args, posix=os.name != "nt"))
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        self.process = subprocess.Popen(args, cwd=str(exe.parent), creationflags=creationflags)
        return args

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def clear_if_stopped(self) -> None:
        if self.process is not None and self.process.poll() is not None:
            self.process = None
