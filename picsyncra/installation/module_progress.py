"""Controller-owned download measurements shared by launcher and WEB."""
from time import monotonic
import math


class DownloadProgress:
    def __init__(self, *, clock=monotonic):
        self.clock = clock
        self.started = None

    def update(self, value):
        now = self.clock()
        if self.started is None: self.started = now
        elapsed = now - self.started
        downloaded, total = value['downloaded_bytes'], value['total_bytes']
        rate = max(0, downloaded / elapsed) if elapsed > 0 else 0
        return dict(value, bytes_per_second=round(rate, 1),
                    eta_seconds=math.ceil(max(0, total - downloaded) / rate) if rate > 0 else None)
