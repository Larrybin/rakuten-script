#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from datetime import date, datetime
from pathlib import Path
import sys
import time
from typing import Dict, Tuple
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.config import get_google_spreadsheet_id
from lib.errors import ProjectError, RakutenApiError
from lib.google_sheets_helper import append_rows_to_sheet, get_sheets_service
from lib.rakuten_api import RakutenApiClient
from lib.runtime_model import (
    PARTNERSHIP_DEEPLINKS_HEADERS,
    PARTNERSHIP_DEEPLINKS_SHEET,
    build_header_map,
    ensure_runtime_sheets,
    get_cell,
    index_active_subjects,
    now_iso,
    parse_king_rows,
    read_sheet_with_headers,
    update_sheet_row,
)

MAX_LINK_LOCATOR_PAGES = 20


def resolve_subject(spreadsheet_id: str, service, args):
    selected = [value for value in [args.rakuten_account, args.env_serial, args.subject_id] if value]
    if len(selected) > 1:
        raise SystemExit("只能提供 --rakuten-account / --env-serial / --subject-id 其中一个")

    rows, errors = parse_king_rows(spreadsheet_id, service)
    if errors:
        raise SystemExit(f"King 数据非法: {errors[0]}")
    active_subjects, active_errors = index_active_subjects(rows)
    if active_errors:
        raise SystemExit(active_errors[0])

    if args.subject_id:
        subject = active_subjects.get(args.subject_id.strip().lower())
        if not subject:
            raise SystemExit(f"--subject-id 无法命中 active 主体: {args.subject_id}")
        return subject

    if args.rakuten_account:
        subject = active_subjects.get(args.rakuten_account.strip().lower())
        if not subject:
            raise SystemExit(f"--rakuten-account 无法命中 active 主体: {args.rakuten_account}")
        return subject

    if args.env_serial:
        matches = [row for row in active_subjects.values() if row.env_serial == str(args.env_serial)]
        if len(matches) != 1:
            raise SystemExit(f"--env-serial 无法唯一命中 active 主体: {args.env_serial}")
        return matches[0]

    matches = list(active_subjects.values())
    if len(matches) != 1:
        raise SystemExit("King 中 active 主体不唯一，必须提供 --rakuten-account / --env-serial / --subject-id")
    return matches[0]


def read_existing_rows(spreadsheet_id: str, service) -> Tuple[Dict[Tuple[str, str], Dict[str, str]], Dict[str, int]]:
    headers, rows = read_sheet_with_headers(spreadsheet_id, PARTNERSHIP_DEEPLINKS_SHEET, service)
    header_map = build_header_map(headers)
    records = {}
    for idx, row in enumerate(rows, start=2):
        subject_id = get_cell(row, header_map, "subject_id")
        advertiser_id = get_cell(row, header_map, "advertiser_id")
        if not subject_id or not advertiser_id:
            continue
        record = {"row_index": str(idx)}
        for header in PARTNERSHIP_DEEPLINKS_HEADERS:
            record[header] = get_cell(row, header_map, header)
        records[(subject_id, advertiser_id)] = record
    return records, header_map


def upsert_deeplink_row(spreadsheet_id: str, service, existing, header_map, record: Dict[str, str]):
    key = (record["subject_id"], record["advertiser_id"])
    current = existing.get(key)
    if current:
        update_sheet_row(
            spreadsheet_id,
            PARTNERSHIP_DEEPLINKS_SHEET,
            int(current["row_index"]),
            header_map,
            {header: record.get(header, "") for header in PARTNERSHIP_DEEPLINKS_HEADERS},
            service,
        )
        return

    append_rows_to_sheet(
        [[record.get(header, "") for header in PARTNERSHIP_DEEPLINKS_HEADERS]],
        spreadsheet_id,
        PARTNERSHIP_DEEPLINKS_SHEET,
        service_obj=service,
    )


def build_record(subject_id: str, env_serial: str, partnership: Dict, advertiser: Dict, deeplink: str, u1: str, note: str):
    partner_advertiser = partnership.get("advertiser") or {}
    advertiser_id = str(partner_advertiser.get("id") or advertiser.get("id") or "").strip()
    features = advertiser.get("features") or {}
    policies = advertiser.get("policies") or {}
    international_capabilities = policies.get("international_capabilities") or {}
    return {
        "subject_id": subject_id,
        "env_serial": env_serial,
        "advertiser_id": advertiser_id,
        "advertiser_name": str(advertiser.get("name") or partner_advertiser.get("name") or "").strip(),
        "advertiser_url": str(advertiser.get("url") or "").strip(),
        "ships_to": format_ships_to(international_capabilities.get("ships_to")),
        "partnership_status": str(partnership.get("status") or "").strip(),
        "advertiser_status": str(partner_advertiser.get("status") or advertiser.get("status") or "").strip(),
        "deep_links_enabled": str(bool(features.get("deep_links"))).lower(),
        "homepage_deeplink": deeplink,
        "u1": u1,
        "approved_at": str(partnership.get("approve_datetime") or "").strip(),
        "status_updated_at": str(partnership.get("status_update_datetime") or "").strip(),
        "synced_at": now_iso(),
        "note": note,
}


def format_ships_to(value) -> str:
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def normalize_advertiser_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme:
        return raw
    return f"https://{raw}"


def is_transient_rakuten_error(exc: RakutenApiError) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in [
            "429",
            "500",
            "502",
            "503",
            "504",
            "connection",
            "eof",
            "max retries exceeded",
            "proxy",
            "read timed out",
            "remote end closed",
            "temporarily unavailable",
            "timeout",
            "timed out",
        ]
    )


def call_with_transient_retry(operation):
    try:
        return operation()
    except RakutenApiError as exc:
        if not is_transient_rakuten_error(exc):
            raise
        time.sleep(1)
        return operation()


def is_url_template_mismatch(exc: RakutenApiError) -> bool:
    return "URL_TEMPLATE_MISMATCH" in str(exc)


def find_link_locator_fallback(client, advertiser_id: str, advertiser_url: str):
    for link_type, fetch_links in [
        ("text", client.get_text_links),
        ("banner", client.get_banner_links),
    ]:
        best_link = None
        best_score = None
        for page in range(1, MAX_LINK_LOCATOR_PAGES + 1):
            links = call_with_transient_retry(lambda page=page: fetch_links(advertiser_id, page=page))
            if not links:
                break
            for position, link in enumerate(links):
                score = score_link_locator_candidate(link, advertiser_url, page, position)
                if score is None:
                    continue
                if best_score is None or score > best_score:
                    best_score = score
                    best_link = link
        if best_link:
            return link_type, best_link
    return "", {}


def score_link_locator_candidate(link: Dict[str, str], advertiser_url: str, page: int, position: int):
    if not (link.get("clickURL") or "").strip():
        return None
    if is_expired_link(link.get("endDate") or ""):
        return None

    score = 0
    searchable = " ".join(
        str(link.get(field) or "").lower()
        for field in ["linkName", "textDisplay", "categoryName", "landURL"]
    )
    for keyword in ["homepage", "home", "default", "sitewide"]:
        if keyword in searchable:
            score += 20

    advertiser_host = hostname(advertiser_url)
    landing_host = hostname(link.get("landURL") or "")
    if advertiser_host and landing_host:
        if landing_host == advertiser_host:
            score += 50
        elif landing_host.endswith(f".{advertiser_host}") or advertiser_host.endswith(f".{landing_host}"):
            score += 25

    score -= page
    score -= position / 100
    return score


def hostname(url: str) -> str:
    parsed = urlparse(normalize_advertiser_url(url))
    host = (parsed.netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_expired_link(end_date: str) -> bool:
    raw = (end_date or "").strip()
    if not raw:
        return False
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            return datetime.strptime(raw, fmt).date() < date.today()
        except ValueError:
            continue
    return False


def preserve_existing_fields(record: Dict[str, str], existing_record: Dict[str, str], fields):
    for field in fields:
        if existing_record.get(field):
            record[field] = existing_record[field]


def sync_partnership_deeplinks(args) -> int:
    spreadsheet_id = get_google_spreadsheet_id()
    service = get_sheets_service()
    ensure_runtime_sheets(spreadsheet_id, service)
    subject = resolve_subject(spreadsheet_id, service, args)
    subject_id = subject.subject_id
    env_serial = subject.env_serial
    existing, header_map = read_existing_rows(spreadsheet_id, service)
    client = RakutenApiClient.from_credentials(
        subject.rakuten_account_id,
        subject.rakuten_client_id,
        subject.rakuten_client_secret,
    )

    processed = 0
    generated = 0
    skipped = 0
    for partnership in client.iter_partnerships(network=args.network, limit=args.page_size):
        if args.max_brands is not None and processed >= args.max_brands:
            break
        processed += 1

        partner_advertiser = partnership.get("advertiser") or {}
        advertiser_id = str(partner_advertiser.get("id") or "").strip()
        if not advertiser_id:
            skipped += 1
            continue

        existing_record = existing.get((subject_id, advertiser_id), {})
        advertiser = {}
        deeplink = ""
        note = ""
        preserve_fields = []
        try:
            advertiser = call_with_transient_retry(lambda: client.get_advertiser(advertiser_id))
        except RakutenApiError as exc:
            note = f"api error: {exc}"
            preserve_fields = ["advertiser_url", "deep_links_enabled", "homepage_deeplink"]
            skipped += 1
        else:
            advertiser_url = normalize_advertiser_url(advertiser.get("url") or "")
            advertiser["url"] = advertiser_url
            deep_links_enabled = bool((advertiser.get("features") or {}).get("deep_links"))
            if advertiser_url and deep_links_enabled:
                try:
                    deeplink = call_with_transient_retry(
                        lambda: client.create_deep_link(advertiser_id, advertiser_url, args.u1 or "")
                    )
                except RakutenApiError as exc:
                    if is_url_template_mismatch(exc):
                        link_type, fallback = find_link_locator_fallback(client, advertiser_id, advertiser_url)
                        if fallback:
                            deeplink = fallback["clickURL"]
                            note = f"ok via link locator {link_type}"
                            generated += 1
                        else:
                            note = f"api error: {exc}; no link locator fallback"
                            skipped += 1
                    else:
                        note = f"api error: {exc}"
                        preserve_fields = ["homepage_deeplink"]
                        skipped += 1
                else:
                    note = "ok"
                    generated += 1
            elif not advertiser_url:
                note = "advertiser url missing"
                skipped += 1
            else:
                link_type, fallback = find_link_locator_fallback(client, advertiser_id, advertiser_url)
                if fallback:
                    deeplink = fallback["clickURL"]
                    note = f"ok via link locator {link_type}"
                    generated += 1
                else:
                    note = "deep links disabled; no link locator fallback"
                    skipped += 1
        record = build_record(subject_id, env_serial, partnership, advertiser, deeplink, args.u1 or "", note)
        preserve_existing_fields(record, existing_record, preserve_fields)
        upsert_deeplink_row(spreadsheet_id, service, existing, header_map, record)
        if args.sleep:
            time.sleep(args.sleep)

    print(f"INFO: 已检查合作品牌 {processed} 个，生成首页 deeplink {generated} 个，跳过/失败 {skipped} 个")
    return 0


def main():
    parser = argparse.ArgumentParser(description="同步已合作品牌，并生成品牌首页 Rakuten deeplink")
    parser.add_argument("--rakuten-account", help="用 King.乐天账号 标记输出主体")
    parser.add_argument("--env-serial", help="用 King.指纹id 标记输出主体")
    parser.add_argument("--subject-id", help="用 subject_id 标记输出主体，并从 King 读取 Rakuten API 凭据")
    parser.add_argument("--network", help="Rakuten network ID，例如 1=US")
    parser.add_argument("--u1", default="", help="写入 deeplink 的 u1 跟踪值")
    parser.add_argument("--page-size", type=int, default=200, help="Partnerships API 每页数量，最大 200")
    parser.add_argument("--max-brands", type=int, default=None, help="最多处理多少个已合作品牌")
    parser.add_argument("--sleep", type=float, default=0.7, help="每个品牌处理后的等待秒数，用于避开 100 calls/min 限制")
    args = parser.parse_args()
    if args.page_size < 1 or args.page_size > 200:
        raise SystemExit("--page-size 必须在 1 到 200 之间")

    try:
        sys.exit(sync_partnership_deeplinks(args))
    except ProjectError as exc:
        print(f"❌ 同步合作 deeplink 失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
