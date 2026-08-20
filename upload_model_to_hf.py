"""
Upload the 4-bit FunctionGemma Pocket model (GGUF) to Hugging Face.

Prerequisites:
  1. Install: pip install huggingface-hub
  2. Log in: huggingface-cli login   (or set HF_TOKEN in environment)

Usage:
  python upload_model_to_hf.py
  python upload_model_to_hf.py --repo-id your-username/functiongemma-pocket-q4_k_m
"""

import argparse
import io
from pathlib import Path

from huggingface_hub import HfApi, create_repo

# Default paths
MODEL_PATH = Path(__file__).parent / "functiongemma-pocket-q4_k_m.gguf"
REPO_TYPE = "model"


def main():
    parser = argparse.ArgumentParser(description="Upload 4-bit GGUF model to Hugging Face")
    parser.add_argument(
        "--repo-id",
        type=str,
        default=None,
        help="Hugging Face repo (e.g. username/model-name). Default: infer from your HF username",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=MODEL_PATH,
        help=f"Local path to the .gguf file (default: {MODEL_PATH})",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create the repo as private",
    )
    args = parser.parse_args()

    path = args.model_path
    if not path.is_file():
        print(f"Error: Model file not found at {path}")
        print("  Place functiongemma-pocket-q4_k_m.gguf in the project root or pass --model-path.")
        return 1

    # Repo ID: use provided or default to username/functiongemma-pocket-q4_k_m
    if args.repo_id:
        repo_id = args.repo_id
    else:
        try:
            api = HfApi()
            whoami = api.whoami()
            username = whoami.get("name") or "unknown"
            repo_id = f"{username}/functiongemma-pocket-q4_k_m"
        except Exception as e:
            print("Could not get your Hugging Face username. Run: huggingface-cli login")
            print("Or pass --repo-id your_username/functiongemma-pocket-q4_k_m")
            raise SystemExit(1) from e

    print(f"Model file: {path} ({path.stat().st_size / (1024**2):.1f} MB)")
    print(f"Target repo: https://huggingface.co/{repo_id}")
    print("Creating repo (if needed) and uploading...")

    api = HfApi()
    create_repo(repo_id, repo_type=REPO_TYPE, private=args.private, exist_ok=True)

    # Upload the GGUF model
    api.upload_file(
        path_or_fileobj=str(path),
        path_in_repo=path.name,
        repo_id=repo_id,
        repo_type=REPO_TYPE,
        commit_message="Upload functiongemma-pocket-q4_k_m.gguf (4-bit quantized)",
    )

    # Upload a minimal model card
    readme = f"""---
library_name: gguf
license: apache-2.0
---

# FunctionGemma Pocket (Q4_K_M)

4-bit quantized GGUF model (q4_k_m) for use with llama.cpp / llama-cpp-python.

## Usage

```python
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

path = hf_hub_download(repo_id="{repo_id}", filename="{path.name}")
llm = Llama(model_path=path, n_ctx=2048, n_gpu_layers=-1)
```
"""
    api.upload_file(
        path_or_fileobj=io.BytesIO(readme.encode()),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type=REPO_TYPE,
        commit_message="Add model card",
    )

    print("Done!")
    print(f"  Model URL: https://huggingface.co/{repo_id}/blob/main/{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
