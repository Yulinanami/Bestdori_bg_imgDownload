import time
import threading
import asyncio

BASE_URL = "https://bestdori.com"
BG_LIST_URL = f"{BASE_URL}/tool/explorer/asset/jp/bg"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def wait_if_paused_sync(pause_event: threading.Event):
    """同步代码里用的“阻塞式暂停”"""
    while pause_event.is_set():
        time.sleep(0.2)


async def wait_if_paused_async(pause_event: threading.Event):
    """异步协程里用的暂停"""
    while pause_event.is_set():
        await asyncio.sleep(0.2)
