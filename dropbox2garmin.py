import logging
import os
import signal
import sys
import time
from pathlib import Path

from garminconnect import Garmin
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger("dropbox2garmin")


class UploadState:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.uploaded: set[str] = set()
        if self.path.exists():
            self.uploaded = {
                line.strip()
                for line in self.path.read_text().splitlines()
                if line.strip()
            }

    def contains(self, basename: str) -> bool:
        return basename in self.uploaded

    def add(self, basename: str):
        self.uploaded.add(basename)
        with self.path.open("a") as f:
            f.write(basename + "\n")


class GarminUploader:
    def __init__(self, email: str, password: str, token_dir: str):
        self.email = email
        self.password = password
        self.token_dir = token_dir
        self.client: Garmin | None = None

    def connect(self):
        self.client = Garmin(self.email, self.password)
        self.client.login(tokenstore=self.token_dir)
        log.info("Connected to Garmin Connect")

    def upload(self, path: Path) -> bool:
        try:
            self.client.upload_activity(str(path))
            return True
        except Exception as e:
            if "409" in str(e):
                log.info("Already on Garmin (duplicate): %s", path.name)
                return True
            # Try re-auth once
            log.warning("Upload failed (%s), reconnecting...", e)
            try:
                self.connect()
                self.client.upload_activity(str(path))
                return True
            except Exception as e2:
                if "409" in str(e2):
                    log.info("Already on Garmin (duplicate): %s", path.name)
                    return True
                log.error("Upload failed after retry: %s", e2)
                return False


class FitFileHandler(FileSystemEventHandler):
    def __init__(self, uploader: GarminUploader, state: UploadState):
        self.uploader = uploader
        self.state = state

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".fit":
            return
        # Wait for Dropbox to finish writing
        time.sleep(2)
        upload_file(path, self.uploader, self.state)


def upload_file(path: Path, uploader: GarminUploader, state: UploadState):
    basename = path.name
    if state.contains(basename):
        log.debug("Already uploaded: %s", basename)
        return
    log.info("Uploading %s", basename)
    if uploader.upload(path):
        state.add(basename)
        log.info("Uploaded %s", basename)


def scan_existing(watch_dir: Path, uploader: GarminUploader, state: UploadState):
    fit_files = sorted(watch_dir.glob("*.fit"))
    for path in fit_files:
        upload_file(path, uploader, state)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    watch_dir = Path(
        os.environ.get("DROPBOX_WATCH_DIR", "~/Dropbox/Apps/WahooFitness")
    ).expanduser()
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        log.error("GARMIN_EMAIL and GARMIN_PASSWORD environment variables are required")
        sys.exit(1)
    token_dir = os.environ.get(
        "GARMIN_TOKEN_DIR", str(Path.home() / ".garminconnect")
    )
    state_file = Path(
        os.environ.get(
            "DROPBOX_STATE_FILE",
            str(Path.home() / ".local/state/dropbox2garmin/uploaded.txt"),
        )
    ).expanduser()

    if not watch_dir.is_dir():
        log.error("Watch directory does not exist: %s", watch_dir)
        sys.exit(1)

    uploader = GarminUploader(email, password, token_dir)
    uploader.connect()

    state = UploadState(state_file)
    log.info("Loaded %d previously uploaded files", len(state.uploaded))

    log.info("Scanning existing files in %s", watch_dir)
    scan_existing(watch_dir, uploader, state)

    handler = FitFileHandler(uploader, state)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()
    log.info("Watching %s for new .fit files", watch_dir)

    stop = False

    def handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not stop:
        time.sleep(60)

    log.info("Shutting down")
    observer.stop()
    observer.join()
