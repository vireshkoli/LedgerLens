"""Make sure Docker is running inside the memory limit before the local stack starts.

The Mac has 16 GB and also runs the editor, browser and tests, so Colima gets a fixed share. A VM
that's already too big is reported and left alone: restarting it would stop whatever it's running.
"""

import json
import shutil
import subprocess
import sys

COLIMA_CPUS = 4
COLIMA_MEMORY_GIB = 6
COLIMA_DISK_GIB = 40
BYTES_PER_GIB = 1024**3


def memory_problem(memory_bytes: int) -> str | None:
    """Decide whether the Colima VM is within the memory limit.

    Args:
        memory_bytes: The memory given to the VM, as `colima status --json` reports it.

    Returns:
        What to do about it, or None if the VM is within the limit.
    """
    if memory_bytes <= COLIMA_MEMORY_GIB * BYTES_PER_GIB:
        return None
    memory_gib = memory_bytes / BYTES_PER_GIB
    return (
        f"Colima has {memory_gib:.1f} GiB, above the {COLIMA_MEMORY_GIB} GiB limit. "
        "Run `colima stop` when nothing in it needs to keep running, then try again."
    )


def read_memory_bytes() -> int | None:
    """Read the running VM's memory.

    Returns:
        The VM's memory in bytes, or None if Colima isn't running.
    """
    result = subprocess.run(["colima", "status", "--json"], capture_output=True, check=False)
    if result.returncode != 0:
        return None
    memory_bytes: int = json.loads(result.stdout)["memory"]
    return memory_bytes


def start_colima() -> None:
    """Start the VM with the project's limits."""
    subprocess.run(
        [
            "colima",
            "start",
            f"--cpu={COLIMA_CPUS}",
            f"--memory={COLIMA_MEMORY_GIB}",
            f"--disk={COLIMA_DISK_GIB}",
        ],
        check=True,
    )


def main() -> int:
    """Run the check, starting Colima if it's stopped.

    Returns:
        0 if Docker is ready, otherwise 1.
    """
    # CI runs Docker directly, and the limit exists to protect the Mac.
    if shutil.which("colima") is None:
        return 0

    memory_bytes = read_memory_bytes()
    if memory_bytes is None:
        start_colima()
        return 0

    problem = memory_problem(memory_bytes)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
