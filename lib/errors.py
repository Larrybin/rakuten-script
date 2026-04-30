class ProjectError(Exception):
    """项目内底座错误的统一父类。"""


class ConfigError(ProjectError):
    """本地配置错误。"""


class SheetsError(ProjectError):
    """Google Sheets 相关错误。"""


class SheetsAuthError(SheetsError):
    """Google Sheets 认证失败。"""


class SheetsApiError(SheetsError):
    """Google Sheets API 调用失败。"""


class AdsPowerError(ProjectError):
    """AdsPower 相关错误。"""


class AdsPowerApiError(AdsPowerError):
    """AdsPower API 调用失败。"""


class AdsPowerLaunchError(AdsPowerError):
    """AdsPower 启动或浏览器接管失败。"""


class RakutenApiError(ProjectError):
    """Rakuten Advertising API 调用失败。"""
