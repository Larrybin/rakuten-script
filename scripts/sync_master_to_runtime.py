#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.config import get_google_spreadsheet_id
from lib.errors import ProjectError
from lib.google_sheets_helper import get_sheets_service
from lib.runtime_model import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_BLOCKED,
    ACCOUNT_STATUS_MISSING,
    APPLY_STATUS_APPLIED,
    APPLY_STATUS_DISABLED,
    APPLY_STATUS_FAILED,
    APPLY_STATUS_PENDING,
    APPLY_STATUS_SKIPPED,
    BRANLIST_HEADERS,
    BRANLIST_SHEET,
    CATURL_HEADERS,
    CATURL_SHEET,
    KEYWORDS_HEADERS,
    KEYWORDS_SHEET,
    TASK_SOURCE_STATUS_ACTIVE,
    TASK_STATUS_DISABLED,
    TASK_STATUS_PENDING,
    TaskSourceRow,
    SyncSummary,
    append_record,
    build_header_map,
    get_cell,
    index_active_subjects,
    now_iso,
    parse_king_rows,
    parse_task_source_rows,
    read_category_map,
    read_rows_as_records,
    required_headers_present,
    update_sheet_row,
)


@dataclass(frozen=True)
class RuntimeTaskSpec:
    subject_id: str
    env_serial: str
    sheet_name: str
    dedupe_key: str
    row_payload: Dict[str, str]


def _read_runtime_records(spreadsheet_id: str, service, sheet_name: str, headers: List[str]) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    return read_rows_as_records(spreadsheet_id, sheet_name, headers, service)


def _task_source_specs(active_subjects, task_rows, category_map, errors: List[str]) -> List[RuntimeTaskSpec]:
    specs: List[RuntimeTaskSpec] = []
    # 注意：King.类型 只是账号定位标签，不参与 category 任务生成。
    # 真正的执行任务只来自 task_source。
    for row in task_rows:
        subject = active_subjects.get(row.subject_id)
        if not subject:
            continue
        if row.status != TASK_SOURCE_STATUS_ACTIVE:
            continue
        if row.task_type == "keyword":
            specs.append(
                RuntimeTaskSpec(
                    subject_id=row.subject_id,
                    env_serial=subject.env_serial,
                    sheet_name=KEYWORDS_SHEET,
                    dedupe_key=row.task_value.strip().lower(),
                    row_payload={
                        "subject_id": row.subject_id,
                        "env_serial": subject.env_serial,
                        "keyword": row.task_value,
                        "status": TASK_STATUS_PENDING,
                        "last_crawled_at": "",
                        "note": "",
                    },
                )
            )
            continue

        mapping = category_map.get(row.task_value.strip())
        if not mapping:
            errors.append(f"category_map 缺少分类映射: {row.task_value}")
            continue
        specs.append(
            RuntimeTaskSpec(
                subject_id=row.subject_id,
                env_serial=subject.env_serial,
                sheet_name=CATURL_SHEET,
                dedupe_key=row.task_value.strip().lower(),
                row_payload={
                    "subject_id": row.subject_id,
                    "env_serial": subject.env_serial,
                    "category": row.task_value,
                    "url": mapping["url"],
                    "count": "",
                    "status": TASK_STATUS_PENDING,
                    "last_crawled_at": "",
                    "note": "",
                },
            )
        )
    return specs


def _specs_by_subject(task_rows: Iterable[TaskSourceRow]) -> Dict[str, Dict[Tuple[str, str], TaskSourceRow]]:
    grouped: Dict[str, Dict[Tuple[str, str], TaskSourceRow]] = {}
    for row in task_rows:
        grouped.setdefault(row.subject_id, {})[(row.task_type, row.task_value.strip().lower())] = row
    return grouped


def _sync_runtime_sheet(spreadsheet_id: str, service, sheet_name: str, headers: List[str], specs: List[RuntimeTaskSpec]) -> SyncSummary:
    rows, header_map = _read_runtime_records(spreadsheet_id, service, sheet_name, headers)
    summary = SyncSummary()
    spec_map = {(spec.subject_id, spec.dedupe_key): spec for spec in specs if spec.sheet_name == sheet_name}

    for record in rows:
        row_index = int(record["row_index"])
        key_field = "keyword" if sheet_name == KEYWORDS_SHEET else "category"
        current_key = record[key_field].strip().lower()
        spec = spec_map.get((record["subject_id"], current_key))
        current_status = record["status"]
        if spec is None:
            if current_status != TASK_STATUS_DISABLED:
                update_sheet_row(
                    spreadsheet_id,
                    sheet_name,
                    row_index,
                    header_map,
                    {"status": TASK_STATUS_DISABLED, "note": "disabled by sync"},
                    service=service,
                )
                summary = summary.merge(disabled=1)
            continue

        updates = {}
        if record["env_serial"] != spec.env_serial:
            updates["env_serial"] = spec.env_serial
        if sheet_name == CATURL_SHEET and record["url"] != spec.row_payload["url"]:
            updates["url"] = spec.row_payload["url"]
        if current_status == TASK_STATUS_DISABLED:
            updates["status"] = TASK_STATUS_PENDING
            updates["note"] = "restored by sync"
            summary = summary.merge(restored=1)
        elif updates:
            summary = summary.merge(updated=1)
        if updates:
            update_sheet_row(spreadsheet_id, sheet_name, row_index, header_map, updates, service=service)

    existing_keys = {
        (record["subject_id"], record["keyword"].strip().lower() if sheet_name == KEYWORDS_SHEET else record["category"].strip().lower())
        for record in rows
    }
    for spec in specs:
        if spec.sheet_name != sheet_name:
            continue
        key = (spec.subject_id, spec.dedupe_key)
        if key in existing_keys:
            continue
        append_record(spreadsheet_id, sheet_name, headers, spec.row_payload, service=service)
        summary = summary.merge(created=1)

    return summary


def _sync_branlist(spreadsheet_id: str, service, active_subjects, all_subjects) -> SyncSummary:
    rows, header_map = _read_runtime_records(spreadsheet_id, service, BRANLIST_SHEET, BRANLIST_HEADERS)
    summary = SyncSummary()
    for record in rows:
        row_index = int(record["row_index"])
        subject_id = record["subject_id"]
        apply_status = record["apply_status"]
        subject = all_subjects.get(subject_id)

        if subject is None or subject.account_status in {ACCOUNT_STATUS_BLOCKED, ACCOUNT_STATUS_MISSING}:
            if apply_status in {"", APPLY_STATUS_PENDING}:
                update_sheet_row(
                    spreadsheet_id,
                    BRANLIST_SHEET,
                    row_index,
                    header_map,
                    {"apply_status": APPLY_STATUS_DISABLED, "note": "disabled by sync"},
                    service=service,
                )
                summary = summary.merge(disabled=1)
            continue

        if record["env_serial"] != subject.env_serial and apply_status in {"", APPLY_STATUS_PENDING}:
            update_sheet_row(
                spreadsheet_id,
                BRANLIST_SHEET,
                row_index,
                header_map,
                {"env_serial": subject.env_serial},
                service=service,
            )
            summary = summary.merge(updated=1)
    return summary


def sync_master_to_runtime(spreadsheet_id: str, service) -> Tuple[SyncSummary, List[str]]:
    errors: List[str] = []
    king_rows, king_errors = parse_king_rows(spreadsheet_id, service)
    errors.extend(king_errors)
    active_subjects, active_errors = index_active_subjects(king_rows)
    errors.extend(active_errors)
    all_subjects = {row.subject_id: row for row in king_rows}

    task_rows, task_errors = parse_task_source_rows(spreadsheet_id, service)
    errors.extend(task_errors)
    category_map, category_errors = read_category_map(spreadsheet_id, service)
    errors.extend(category_errors)

    specs = _task_source_specs(active_subjects, task_rows, category_map, errors)

    summary = SyncSummary(errors=len(errors))
    summary = summary.merge(**_sync_runtime_sheet(spreadsheet_id, service, CATURL_SHEET, CATURL_HEADERS, specs).__dict__)
    summary = summary.merge(**_sync_runtime_sheet(spreadsheet_id, service, KEYWORDS_SHEET, KEYWORDS_HEADERS, specs).__dict__)
    summary = summary.merge(**_sync_branlist(spreadsheet_id, service, active_subjects, all_subjects).__dict__)
    summary = summary.merge(mapping_missing=sum(1 for item in errors if item.startswith("category_map 缺少分类映射")))
    summary = SyncSummary(
        created=summary.created,
        restored=summary.restored,
        disabled=summary.disabled,
        updated=summary.updated,
        mapping_missing=summary.mapping_missing,
        errors=len(errors),
    )
    return summary, errors


def main():
    parser = argparse.ArgumentParser(description="同步 King/task_source 到运行表")
    parser.add_argument("--spreadsheet-id", help="Google Spreadsheet ID，默认读取 .env")
    args = parser.parse_args()
    spreadsheet_id = args.spreadsheet_id or get_google_spreadsheet_id()

    try:
        service = get_sheets_service()
        summary, errors = sync_master_to_runtime(spreadsheet_id, service)
        print("✅ 同步完成")
        print(f"created={summary.created} restored={summary.restored} disabled={summary.disabled} updated={summary.updated} mapping_missing={summary.mapping_missing} errors={summary.errors}")
        if errors:
            print("同步错误:")
            for item in errors:
                print(f"- {item}")
            raise SystemExit(1)
    except ProjectError as exc:
        print(f"❌ 同步失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
