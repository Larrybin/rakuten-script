from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib.config import get_google_spreadsheet_id
from lib.errors import ConfigError
from lib.google_sheets_helper import (
    append_rows_to_sheet,
    batch_update_spreadsheet,
    get_spreadsheet_metadata,
    read_sheet_data,
    write_sheet_data,
)

KING_SHEET = "King"
TASK_SOURCE_SHEET = "task_source"
CATEGORY_MAP_SHEET = "category_map"
CATURL_SHEET = "caturl"
KEYWORDS_SHEET = "keywords"
BRANLIST_SHEET = "branlist"
APPLY_WINDOW_SHEET = "apply_window"
APPLY_LOG_SHEET = "apply_log"
PARTNERSHIP_DEEPLINKS_SHEET = "partnership_deeplinks"

KING_REQUIRED_HEADERS = [
    "指纹id",
    "乐天账号",
    "乐天密码",
    "乐天状态",
]
KING_RAKUTEN_API_HEADERS = [
    "RAKUTEN_ACCOUNT_ID",
    "RAKUTEN_CLIENT_ID",
    "RAKUTEN_CLIENT_SECRET",
]
TASK_SOURCE_HEADERS = [
    "乐天账号",
    "task_type",
    "task_value",
    "status",
    "note",
]
CATEGORY_MAP_HEADERS = [
    "category",
    "url",
    "updated_at",
    "note",
]
CATURL_HEADERS = [
    "subject_id",
    "env_serial",
    "category",
    "url",
    "count",
    "status",
    "last_crawled_at",
    "note",
]
KEYWORDS_HEADERS = [
    "subject_id",
    "env_serial",
    "keyword",
    "status",
    "last_crawled_at",
    "note",
]
BRANLIST_HEADERS = [
    "subject_id",
    "env_serial",
    "category",
    "brand",
    "brand_url",
    "apply_status",
    "note",
    "source_type",
    "search_keyword",
    "discovered_at",
]
APPLY_WINDOW_HEADERS = [
    "subject_id",
    "env_serial",
    "window_start",
    "window_end",
    "limit",
    "status",
]
APPLY_LOG_HEADERS = [
    "subject_id",
    "env_serial",
    "brand",
    "brand_url",
    "applied_at",
    "result",
    "note",
]
PARTNERSHIP_DEEPLINKS_HEADERS = [
    "subject_id",
    "env_serial",
    "advertiser_id",
    "advertiser_name",
    "advertiser_url",
    "ships_to",
    "partnership_status",
    "advertiser_status",
    "deep_links_enabled",
    "homepage_deeplink",
    "u1",
    "approved_at",
    "status_updated_at",
    "synced_at",
    "note",
]

TASK_STATUS_PENDING = "pending"
TASK_STATUS_DONE = "done"
TASK_STATUS_PARTIAL = "partial"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_DISABLED = "disabled"
TASK_SOURCE_STATUS_ACTIVE = "active"
TASK_SOURCE_STATUS_DISABLED = "disabled"
ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_BLOCKED = "blocked"
ACCOUNT_STATUS_MISSING = "missing"
APPLY_STATUS_PENDING = "pending"
APPLY_STATUS_APPLIED = "applied"
APPLY_STATUS_SKIPPED = "skipped"
APPLY_STATUS_FAILED = "failed"
APPLY_STATUS_DISABLED = "disabled"
WINDOW_STATUS_ACTIVE = "active"
APPLY_LOG_RESULT = "applied"

TASK_SHEETS = {
    TASK_SOURCE_SHEET: TASK_SOURCE_HEADERS,
    CATEGORY_MAP_SHEET: CATEGORY_MAP_HEADERS,
    CATURL_SHEET: CATURL_HEADERS,
    KEYWORDS_SHEET: KEYWORDS_HEADERS,
    BRANLIST_SHEET: BRANLIST_HEADERS,
    APPLY_WINDOW_SHEET: APPLY_WINDOW_HEADERS,
    APPLY_LOG_SHEET: APPLY_LOG_HEADERS,
    PARTNERSHIP_DEEPLINKS_SHEET: PARTNERSHIP_DEEPLINKS_HEADERS,
}

ACCOUNT_STATUS_ALIASES = {
    "active": ACCOUNT_STATUS_ACTIVE,
    "活着": ACCOUNT_STATUS_ACTIVE,
    "正常": ACCOUNT_STATUS_ACTIVE,
    "可用": ACCOUNT_STATUS_ACTIVE,
    "blocked": ACCOUNT_STATUS_BLOCKED,
    "被封": ACCOUNT_STATUS_BLOCKED,
    "封禁": ACCOUNT_STATUS_BLOCKED,
    "停用": ACCOUNT_STATUS_BLOCKED,
    "不可用": ACCOUNT_STATUS_BLOCKED,
    "需要人脸验证": ACCOUNT_STATUS_BLOCKED,
    "missing": ACCOUNT_STATUS_MISSING,
    "缺失": ACCOUNT_STATUS_MISSING,
    "无账号": ACCOUNT_STATUS_MISSING,
}


def normalize_subject_id(value: str) -> str:
    return (value or "").strip().lower()


def normalize_text(value: str) -> str:
    return (value or "").strip()


def normalize_task_value(value: str) -> str:
    return normalize_text(value).lower()


def normalize_account_status(value: str) -> str:
    raw = normalize_text(value).lower()
    if not raw:
        return ""
    if raw in ACCOUNT_STATUS_ALIASES:
        return ACCOUNT_STATUS_ALIASES[raw]
    if any(token in raw for token in ["封", "挂", "异常", "验证", "改媒体"]):
        return ACCOUNT_STATUS_BLOCKED
    if any(token in raw for token in ["缺", "无账号", "没有账号"]):
        return ACCOUNT_STATUS_MISSING
    return raw


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_header_map(headers: Sequence[str]) -> Dict[str, int]:
    return {str(name).strip(): idx for idx, name in enumerate(headers)}


def get_cell(row: Sequence[Any], header_map: Dict[str, int], key: str) -> str:
    idx = header_map.get(key)
    if idx is None or idx >= len(row):
        return ""
    value = row[idx]
    return str(value).strip() if value is not None else ""


def read_sheet_with_headers(spreadsheet_id: str, sheet_name: str, service) -> Tuple[List[str], List[List[str]]]:
    rows = read_sheet_data(spreadsheet_id, sheet_name, service_obj=service) or []
    if not rows:
        return [], []
    return [str(cell).strip() for cell in rows[0]], rows[1:]


def required_headers_present(headers: Sequence[str], required: Sequence[str]) -> bool:
    header_set = {str(item).strip() for item in headers}
    return all(column in header_set for column in required)


def missing_headers(headers: Sequence[str], required: Sequence[str]) -> List[str]:
    header_set = {str(item).strip() for item in headers}
    return [column for column in required if column not in header_set]


def column_letter(index: int) -> str:
    result = ""
    current = index + 1
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def update_sheet_row(
    spreadsheet_id: str,
    sheet_name: str,
    row_number: int,
    header_map: Dict[str, int],
    values: Dict[str, str],
    service=None,
):
    ordered = sorted(
        ((header_map[key], key, values[key]) for key in values if key in header_map),
        key=lambda item: item[0],
    )
    if not ordered:
        return
    start_idx = ordered[0][0]
    end_idx = ordered[-1][0]
    payload = ["" for _ in range(end_idx - start_idx + 1)]
    for col_idx, _, value in ordered:
        payload[col_idx - start_idx] = value
    write_sheet_data(
        [payload],
        spreadsheet_id,
        f"{sheet_name}!{column_letter(start_idx)}{row_number}:{column_letter(end_idx)}{row_number}",
        service_obj=service,
    )


def list_sheet_titles(spreadsheet_id: str, service) -> List[str]:
    metadata = get_spreadsheet_metadata(spreadsheet_id, service_obj=service)
    sheets = metadata.get("sheets", [])
    return [sheet.get("properties", {}).get("title", "") for sheet in sheets]


def ensure_runtime_sheets(spreadsheet_id: str, service) -> List[str]:
    existing_titles = set(list_sheet_titles(spreadsheet_id, service))
    missing_titles = [title for title in TASK_SHEETS if title not in existing_titles]
    if missing_titles:
        requests = [{"addSheet": {"properties": {"title": title}}} for title in missing_titles]
        batch_update_spreadsheet(requests, spreadsheet_id, service_obj=service)
    for sheet_name, headers in TASK_SHEETS.items():
        first_row = read_sheet_data(spreadsheet_id, f"{sheet_name}!1:1", service_obj=service)
        current_headers = first_row[0] if first_row else []
        if current_headers != headers:
            write_sheet_data([headers], spreadsheet_id, f"{sheet_name}!A1", service_obj=service)
    return missing_titles


def ensure_king_status_column(spreadsheet_id: str, service) -> bool:
    headers, _ = read_sheet_with_headers(spreadsheet_id, KING_SHEET, service)
    if not headers:
        raise ConfigError("King 工作表不存在或为空")
    missing_columns = [column for column in ["乐天状态"] + KING_RAKUTEN_API_HEADERS if column not in headers]
    if not missing_columns:
        return False
    write_sheet_data([headers + missing_columns], spreadsheet_id, f"{KING_SHEET}!A1", service_obj=service)
    return True


@dataclass(frozen=True)
class KingRow:
    row_index: int
    env_serial: str
    rakuten_account: str
    rakuten_password: str
    account_status: str
    subject_id: str
    category_hint: str
    rakuten_account_id: str = ""
    rakuten_client_id: str = ""
    rakuten_client_secret: str = ""


@dataclass(frozen=True)
class TaskSourceRow:
    row_index: int
    subject_id: str
    rakuten_account: str
    task_type: str
    task_value: str
    status: str
    note: str


@dataclass(frozen=True)
class SyncSummary:
    created: int = 0
    restored: int = 0
    disabled: int = 0
    updated: int = 0
    mapping_missing: int = 0
    errors: int = 0

    def merge(self, **changes: int) -> "SyncSummary":
        data = {
            "created": self.created,
            "restored": self.restored,
            "disabled": self.disabled,
            "updated": self.updated,
            "mapping_missing": self.mapping_missing,
            "errors": self.errors,
        }
        for key, delta in changes.items():
            data[key] = data.get(key, 0) + delta
        return SyncSummary(**data)


def parse_king_rows(spreadsheet_id: str, service) -> Tuple[List[KingRow], List[str]]:
    headers, rows = read_sheet_with_headers(spreadsheet_id, KING_SHEET, service)
    missing = missing_headers(headers, KING_REQUIRED_HEADERS)
    if missing:
        raise ConfigError(f"King 缺少必要列: {missing}")
    header_map = build_header_map(headers)
    parsed: List[KingRow] = []
    errors: List[str] = []
    for idx, row in enumerate(rows, start=2):
        env_serial = get_cell(row, header_map, "指纹id")
        rakuten_account = get_cell(row, header_map, "乐天账号")
        rakuten_password = get_cell(row, header_map, "乐天密码")
        account_status = normalize_account_status(get_cell(row, header_map, "乐天状态"))
        category_hint = get_cell(row, header_map, "类型")
        rakuten_account_id = get_cell(row, header_map, "RAKUTEN_ACCOUNT_ID")
        rakuten_client_id = get_cell(row, header_map, "RAKUTEN_CLIENT_ID")
        rakuten_client_secret = get_cell(row, header_map, "RAKUTEN_CLIENT_SECRET")
        if not rakuten_account:
            continue
        subject_id = normalize_subject_id(rakuten_account)
        if not account_status:
            if env_serial and rakuten_password:
                account_status = ACCOUNT_STATUS_ACTIVE
            else:
                errors.append(f"King 第 {idx} 行乐天状态为空且无法按迁移期规则推断")
                continue
        if account_status not in {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_BLOCKED, ACCOUNT_STATUS_MISSING}:
            errors.append(f"King 第 {idx} 行乐天状态非法: {account_status}")
            continue
        if account_status == ACCOUNT_STATUS_ACTIVE and (not env_serial or not rakuten_password):
            errors.append(f"King 第 {idx} 行 active 主体缺少指纹id或乐天密码")
            continue
        parsed.append(
            KingRow(
                row_index=idx,
                env_serial=env_serial,
                rakuten_account=rakuten_account,
                rakuten_password=rakuten_password,
                account_status=account_status,
                subject_id=subject_id,
                category_hint=category_hint,
                rakuten_account_id=rakuten_account_id,
                rakuten_client_id=rakuten_client_id,
                rakuten_client_secret=rakuten_client_secret,
            )
        )
    return parsed, errors


def index_active_subjects(rows: Iterable[KingRow]) -> Tuple[Dict[str, KingRow], List[str]]:
    active: Dict[str, KingRow] = {}
    errors: List[str] = []
    for row in rows:
        if row.account_status != ACCOUNT_STATUS_ACTIVE:
            continue
        if row.subject_id in active:
            errors.append(f"King 存在重复 active 乐天账号: {row.rakuten_account}")
            active.pop(row.subject_id, None)
            continue
        active[row.subject_id] = row
    return active, errors


def parse_task_source_rows(spreadsheet_id: str, service) -> Tuple[List[TaskSourceRow], List[str]]:
    headers, rows = read_sheet_with_headers(spreadsheet_id, TASK_SOURCE_SHEET, service)
    missing = missing_headers(headers, TASK_SOURCE_HEADERS)
    if missing:
        raise ConfigError(f"task_source 缺少必要列: {missing}")
    header_map = build_header_map(headers)
    parsed: List[TaskSourceRow] = []
    errors: List[str] = []
    seen = set()
    for idx, row in enumerate(rows, start=2):
        rakuten_account = get_cell(row, header_map, "乐天账号")
        if not rakuten_account:
            continue
        task_type = normalize_text(get_cell(row, header_map, "task_type")).lower()
        task_value = normalize_text(get_cell(row, header_map, "task_value"))
        status = normalize_text(get_cell(row, header_map, "status")).lower() or TASK_SOURCE_STATUS_ACTIVE
        note = get_cell(row, header_map, "note")
        if task_type not in {"keyword", "category"}:
            errors.append(f"task_source 第 {idx} 行 task_type 非法: {task_type}")
            continue
        if status not in {TASK_SOURCE_STATUS_ACTIVE, TASK_SOURCE_STATUS_DISABLED}:
            errors.append(f"task_source 第 {idx} 行 status 非法: {status}")
            continue
        if not task_value:
            errors.append(f"task_source 第 {idx} 行 task_value 为空")
            continue
        subject_id = normalize_subject_id(rakuten_account)
        dedupe_key = (subject_id, task_type, normalize_task_value(task_value))
        if dedupe_key in seen:
            errors.append(f"task_source 第 {idx} 行重复任务: {rakuten_account} / {task_type} / {task_value}")
            continue
        seen.add(dedupe_key)
        parsed.append(
            TaskSourceRow(
                row_index=idx,
                subject_id=subject_id,
                rakuten_account=rakuten_account,
                task_type=task_type,
                task_value=task_value,
                status=status,
                note=note,
            )
        )
    return parsed, errors


def read_category_map(spreadsheet_id: str, service) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    headers, rows = read_sheet_with_headers(spreadsheet_id, CATEGORY_MAP_SHEET, service)
    missing = missing_headers(headers, CATEGORY_MAP_HEADERS)
    if missing:
        raise ConfigError(f"category_map 缺少必要列: {missing}")
    header_map = build_header_map(headers)
    mapping: Dict[str, Dict[str, str]] = {}
    errors: List[str] = []
    for idx, row in enumerate(rows, start=2):
        category = normalize_text(get_cell(row, header_map, "category"))
        if not category:
            continue
        url = normalize_text(get_cell(row, header_map, "url"))
        if not url:
            errors.append(f"category_map 第 {idx} 行缺少 url: {category}")
            continue
        mapping[category] = {
            "category": category,
            "url": url,
            "updated_at": get_cell(row, header_map, "updated_at"),
            "note": get_cell(row, header_map, "note"),
        }
    return mapping, errors


def read_rows_as_records(spreadsheet_id: str, sheet_name: str, headers: Sequence[str], service) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    sheet_headers, rows = read_sheet_with_headers(spreadsheet_id, sheet_name, service)
    if not required_headers_present(sheet_headers, headers):
        raise ConfigError(f"{sheet_name} 缺少必要列: {missing_headers(sheet_headers, headers)}")
    header_map = build_header_map(sheet_headers)
    records = []
    for idx, row in enumerate(rows, start=2):
        record = {"row_index": str(idx)}
        for header in headers:
            record[header] = get_cell(row, header_map, header)
        records.append(record)
    return records, header_map


def append_record(spreadsheet_id: str, sheet_name: str, headers: Sequence[str], record: Dict[str, str], service=None):
    row = [record.get(header, "") for header in headers]
    append_rows_to_sheet([row], spreadsheet_id, sheet_name, service_obj=service)


def get_runtime_spreadsheet_id() -> str:
    return get_google_spreadsheet_id()


def resolve_subject_credentials(spreadsheet_id: str, service, subject_id: str) -> Tuple[str, str, str]:
    rows, errors = parse_king_rows(spreadsheet_id, service)
    if errors:
        raise ConfigError(f"King 数据非法: {errors[0]}")
    matches = [row for row in rows if row.subject_id == normalize_subject_id(subject_id)]
    if not matches:
        raise ConfigError(f"King 中不存在主体: {subject_id}")
    if len(matches) > 1:
        active_matches = [row for row in matches if row.account_status == ACCOUNT_STATUS_ACTIVE]
        if len(active_matches) == 1:
            match = active_matches[0]
        else:
            raise ConfigError(f"King 中主体不唯一: {subject_id}")
    else:
        match = matches[0]
    if match.account_status != ACCOUNT_STATUS_ACTIVE:
        raise ConfigError(f"主体不是 active 状态: {match.rakuten_account}")
    return match.rakuten_account, match.rakuten_password, match.env_serial
