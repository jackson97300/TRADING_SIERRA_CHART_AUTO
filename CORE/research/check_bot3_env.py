"""Lit env vars du process Bot 3 (PID 8688) pour verifier LADDER actif."""
import sys
import psutil


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 8688
    try:
        p = psutil.Process(pid)
        env = p.environ()
        print(f"=== Process {pid} ({p.name()}) env vars ===")
        for k, v in sorted(env.items()):
            if k.startswith("MIA_") or "LADDER" in k:
                print(f"  {k}={v}")
        print(f"\n=== Process info ===")
        print(f"  create_time: {p.create_time()}")
        print(f"  status: {p.status()}")
        print(f"  cmdline: {' '.join(p.cmdline())[:200]}")
    except psutil.NoSuchProcess:
        print(f"PID {pid} not found")


if __name__ == "__main__":
    main()
