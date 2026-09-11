"""Multi-process launcher for Tandem Operator Console and Banking Simulators."""

import signal
import subprocess
import sys
import time

SERVICES = [
    {"name": "Core Bank Simulator", "app": "simulators.core_bank.app:app", "port": 8001},
    {"name": "Card Processor Simulator", "app": "simulators.processor.app:app", "port": 8003},
    {"name": "Notice Simulator", "app": "simulators.documents.app:app", "port": 8004},
    {"name": "Tandem Operator Console", "app": "tandem.api.app:app", "port": 8000},
]


def main():
    processes = []
    print("=================================================================")
    print("           TANDEM FINANCIAL AUTOMATION SYSTEM                   ")
    print("=================================================================")

    try:
        for svc in SERVICES:
            print(f"[*] Launching {svc['name']} on http://127.0.0.1:{svc['port']}...")
            cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                svc["app"],
                "--host",
                "0.0.0.0",
                "--port",
                str(svc["port"]),
                "--log-level",
                "info",
            ]
            p = subprocess.Popen(cmd)
            processes.append((svc["name"], p))

        print("\n[+] All services active!")
        print("  - Operator Console: http://127.0.0.1:8000")
        print("  - Core Bank Alpha:  http://127.0.0.1:8001")
        print("  - Core Bank Beta:   http://127.0.0.1:8001/inst_beta")
        print("  - Card Processor:   http://127.0.0.1:8003")
        print("  - Notice Simulator: http://127.0.0.1:8004")
        print("\nPress Ctrl+C to terminate all services.\n")

        while True:
            time.sleep(1)
            for name, p in processes:
                if p.poll() is not None:
                    print(f"[!] Warning: Service '{name}' exited prematurely with code {p.returncode}")
                    return p.returncode

    except KeyboardInterrupt:
        print("\n[*] Shutting down all services...")
    finally:
        for name, p in processes:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()
        print("[+] All services halted cleanly.")


if __name__ == "__main__":
    sys.exit(main() or 0)
