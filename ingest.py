"""独立入口：python ingest.py paper.pdf 或 python ingest.py ./pdf_folder/"""
import sys
from proofparse.cli import main

if __name__ == "__main__":
    sys.exit(main())
