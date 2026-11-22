"""Check a machine before long runs: Python packages, GPU, disk space, and reachability of every data service.

    python scripts/dgx/check_env.py
    python scripts/dgx/check_env.py --no-network
"""

from __future__ import annotations

import argparse
import importlib
import os
import platform
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = {
    "INGV FDSN (Italy waveforms + catalogue)": "https://webservices.ingv.it/fdsnws/event/1/version",
    "SCEDC FDSN (California waveforms + catalogue)": "https://service.scedc.caltech.edu/fdsnws/event/1/version",
    "USGS ComCat (catalogue, ShakeMap)": "https://earthquake.usgs.gov/fdsnws/event/1/version",
    "USGS Vs30 grid": "https://apps.usgs.gov/shakemap_geodata/vs30/global_vs30.grd",
    "PyTorch wheels": "https://download.pytorch.org/whl/",
}


def line(ok, label, detail=""):
    print(f"  [{'OK' if ok else '!!'}] {label}{(': ' + detail) if detail else ''}")
    return ok


def gb(n):
    return f"{n / 1e9:.0f} GB"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--no-network", action="store_true")
    a = p.parse_args(argv)
    ok_all = True
    print(f"python {sys.version.split()[0]} on {platform.machine()} / {platform.system()}, {os.cpu_count()} CPU cores")
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        print(f"memory {gb(mem)}")
    except (ValueError, OSError, AttributeError):
        pass

    print("packages:")
    for mod in ["numpy", "pandas", "scipy", "sklearn", "matplotlib", "obspy", "rasterio", "seisbench", "torch"]:
        try:
            m = importlib.import_module(mod)
            line(True, mod, getattr(m, "__version__", "?"))
        except Exception as exc:
            ok_all &= line(False, mod, f"missing ({type(exc).__name__})")

    print("GPU:")
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            t0 = time.time()
            x = torch.randn(2048, 2048, device="cuda")
            float((x @ x).sum())
            torch.cuda.synchronize()
            free, total = torch.cuda.mem_get_info()
            line(True, f"CUDA {torch.version.cuda}, {name}", f"matmul test {time.time() - t0:.2f}s, "
                 f"{gb(free)} free of {gb(total)}")
        else:
            line(False, "CUDA not available", "training/picking will run on CPU (use --device cpu)")
    except Exception as exc:
        line(False, "torch GPU test failed", str(exc))

    print("disk:")
    sb = Path(os.environ.get("SEISBENCH_CACHE_ROOT", Path.home() / ".seisbench"))
    for label, path in (("repository (data/, outputs/)", ROOT), (f"SeisBench cache {sb}", sb if sb.exists() else sb.parent)):
        u = shutil.disk_usage(path)
        line(u.free > 50e9, label, f"{gb(u.free)} free of {gb(u.total)}"
             + ("" if u.free > 50e9 else " - large datasets (INSTANCE/STEAD) need 100+ GB; set SEISBENCH_CACHE_ROOT"))

    if not a.no_network:
        print("network:")
        try:
            import requests
        except ImportError:
            requests = None
        targets = dict(SERVICES)
        try:
            import seisbench

            targets["SeisBench datasets/weights"] = seisbench.remote_root
        except Exception:
            pass
        for label, url in targets.items():
            if requests is None:
                break
            try:
                r = requests.head(url, timeout=15, allow_redirects=True)
                if r.status_code >= 400:
                    r = requests.get(url, timeout=15, stream=True)
                ok_all &= line(r.status_code < 400, label, f"HTTP {r.status_code}")
            except Exception as exc:
                ok_all &= line(False, label, f"{type(exc).__name__}")
    print("required checks passed (GPU/disk lines are advisory)" if ok_all else "some required checks failed (see !! lines)")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
