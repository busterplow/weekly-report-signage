"""
Weekly Report PDF → GitHub Pages Slideshow
Watches a folder for PDF files. When a new/updated PDF is detected:
  1. Converts each page to a high-quality JPG
  2. Generates slides.json manifest
  3. Pushes to GitHub Pages for live display on Ablesign.tv
"""

import sys
import os
import json
import time
import shutil
import subprocess
import logging
from pathlib import Path

import fitz  # PyMuPDF
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Configuration ---
WATCH_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(REPO_DIR, "docs")
SLIDES_DIR = os.path.join(DOCS_DIR, "slides")
DPI = 200  # Image quality (200 DPI is sharp on 1080p signage)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("report-watcher")


def convert_pdf_to_images(pdf_path: str) -> list[str]:
    """Convert each page of a PDF to a JPG image. Returns list of filenames."""
    log.info(f"Converting: {pdf_path}")
    os.makedirs(SLIDES_DIR, exist_ok=True)

    # Clean old slides
    for f in Path(SLIDES_DIR).glob("slide_*.jpg"):
        f.unlink()

    doc = fitz.open(pdf_path)
    filenames = []

    for i, page in enumerate(doc):
        zoom = DPI / 72  # 72 is default PDF DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        filename = f"slide_{i + 1:02d}.jpg"
        filepath = os.path.join(SLIDES_DIR, filename)
        pix.save(filepath)
        filenames.append(f"slides/{filename}")
        log.info(f"  Page {i + 1}/{len(doc)} → {filename}")

    doc.close()
    log.info(f"Converted {len(filenames)} pages")
    return filenames


def write_manifest(slide_files: list[str]):
    """Write slides.json manifest for the HTML slideshow."""
    manifest = {"slides": slide_files, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    manifest_path = os.path.join(DOCS_DIR, "slides.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    log.info(f"Manifest written: {len(slide_files)} slides")


def push_to_github():
    """Stage, commit, and push changes to GitHub."""
    try:
        subprocess.run(["git", "add", "docs/"], cwd=REPO_DIR, check=True,
                        capture_output=True, text=True)

        # Check if there are staged changes
        result = subprocess.run(["git", "diff", "--cached", "--quiet"],
                                cwd=REPO_DIR, capture_output=True)
        if result.returncode == 0:
            log.info("No changes to push")
            return

        timestamp = time.strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"Update weekly report slides - {timestamp}"],
            cwd=REPO_DIR, check=True, capture_output=True, text=True
        )
        subprocess.run(["git", "push"], cwd=REPO_DIR, check=True,
                        capture_output=True, text=True)
        log.info("Pushed to GitHub — slideshow will update shortly")
    except subprocess.CalledProcessError as e:
        log.error(f"Git error: {e.stderr}")


def process_pdf(pdf_path: str):
    """Full pipeline: convert PDF → update manifest → push to GitHub."""
    slide_files = convert_pdf_to_images(pdf_path)
    if slide_files:
        write_manifest(slide_files)
        push_to_github()


class PDFHandler(FileSystemEventHandler):
    """Watches for new or modified PDF files."""

    def __init__(self):
        self._debounce = {}

    def _handle(self, path):
        if not path.lower().endswith(".pdf"):
            return
        # Debounce: wait for file to finish writing (some apps write in chunks)
        now = time.time()
        last = self._debounce.get(path, 0)
        if now - last < 5:
            return
        self._debounce[path] = now

        # Brief pause to let the file finish writing
        time.sleep(2)
        process_pdf(path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)


def run_watcher():
    """Start watching the input folder."""
    os.makedirs(WATCH_FOLDER, exist_ok=True)
    os.makedirs(SLIDES_DIR, exist_ok=True)

    log.info(f"Watching folder: {WATCH_FOLDER}")
    log.info(f"Drop a PDF into the folder above to convert and publish.")
    log.info(f"Press Ctrl+C to stop.\n")

    handler = PDFHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_FOLDER, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping watcher...")
        observer.stop()
    observer.join()


def run_once(pdf_path: str):
    """One-shot mode: convert a specific PDF and push."""
    if not os.path.isfile(pdf_path):
        log.error(f"File not found: {pdf_path}")
        sys.exit(1)
    process_pdf(pdf_path)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # One-shot mode: python watcher.py path/to/report.pdf
        run_once(sys.argv[1])
    else:
        # Watcher mode: python watcher.py
        run_watcher()
