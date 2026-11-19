import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter


class CommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    stdout: str
    stderr: str
    seconds: float
    log: Path | None


def run(argv, *, cwd=None, timeout=600, env=None, log=None) -> Result:
    start = perf_counter()
    try:
        with subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8",
                              errors="replace", start_new_session=(os.name == "posix")) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                error = f"status {proc.returncode}" if proc.returncode else None
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    proc.kill()
                stdout, stderr = proc.communicate()
                error = f"tempo limite de {timeout}s"
    except OSError as exc:
        stdout, stderr, error = "", str(exc), "falha ao iniciar"
    seconds = perf_counter() - start
    if log is not None:
        log.write_text(f"{list(argv)!r}\n\nSTDOUT\n{stdout}\nSTDERR\n{stderr}",
                       encoding="utf-8")
    if error:
        detail = f"consulte {log}" if log else stderr.strip()[-600:]
        raise CommandError(f"{argv[0]}: {error}. {detail}")
    return Result(stdout, stderr, seconds, log)
