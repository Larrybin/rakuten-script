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
from lib.errors import ConfigError, ProjectError
from lib.google_sheets_helper import get_sheets_service
from lib.runtime_model import index_active_subjects, normalize_subject_id, parse_king_rows


def resolve_subject(service, spreadsheet_id: str, env_serial: str | None, rakuten_account: str | None):
    rows, errors = parse_king_rows(spreadsheet_id, service)
    if errors:
        raise ConfigError(f"King 数据非法: {errors[0]}")
    active_subjects, active_errors = index_active_subjects(rows)
    if active_errors:
        raise ConfigError(active_errors[0])

    if env_serial:
        matches = [row for row in active_subjects.values() if row.env_serial == str(env_serial)]
        if len(matches) != 1:
            raise ConfigError(f"--env-serial 无法唯一命中 active 主体: {env_serial}")
        return matches[0]

    subject_id = normalize_subject_id(rakuten_account or "")
    match = active_subjects.get(subject_id)
    if not match:
        raise ConfigError(f"--rakuten-account 无法命中 active 主体: {rakuten_account}")
    return match


def main():
    parser = argparse.ArgumentParser(description="按主体执行 Rakuten 采集与申请")
    parser.add_argument("--env-serial", help="AdsPower 指纹id")
    parser.add_argument("--rakuten-account", help="乐天账号")
    parser.add_argument("--skip-apply", action="store_true", help="只跑采集，不跑申请")
    parser.add_argument("--close-on-finish", action="store_true", help="执行完成后关闭 AdsPower 浏览器")
    parser.add_argument("-n", "--num", type=int, default=None, help="申请阶段本次执行处理的品牌数量上限")
    args = parser.parse_args()

    if bool(args.env_serial) == bool(args.rakuten_account):
        raise SystemExit("必须且只能提供 --env-serial 或 --rakuten-account 其中之一")

    try:
        spreadsheet_id = get_google_spreadsheet_id()
        service = get_sheets_service()
        subject = resolve_subject(service, spreadsheet_id, args.env_serial, args.rakuten_account)

        if not rakuten_aff_offer.process(
            subject_id=subject.subject_id,
            env_serial=subject.env_serial,
            email=subject.rakuten_account,
            password=subject.rakuten_password,
            close_on_finish=args.close_on_finish and args.skip_apply,
        ):
            raise SystemExit(1)

        if not args.skip_apply:
            if not rakuten_aff_apply.process(
                subject_id=subject.subject_id,
                env_serial=subject.env_serial,
                email=subject.rakuten_account,
                password=subject.rakuten_password,
                limit=args.num,
                close_on_finish=args.close_on_finish,
            ):
                raise SystemExit(1)
    except ProjectError as exc:
        print(f"❌ run_subject 失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
