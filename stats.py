import threading


class DownloadStats:
    """线程安全的下载统计"""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_images = 0 
        self.success_images = 0 
        self.failed_images = 0 
        self.failed_items = []

    def add_total(self, n: int = 1):
        with self._lock:
            self.total_images += n

    def add_success(self, n: int = 1):
        with self._lock:
            self.success_images += n

    def add_failure(self, scenario_name: str, alt: str):
        with self._lock:
            self.failed_images += 1
            self.failed_items.append((scenario_name, alt))

    def snapshot(self):
        """获取当前统计快照（用于 GUI 展示）"""
        with self._lock:
            return {
                "total": self.total_images,
                "success": self.success_images,
                "failed": self.failed_images,
                "failed_items": list(self.failed_items),
            }
