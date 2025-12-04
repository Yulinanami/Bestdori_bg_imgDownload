import os
import asyncio
import threading
import queue
from urllib.parse import urljoin
import aiohttp
from common import BASE_URL, HEADERS, wait_if_paused_sync, wait_if_paused_async
from stats import DownloadStats 


async def download_image(
    session,
    sem,
    scenario_name,
    alt,
    output_dir,
    pause_event,
    log,
    max_retries=5,
    base_delay=0.5,
    stats: DownloadStats | None = None,
):
    """下载单张图片，带重试 + 指数退避"""
    asset_path = f"/assets/jp/bg/{scenario_name}_rip/{alt}"
    img_url = urljoin(BASE_URL, asset_path)

    save_dir = os.path.join(output_dir, scenario_name)
    os.makedirs(save_dir, exist_ok=True)

    filepath = os.path.join(save_dir, alt)
    if os.path.exists(filepath):
        log(f"    [skip] {scenario_name}/{alt} 已存在")
        # 已存在也视为“成功下载过”
        if stats is not None:
            stats.add_success()
        return True

    async with sem:
        for attempt in range(1, max_retries + 1):
            await wait_if_paused_async(pause_event)

            try:
                async with session.get(img_url) as resp:
                    if resp.status != 200:
                        raise aiohttp.ClientResponseError(
                            resp.request_info,
                            resp.history,
                            status=resp.status,
                            message=f"HTTP {resp.status}",
                        )

                    content = await resp.read()

                    if len(content) < 500:
                        raise Exception(f"内容过小 ({len(content)} bytes)")

                    with open(filepath, "wb") as f:
                        f.write(content)

                    log(f"    [dl] {scenario_name}/{alt}  <- {img_url}")

                    # 统计成功
                    if stats is not None:
                        stats.add_success()

                    return True

            except Exception as e:
                log(f"    [warn] 下载失败: {e} (尝试 {attempt}/{max_retries})")

                await asyncio.sleep(base_delay * attempt)

        log(f"    [err] {scenario_name}/{alt} 完全失败（重试 {max_retries} 次）")
        if stats is not None:
            stats.add_failure(scenario_name, alt)

        return False


async def download_batch(
    batch_map,
    max_concurrency,
    output_dir,
    pause_event,
    log,
    stats: DownloadStats | None = None,
):
    """下载一个批次里的所有图片"""
    timeout = aiohttp.ClientTimeout(total=60)
    connector = aiohttp.TCPConnector(limit=max_concurrency)
    sem = asyncio.Semaphore(max_concurrency)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=HEADERS,
    ) as session:
        tasks = []
        for scen, alts in batch_map.items():
            for alt in alts:
                tasks.append(
                    download_image(
                        session,
                        sem,
                        scen,
                        alt,
                        output_dir,
                        pause_event,
                        log,
                        stats=stats,
                    )
                )

        log(f"\n[+] 本批次准备下载 {len(tasks)} 张图片（并发 {max_concurrency}）")

        success = 0
        for coro in asyncio.as_completed(tasks):
            if await coro:
                success += 1

        log(f"[+] 本批次完成：成功 {success} 张 / 共 {len(tasks)} 张")


def download_worker(
    batch_queue: "queue.Queue[dict]",
    pause_event: threading.Event,
    stop_event: threading.Event,
    output_dir: str,
    max_concurrency: int,
    log,
    on_all_done,
    stats: DownloadStats | None = None,
):
    """
    独立下载线程：
      - 自己创建 asyncio 事件循环
      - 从 batch_queue 里取批次
      - 对每个批次调用 download_batch
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while True:
            batch = batch_queue.get()
            if batch is None:
                # 哨兵：扫描完成
                break
            if stop_event.is_set():
                break

            wait_if_paused_sync(pause_event)

            try:
                loop.run_until_complete(
                    download_batch(
                        batch,
                        max_concurrency,
                        output_dir,
                        pause_event,
                        log,
                        stats=stats,  # ✅ 把统计对象传入
                    )
                )
            except Exception as e:
                import traceback

                traceback.print_exc()
                log(f"[错误] 下载批次时出现异常: {e!r}")

        log("=== 所有批次下载完成 ===")
    finally:
        loop.close()
        if on_all_done:
            on_all_done()
