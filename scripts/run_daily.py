#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import rakuten_aff_apply
import rakuten_aff_offer
from lib.config import get_google_spreadsheet_id
from lib.errors import ProjectError
from lib.google_sheets_helper import get_sheets_service
from lib.runtime_model import index_active_subjects, parse_king_rows
from scripts.sync_master_to_runtime import sync_master_to_runtime


def main():
    parser = argparse.ArgumentParser(description="执行每日 Rakuten 自动化")
    parser.add_argument("--skip-apply", action="store_true", help="只跑采集，不跑申请")
    parser.add_argument("-n", "--num", type=int, default=None, help="申请阶段每个主体本次执行处理的品牌数量上限")
    args = parser.parse_args()

    spreadsheet_id = get_google_spreadsheet_id()
    service = get_sheets_service()
    failures = []

    try:
        summary, sync_errors = sync_master_to_runtime(spreadsheet_id, service)
        print(f"INFO: sync summary created={summary.created} restored={summary.restored} disabled={summary.disabled} updated={summary.updated}")
        if sync_errors:
            for item in sync_errors:
                print(f"WARN: sync error: {item}")

        rows, parse_errors = parse_king_rows(spreadsheet_id, service)
        active_subjects, active_errors = index_active_subjects(rows)
        for item in parse_errors + active_errors:
            print(f"WARN: King 数据问题: {item}")

        for subject in active_subjects.values():
            print(f"INFO: 开始执行主体 {subject.subject_id} env_serial={subject.env_serial}")
            offer_ok = rakuten_aff_offer.process(
                subject_id=subject.subject_id,
                env_serial=subject.env_serial,
                email=subject.rakuten_account,
                password=subject.rakuten_password,
            )
            if not offer_ok:
                failures.append(f"offer:{subject.subject_id}")
                continue
            if args.skip_apply:
                continue
            apply_ok = rakuten_aff_apply.process(
                subject_id=subject.subject_id,
                env_serial=subject.env_serial,
                email=subject.rakuten_account,
                password=subject.rakuten_password,
                limit=args.num,
            )
            if not apply_ok:
                failures.append(f"apply:{subject.subject_id}")
    except ProjectError as exc:
        print(f"❌ run_daily 失败: {type(exc).__name__}: {exc}")
        sys.exit(1)

    print(f"INFO: run_daily 完成，失败数={len(failures)}")
    for item in failures:
        print(f"- {item}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
