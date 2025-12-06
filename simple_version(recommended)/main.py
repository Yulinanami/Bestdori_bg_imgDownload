import asyncio
import os
import hashlib
import aiohttp
from pathlib import Path


BASE_URL = "https://bestdori.com/assets/jp/bg"
# 缺失图片的响应内容大小通常固定14,084 bytes
KNOWN_PLACEHOLDER_SIZES = {14084}
KNOWN_PLACEHOLDER_HASHES: set[str] = set()
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=90, connect=15)
MAX_RETRIES = 4


def build_filename(scenario_number: int, last_digit: int) -> str:
    scen_str = f"{scenario_number:03d}"
    return f"bg0{scen_str}{last_digit}.png"


def build_url(scenario_number: int, last_digit: int) -> str:
    scen_name = f"scenario{scenario_number}"
    filename = build_filename(scenario_number, last_digit)
    return f"{BASE_URL}/{scen_name}_rip/{filename}"


async def download_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    scenario_number: int,
    last_digit: int,
    output_root: Path,
    split_by_scenario: bool,
) -> str | bool:
    url = build_url(scenario_number, last_digit)
    filename = build_filename(scenario_number, last_digit)
    if split_by_scenario:
        save_dir = output_root / f"scenario{scenario_number}"
    else:
        save_dir = output_root

    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 小的等待抖动，降低瞬时并发对服务器的压力
            await asyncio.sleep(0.2 * attempt)
            async with sem:
                async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                    if resp.status != 200:
                        raise aiohttp.ClientResponseError(
                            resp.request_info, resp.history, status=resp.status
                        )

                    content = await resp.read()
                    size = len(content)
                    sha256 = hashlib.sha256(content).hexdigest()

                    if (
                        size in KNOWN_PLACEHOLDER_SIZES
                        or sha256 in KNOWN_PLACEHOLDER_HASHES
                    ):
                        print(
                            f"[skip] {scenario_number}/{filename} 命中占位过滤 (size={size})"
                        )
                        return "skip"

                    with open(save_path, "wb") as f:
                        f.write(content)

                    return True
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            if attempt >= MAX_RETRIES:
                print(
                    f"[warn] {scenario_number}/{filename} 失败: {e} (尝试 {attempt}/{MAX_RETRIES})"
                )
                return False
            await asyncio.sleep(1.5 * attempt)
        except Exception as e:
            if attempt >= MAX_RETRIES:
                print(
                    f"[warn] {scenario_number}/{filename} 失败: {e} (尝试 {attempt}/{MAX_RETRIES})"
                )
                return False
            await asyncio.sleep(1.5 * attempt)


def print_progress(done: int, total: int, success: int, failed: int, skipped: int):
    msg = f"\r进度 {done}/{total} | 成功 {success} | 失败 {failed} | 过滤 {skipped}"
    print(msg, end="", flush=True)


async def download_batch(
    scenarios,
    last_digits,
    output: Path,
    concurrency: int,
    split_by_scenario: bool,
):
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(
        connector=connector, timeout=REQUEST_TIMEOUT
    ) as session:
        sem = asyncio.Semaphore(concurrency)
        tasks = []
        for scen in scenarios:
            for d in last_digits:
                tasks.append(
                    download_one(
                        session,
                        sem,
                        scen,
                        d,
                        output,
                        split_by_scenario,
                    )
                )

        total = len(tasks)
        success = 0
        skipped = 0
        failed = 0
        done = 0
        print_progress(done, total, success, failed, skipped)

        for coro in asyncio.as_completed(tasks):
            result = await coro
            done += 1
            if result == "skip":
                skipped += 1
            elif result:
                success += 1
            else:
                failed += 1
            print_progress(done, total, success, failed, skipped)

    effective_total = total - skipped
    print()  # 换行，避免进度覆盖后续输出
    return success, effective_total, skipped, failed


def prompt_range(default_start: int, default_end: int) -> tuple[int, int]:
    """交互式获取起止编号，允许直接回车使用默认值"""

    def _read(prompt: str, default_val: int) -> int:
        raw = input(prompt).strip()
        if not raw:
            return default_val
        try:
            val = int(raw)
            if val < 0:
                raise ValueError
            return val
        except ValueError:
            print(f"输入无效，使用默认值 {default_val}")
            return default_val

    start = _read(f"请输入起始 scenario 编号（默认 {default_start}）: ", default_start)
    end = _read(f"请输入结束 scenario 编号（默认 {default_end}）: ", default_end)

    if start > end:
        start, end = end, start
        print(f"起始大于结束，已交换为 {start} - {end}")

    return start, end


def main():
    default_start = 0
    default_end = 123
    default_output = "./bg_downloads"
    concurrency = 12

    print("按命名规则下载 Bestdori scenario 背景图（无需扫描网页）")
    print("默认起止为 0-5，可按提示输入覆盖。")
    print(
        f"已启用占位过滤：长度 {sorted(KNOWN_PLACEHOLDER_SIZES)} bytes + 哈希 {len(KNOWN_PLACEHOLDER_HASHES)} 个。"
    )

    start, end = prompt_range(default_start, default_end)
    scenarios = list(range(start, end + 1))
    choice = input("按 scenario 分目录保存? (默认关闭，输入Y/y开启): ").strip().lower()
    split_by_scenario = choice == "y"

    if not scenarios:
        raise SystemExit("未指定有效的 scenario 序号")

    output_input = input(f"请输入输出目录（默认 {default_output}）: ").strip()
    output_path = output_input or default_output
    output = Path(os.path.abspath(output_path))
    output.mkdir(parents=True, exist_ok=True)

    last_digits = list(range(10)) 

    print(f"准备下载 scenario {scenarios}，每个尝试文件 bg0###(0-9).png")
    print(f"输出目录: {output}")
    print(f"并发: {concurrency}，按 scenario 分目录: {split_by_scenario}")

    success, total, skipped, failed = asyncio.run(
        download_batch(
            scenarios,
            last_digits,
            output,
            concurrency,
            split_by_scenario,
        )
    )

    print(
        f"完成: {success}/{total} 成功，失败 {failed}，占位过滤 {skipped}（不计入总数）"
    )


if __name__ == "__main__":
    main()
