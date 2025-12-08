import os
import time
import threading
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from common import BG_LIST_URL, HEADERS, wait_if_paused_sync
from stats import DownloadStats

# 极小的 1x1 PNG，用于拦截图片请求时返回占位，避免下载真实图片流量
PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\xdac\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xe1\x00\x00\x00\x00IEND\xaeB`\x82"
)


def scan_all_scenarios(
    output_dir,
    batch_size,
    pause_event,
    log,
    update_progress,
    stats: DownloadStats | None = None,
    stop_event: threading.Event | None = None,
    retry_attempts: int = 3,
):
    """
    分批扫描：
      获取 scenario 列表
      逐个页面扫描图片 alt
      每凑够 batch_size 个 scenario，就 yield 一批 {scenario: [alt...]}
    """
    os.makedirs(output_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])

        def _route_filter(route):
            rtype = route.request.resource_type

            if rtype == "image":
                # 对图片请求返回占位图，触发 onload 但不下载真实资源
                route.fulfill(
                    status=200,
                    headers={"Content-Type": "image/png"},
                    body=PLACEHOLDER_PNG,
                )
            elif rtype in {"media", "font"}:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", _route_filter)

        log(f"[+] 打开 {BG_LIST_URL}")
        page.goto(BG_LIST_URL)
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("table.table-directory span.m-l-xs")

        spans = page.query_selector_all("table.table-directory span.m-l-xs")
        scenarios = sorted(
            {
                span.inner_text().strip()
                for span in spans
                if span.inner_text().strip().startswith("scenario")
            },
            key=lambda x: (
                int(x[len("scenario") :]) if x[len("scenario") :].isdigit() else x
            ),
        )

        total = len(scenarios)
        log(f"[+] 共发现 {total} 个 scenario")
        log(str(scenarios))

        scanned = 0  # 已完成（成功或最终失败）的 scenario 数
        collected = 0  # 已成功解析的 scenario 数
        batch_map = {}

        def _tick_progress():
            nonlocal scanned
            scanned += 1
            if update_progress:
                update_progress(scanned, total)

        remaining = scenarios
        attempt_round = 0

        def _scan_single(scen: str):
            url = f"{BG_LIST_URL}/{scen}"
            log(
                f"\n[+] 扫描 {scen} -> {url} (尝试 {attempt_round + 1}/{retry_attempts + 1})"
            )

            goto_ok = False
            for attempt in range(1, 4):
                try:
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    goto_ok = True
                    break
                except PlaywrightTimeoutError:
                    log(f"    [warn] 打开 {scen} 超时（第 {attempt} 次），准备重试...")
                except Exception as e:
                    log(
                        f"    [warn] 打开 {scen} 失败（第 {attempt} 次）：{e!r}，准备重试..."
                    )
            if not goto_ok:
                log(f"    [warn] {scen} 页面多次失败/超时，本轮跳过")
                return False, []

            try:
                page.wait_for_selector("div.image img", timeout=20000)
            except PlaywrightTimeoutError:
                log(f"    [warn] {scen} 页面找不到图片元素或加载过慢，本轮跳过")
                return False, []
            except Exception as e:
                log(f"    [warn] {scen} 等待图片元素时出错：{e!r}，本轮跳过")
                return False, []

            imgs = page.query_selector_all("div.image img")
            if not imgs:
                log(f"    [warn] {scen} 无图片，跳过")
                return True, []

            alts = []
            for img in imgs:
                alt = img.get_attribute("alt")
                if alt:
                    alts.append(alt)

            return True, alts

        while remaining:
            if stop_event is not None and stop_event.is_set():
                log("[info] 检测到停止信号，结束扫描")
                break

            if attempt_round > 0:
                log(
                    f"[info] 开始第 {attempt_round + 1} 轮重试，共 {len(remaining)} 个待重试 scenario"
                )

            next_remaining = []

            for scen in remaining:
                if stop_event is not None and stop_event.is_set():
                    log("[info] 检测到停止信号，结束扫描")
                    break

                wait_if_paused_sync(pause_event)
                time.sleep(0.5)  # 每个 scenario 间隔 0.5s，降低对 Bestdori 服务器的压力

                try:
                    success, alts = _scan_single(scen)
                except Exception as e:
                    log(f"    [warn] 扫描 {scen} 时出现异常：{e!r}，本轮跳过")
                    success, alts = False, []

                if success:
                    if alts:
                        if stats is not None:
                            stats.add_total(len(alts))

                        batch_map[scen] = alts
                        collected += 1
                        log(f"    [info] {scen} 发现 {len(alts)} 张图片")

                        if collected % batch_size == 0:
                            yield batch_map
                            batch_map = {}
                    else:
                        log(f"    [info] {scen} 未发现图片，跳过下载")

                    _tick_progress()
                else:
                    if attempt_round < retry_attempts:
                        next_remaining.append(scen)
                    else:
                        log(
                            f"    [err] {scen} 在 {retry_attempts + 1} 轮后仍未成功，放弃"
                        )
                        _tick_progress()

            if stop_event is not None and stop_event.is_set():
                break

            remaining = next_remaining
            attempt_round += 1

            if attempt_round > retry_attempts:
                break

        if batch_map and not (stop_event and stop_event.is_set()):
            yield batch_map

        browser.close()
