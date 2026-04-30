#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.errors import ProjectError
from lib.fingerprint_utils import (
    get_existing_env_info,
    open_env_with_retry,
    preload_fingerprint_cache,
    set_fullscreen_mode,
)


def main():
    parser = argparse.ArgumentParser(description="AdsPower helper 自检")
    parser.add_argument("--env-serial", required=True, help="AdsPower Local API 真实 serial_number")
    args = parser.parse_args()

    try:
        preload_fingerprint_cache()
        env_info = get_existing_env_info(args.env_serial)
        driver = open_env_with_retry(env_info["env_id"])
        set_fullscreen_mode(driver)
        print("✅ AdsPower 自检成功")
        print(f"profile_id: {env_info['profile_id']}")
        print(f"serial_number: {env_info['serial_number']}")
        print(f"current_url: {driver.current_url}")
        print(f"title: {driver.title}")
    except ProjectError as exc:
        print(f"❌ AdsPower 自检失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
