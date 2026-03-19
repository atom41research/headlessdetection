"""Host-side Docker stats collection via the Docker SDK.

Run this alongside `docker compose up` to capture container-level metrics:
    uv run python -m bench.host_stats --container chrome-bench
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import docker
except ImportError:
    print("docker SDK not installed. Run: uv sync --group dev", file=sys.stderr)
    sys.exit(1)


def parse_cpu_percent(stats: dict) -> float:
    """Calculate CPU percentage from docker stats JSON."""
    cpu = stats.get("cpu_stats", {})
    precpu = stats.get("precpu_stats", {})

    cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - precpu.get("cpu_usage", {}).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)

    if system_delta <= 0 or cpu_delta < 0:
        return 0.0

    num_cpus = len(cpu.get("cpu_usage", {}).get("percpu_usage", []) or [1])
    return (cpu_delta / system_delta) * num_cpus * 100.0


def collect(container_name: str, output_path: Path, interval_s: float) -> None:
    client = docker.from_env()

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        print(f"Container '{container_name}' not found. Is it running?", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["wall_clock", "cpu_pct", "mem_bytes", "mem_limit_bytes", "mem_pct"]

    print(f"Collecting stats for '{container_name}' -> {output_path}")
    print("Press Ctrl+C to stop.\n")

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        try:
            for raw in container.stats(stream=True, decode=True):
                mem = raw.get("memory_stats", {})
                mem_usage = mem.get("usage", 0)
                mem_limit = mem.get("limit", 1)
                cpu_pct = parse_cpu_percent(raw)

                row = {
                    "wall_clock": datetime.now(timezone.utc).isoformat(),
                    "cpu_pct": f"{cpu_pct:.2f}",
                    "mem_bytes": mem_usage,
                    "mem_limit_bytes": mem_limit,
                    "mem_pct": f"{(mem_usage / mem_limit) * 100:.2f}" if mem_limit else "0",
                }
                writer.writerow(row)
                f.flush()

                print(
                    f"  CPU: {cpu_pct:6.1f}%  |  "
                    f"MEM: {mem_usage / (1024*1024):7.1f} MB / {mem_limit / (1024*1024):.0f} MB "
                    f"({(mem_usage/mem_limit)*100:.1f}%)",
                    end="\r",
                )
        except KeyboardInterrupt:
            print("\nStopped.")
        except docker.errors.APIError as e:
            if "is not running" in str(e):
                print("\nContainer stopped.")
            else:
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Docker container stats")
    parser.add_argument("--container", default="chrome-bench", help="Container name")
    parser.add_argument("--output", type=Path, default=Path("bench/results/docker_stats.csv"))
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval (seconds)")
    args = parser.parse_args()
    collect(args.container, args.output, args.interval)


if __name__ == "__main__":
    main()
