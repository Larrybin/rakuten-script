#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.config import get_google_spreadsheet_id
from lib.errors import ProjectError
from lib.google_sheets_helper import get_sheets_service
from lib.runtime_model import ensure_king_status_column, ensure_runtime_sheets


def main():
    parser = argparse.ArgumentParser(description="初始化 Rakuten 运行表布局")
    parser.add_argument("--spreadsheet-id", help="Google Spreadsheet ID，默认读取 .env")
    args = parser.parse_args()

    spreadsheet_id = args.spreadsheet_id or get_google_spreadsheet_id()
    try:
        service = get_sheets_service()
        created = ensure_runtime_sheets(spreadsheet_id, service)
        king_updated = ensure_king_status_column(spreadsheet_id, service)
        print("✅ 工作表布局初始化完成")
        print(f"Spreadsheet ID: {spreadsheet_id}")
        print(f"新建工作表: {', '.join(created) if created else '无'}")
        print(f"King 新增乐天状态列: {'是' if king_updated else '否'}")
    except ProjectError as exc:
        print(f"❌ 初始化失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
