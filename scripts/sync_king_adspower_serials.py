#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import sys
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.config import get_google_spreadsheet_id
from lib.errors import ConfigError, ProjectError
from lib.fingerprint_utils import _get_profiles_via_list, preload_fingerprint_cache
from lib.google_sheets_helper import get_sheets_service
from lib.runtime_model import (
    KING_SHEET,
    build_header_map,
    get_cell,
    read_sheet_with_headers,
    update_sheet_row,
)


def _normalize(value: str) -> str:
    return str(value or "").strip()


def _rows_for_sync(spreadsheet_id: str, service) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    headers, rows = read_sheet_with_headers(spreadsheet_id, KING_SHEET, service)
    if not headers:
        raise ConfigError("King 工作表不存在或为空")
    if "指纹id" not in headers:
        raise ConfigError("King 缺少必要列: ['指纹id']")
    header_map = build_header_map(headers)
    records = []
    for idx, row in enumerate(rows, start=2):
        records.append(
            {
                "row_index": idx,
                "指纹id": get_cell(row, header_map, "指纹id"),
                "乐天账号": get_cell(row, header_map, "乐天账号"),
                "乐天密码": get_cell(row, header_map, "乐天密码"),
                "乐天状态": get_cell(row, header_map, "乐天状态"),
            }
        )
    return records, header_map


def find_serial_update_plan(
    king_rows: List[Dict[str, str]],
    profiles: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], List[str]]:
    updates: List[Dict[str, str]] = []
    errors: List[str] = []
    by_serial = {_normalize(item.get("serial_number")): item for item in profiles if _normalize(item.get("serial_number"))}
    by_name: Dict[str, List[Dict[str, str]]] = {}
    for profile in profiles:
        name = _normalize(profile.get("name"))
        if not name:
            continue
        by_name.setdefault(name, []).append(profile)

    for row in king_rows:
        fingerprint = _normalize(row.get("指纹id"))
        account = _normalize(row.get("乐天账号"))
        if not fingerprint or not account:
            continue
        if fingerprint in by_serial:
            continue
        name_matches = by_name.get(fingerprint, [])
        if len(name_matches) == 1:
            matched = name_matches[0]
            serial_number = _normalize(matched.get("serial_number"))
            if not serial_number:
                errors.append(f"King 第 {row['row_index']} 行匹配到的 AdsPower profile 缺少 serial_number: {fingerprint}")
                continue
            updates.append(
                {
                    "row_index": row["row_index"],
                    "old_value": fingerprint,
                    "new_value": serial_number,
                    "match_type": "name",
                }
            )
            continue
        if len(name_matches) > 1:
            errors.append(f"King 第 {row['row_index']} 行指纹id值无法唯一匹配 AdsPower profile: {fingerprint}")
            continue
        errors.append(f"King 第 {row['row_index']} 行指纹id值在 AdsPower 中不存在: {fingerprint}")

    return updates, errors


def main():
    parser = argparse.ArgumentParser(description="一次性把 King.指纹id 对齐为 AdsPower Local API 的真实 serial_number")
    parser.add_argument("--spreadsheet-id", help="Google Spreadsheet ID，默认读取 .env")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更计划，不写回 Google Sheets")
    args = parser.parse_args()

    try:
        preload_fingerprint_cache()
        spreadsheet_id = args.spreadsheet_id or get_google_spreadsheet_id()
        service = get_sheets_service()
        king_rows, header_map = _rows_for_sync(spreadsheet_id, service)
        profiles = _get_profiles_via_list()
        updates, errors = find_serial_update_plan(king_rows, profiles)

        print(f"King 行数: {len(king_rows)}")
        print(f"AdsPower profiles: {len(profiles)}")
        print(f"待更新: {len(updates)}")
        print(f"错误: {len(errors)}")

        for item in updates:
            print(f"UPDATE row={item['row_index']} 指纹id: {item['old_value']} -> {item['new_value']} ({item['match_type']})")

        for item in errors:
            print(f"ERROR: {item}")

        if args.dry_run:
            return

        for item in updates:
            update_sheet_row(
                spreadsheet_id,
                KING_SHEET,
                item["row_index"],
                header_map,
                {"指纹id": item["new_value"]},
                service=service,
            )
        print("✅ King.指纹id 已按 AdsPower serial_number 完成写回")
    except ProjectError as exc:
        print(f"❌ sync_king_adspower_serials 失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
