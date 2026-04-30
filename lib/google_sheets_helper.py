import time

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from lib.config import get_google_service_account_file
from lib.errors import ConfigError, SheetsApiError, SheetsAuthError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SERVICE = None
_MAX_API_ATTEMPTS = 3


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        return getattr(exc.resp, "status", None) in {429, 500, 502, 503, 504}
    message = str(exc).lower()
    return any(token in message for token in ["connection reset", "eof", "timed out", "temporarily unavailable"])


def _execute_with_retry(operation, error_message: str):
    last_error = None
    for attempt in range(1, _MAX_API_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt >= _MAX_API_ATTEMPTS or not _is_retryable_error(exc):
                break
            sleep_seconds = 2 ** (attempt - 1)
            print(f"WARN: {error_message}，第 {attempt} 次失败，{sleep_seconds}s 后重试: {exc}")
            time.sleep(sleep_seconds)
    raise SheetsApiError(f"{error_message}: {last_error}") from last_error


def get_sheets_service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE

    service_account_file = get_google_service_account_file()
    try:
        credentials = Credentials.from_service_account_file(
            str(service_account_file),
            scopes=SCOPES,
        )
        _SERVICE = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return _SERVICE
    except FileNotFoundError as exc:
        raise ConfigError(f"Google Service Account 文件不存在: {service_account_file}") from exc
    except ValueError as exc:
        raise SheetsAuthError(f"Google Service Account 文件格式错误: {service_account_file}") from exc
    except Exception as exc:
        raise SheetsAuthError(f"构建 Google Sheets service 失败: {exc}") from exc


def read_sheet_data(spreadsheet_id, range_name, service_obj=None):
    service = service_obj or get_sheets_service()
    def operation():
        response = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_name)
            .execute()
        )
        return response.get("values", [])

    return _execute_with_retry(operation, "读取 Google Sheets 失败")


def write_sheet_data(values, spreadsheet_id, range_name, service_obj=None):
    service = service_obj or get_sheets_service()
    def operation():
        return (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": values},
            )
            .execute()
        )

    return _execute_with_retry(operation, "写入 Google Sheets 失败")


def append_rows_to_sheet(values, spreadsheet_id, sheet_name, service_obj=None):
    service = service_obj or get_sheets_service()
    def operation():
        return (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=sheet_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )

    return _execute_with_retry(operation, "追加写入 Google Sheets 失败")


def get_spreadsheet_metadata(spreadsheet_id, service_obj=None):
    service = service_obj or get_sheets_service()
    return _execute_with_retry(
        lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
        "读取 Spreadsheet 元数据失败",
    )


def batch_update_spreadsheet(requests, spreadsheet_id, service_obj=None):
    service = service_obj or get_sheets_service()
    def operation():
        return (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            )
            .execute()
        )

    return _execute_with_retry(operation, "批量更新 Spreadsheet 失败")


def batch_read_sheet_data(spreadsheet_id, ranges, service_obj=None):
    """一次 API 调用读取多个 Range，减少启动阶段的网络延迟。"""
    service = service_obj or get_sheets_service()
    def operation():
        response = (
            service.spreadsheets()
            .values()
            .batchGet(spreadsheetId=spreadsheet_id, ranges=ranges)
            .execute()
        )
        return [vr.get("values", []) for vr in response.get("valueRanges", [])]

    return _execute_with_retry(operation, "批量读取 Google Sheets 失败")
