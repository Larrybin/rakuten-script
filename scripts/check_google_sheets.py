#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.errors import ProjectError
from lib.google_sheets_helper import get_sheets_service, read_sheet_data


def main():
    parser = argparse.ArgumentParser(description="Google Sheets helper 自检")
    parser.add_argument("--spreadsheet-id", required=True, help="Google Spreadsheet ID")
    parser.add_argument("--range", required=True, help="读取范围，例如 Sheet1!A1:A5")
    args = parser.parse_args()

    try:
        service = get_sheets_service()
        rows = read_sheet_data(args.spreadsheet_id, args.range, service_obj=service)
        print("✅ Google Sheets 连接成功")
        print(f"读取范围: {args.range}")
        print(f"行数: {len(rows)}")
    except ProjectError as exc:
        print(f"❌ Google Sheets 自检失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
