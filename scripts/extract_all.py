#!/usr/bin/env python3
"""Extract text from all PDFs and save to data/texts/"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_extractor import extract_all_pdfs
import json

def main():
    pdfs_dir = "data/pdfs"
    texts_dir = "data/texts"
    os.makedirs(texts_dir, exist_ok=True)

    print(f"Extracting text from PDFs in {pdfs_dir}...")
    texts = extract_all_pdfs(pdfs_dir)

    for filename, text in texts.items():
        out_path = os.path.join(texts_dir, filename.replace(".pdf", ".txt"))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"  done: {filename} -> {len(text)} chars")

    summary = {name: len(text) for name, text in texts.items()}
    with open(os.path.join(texts_dir, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nExtracted {len(texts)} files to {texts_dir}")

if __name__ == "__main__":
    main()
