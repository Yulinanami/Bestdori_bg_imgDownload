import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from common import BG_LIST_URL, HEADERS, wait_if_paused_sync
from stats import DownloadStats


def scan_all_scenarios(
    output_dir,
    batch_size,
    pause_event,
    log,
    update_progress,
    stats: DownloadStats | None = None,
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

        scanned = 0
        batch_map = {}

        for scen in scenarios:
            wait_if_paused_sync(pause_event)
            time.sleep(0.5)  # 每个 scenario 间隔 0.5s

            url = f"{BG_LIST_URL}/{scen}"
            log(f"\n[+] 扫描 {scen} -> {url}")
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
            if not goto_ok:
                log(f"    [err] {scen} 页面多次超时，已跳过")
                continue

            try:
                page.wait_for_selector("div.image img", timeout=20000)
            except PlaywrightTimeoutError:
                log(f"    [warn] {scen} 页面找不到图片元素或加载过慢，跳过")
                continue

            imgs = page.query_selector_all("div.image img")
            if not imgs:
                log(f"    [warn] {scen} 无图片，跳过")
                continue

            alts = []
            for img in imgs:
                alt = img.get_attribute("alt")
                if alt:
                    alts.append(alt)

            # 统计这个 scenario 下的图片总数
            if stats is not None:
                stats.add_total(len(alts))

            batch_map[scen] = alts
            scanned += 1

            if update_progress:
                update_progress(scanned, total)

            log(f"    [info] {scen} 发现 {len(alts)} 张图片")

            # 凑满一批就产出
            if scanned % batch_size == 0:
                yield batch_map
                batch_map = {}

        # 最后一批（不足 batch_size）
        if batch_map:
            yield batch_map

        browser.close()
