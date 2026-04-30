"""
env_manager.py
==============
HubStudio 指纹环境打开逻辑。
"""

from lib.fingerprint_utils import (
    ensure_chrome_version,
    get_existing_env_info,
    open_env_with_retry,
    set_fullscreen_mode,
)


def open_env_by_serial(env_serial: str):
    """
    根据指纹序号打开 HubStudio 环境。
    缓存查找 → 版本回退保底 → 打开浏览器
    """
    try:
        print(f"INFO: 准备打开指纹环境 (序号: {env_serial})")
        env_id = None
        core_version = None

        try:
            env_seq = int(str(env_serial).strip())
            existing_env = get_existing_env_info(env_seq)
            if existing_env:
                env_id = str(existing_env["env_id"])
                core_version = existing_env.get("core_version")
                print(f"INFO: 缓存命中 env_id={env_id}, Chrome版本={core_version}")
        except (ValueError, TypeError):
            pass

        if not env_id:
            print(f"ERROR: 未能通过序号 {env_serial} 找到指纹")
            return None, None

        if core_version and core_version >= 145:
            fallback_versions = [core_version, 145, 140, 137, 135, 133, 130]
        else:
            fallback_versions = [145, 140, 137, 135, 133, 130]

        seen = set()
        for version in fallback_versions:
            if version in seen:
                continue
            seen.add(version)
            print(f"INFO: 尝试内核版本 {version} ...")
            ensure_chrome_version(env_id, target_version=version, core_version=core_version)
            driver = open_env_with_retry(env_id, max_retries=2, page_load_timeout=60)
            if driver:
                print(f"✅ 内核版本 {version} 启动成功")
                set_fullscreen_mode(driver)
                return driver, env_id
            print(f"WARN: 版本 {version} 失败，尝试更低版本...")

        print(f"ERROR: 环境 {env_id} 所有内核版本均启动失败")
        return None, None
    except Exception as e:
        print(f"ERROR: 打开指纹环境失败: {e}")
        return None, None
