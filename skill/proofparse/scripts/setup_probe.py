"""Read-only installation probe. Standard library only; no downloads or environment changes."""
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def main():
    versions = {}
    for name in ("proofparse", "mineru", "torch", "pypdfium2", "Pillow", "numpy"):
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = None
    gpu = None
    cuda_available = False
    torch_probe_error = None
    if versions["torch"]:
        try:
            result = subprocess.run([sys.executable, "-B", "-c",
                "import torch; print('cuda' if torch.cuda.is_available() else 'cpu')"],
                capture_output=True, text=True, timeout=30)
            cuda_available = result.returncode == 0 and result.stdout.strip() == "cuda"
            if result.returncode:
                torch_probe_error = result.stderr.strip()[-500:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            torch_probe_error = str(exc)
    requested_device = os.environ.get("PROOFPARSE_MINERU_DEVICE", "auto").strip().lower()
    selected_device = ("cuda" if cuda_available else "cpu") if requested_device == "auto" else requested_device
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            r = subprocess.run([exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                               capture_output=True,text=True,timeout=10)
            gpu = r.stdout.strip() if r.returncode == 0 else None
        except (OSError,subprocess.TimeoutExpired): pass
    config = Path(os.environ.get("MINERU_TOOLS_CONFIG_JSON", "mineru.json"))
    if not config.is_absolute(): config = Path.home() / config
    caches = {}
    if config.is_file():
        try:
            data=json.loads(config.read_text(encoding="utf-8"))
            for name,path in (data.get("models-dir") or {}).items():
                if isinstance(path,str) and path: caches[name]={"path":path,"exists":Path(path).is_dir()}
        except (OSError,ValueError): pass
    print(json.dumps({"python":sys.executable,"python_version":platform.python_version(),
                      "os":platform.platform(),"packages":versions,"gpu":gpu,
                      "requested_device":requested_device,"selected_device":selected_device,
                      "torch_cuda_available":cuda_available,"torch_probe_error":torch_probe_error,
                      "conda":shutil.which("conda"),"configured_models":caches,
                      "huggingface_cache":os.environ.get("HF_HOME",str(Path.home()/'.cache/huggingface')),
                      "modelscope_cache":os.environ.get("MODELSCOPE_CACHE",str(Path.home()/'.cache/modelscope')),
                      "downloaded":False,"changed_environment":False},ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
