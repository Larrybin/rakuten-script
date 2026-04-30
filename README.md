# Rakuten Script

Rakuten Advertising Publisher 自动化脚本已经收敛为“按乐天账号治理”的工作流：

- `King`：账号资产总表
- `task_source`：结构化任务源，一行一个 `keyword/category`
- `category_map`：分类到 Rakuten URL 的映射
- 运行表：`caturl` / `keywords` / `branlist` / `apply_window` / `apply_log` / `partnership_deeplinks`

正式日常入口：

- [`scripts/init_sheet_layout.py`](./scripts/init_sheet_layout.py)
- [`scripts/sync_master_to_runtime.py`](./scripts/sync_master_to_runtime.py)
- [`scripts/run_subject.py`](./scripts/run_subject.py)
- [`scripts/run_daily.py`](./scripts/run_daily.py)

## 安装

建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

可以用初始化脚本一次性创建任务工作表和标准表头。

## 本地配置

复制模板：

```bash
cp .env.example .env
```

需要填写：

```env
GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/google-service-account.json
GOOGLE_SPREADSHEET_ID=
ADSPOWER_API_BASE=http://127.0.0.1:50325
ADSPOWER_API_KEY=
```

说明：

- `GOOGLE_SERVICE_ACCOUNT_FILE` 支持相对路径，基于项目根目录解析
- `GOOGLE_SPREADSHEET_ID` 是目标 Google Sheet 的 ID
- `ADSPOWER_API_BASE` 默认是 AdsPower Local API 本地端口
- `ADSPOWER_API_KEY` 如果你的 AdsPower 没开鉴权，可以留空
- Rakuten API 凭据不再从本地 `.env` 读取，统一维护在 Google Sheet 的 `King` 表

## Google Sheets 前置条件

- 当前实现只支持 Service Account JSON
- 你必须把该 Service Account 的邮箱加入目标 Google Spreadsheet 协作者，否则会报 403
- helper 内部会自动加载 `.env` 并读取 `GOOGLE_SERVICE_ACCOUNT_FILE`
- `King` 表需要维护 `RAKUTEN_ACCOUNT_ID` / `RAKUTEN_CLIENT_ID` / `RAKUTEN_CLIENT_SECRET` 三列；`scripts/init_sheet_layout.py` 会自动补齐缺失表头

## AdsPower 前置条件

- 当前实现只支持 AdsPower + Selenium
- 只支持 Chromium 内核 profile
- `King.指纹id` 必须填写 AdsPower Local API 可直接查询到的真实 `serial_number`
- 运行期不会再猜测 `King.指纹id` 是名称、视觉序号还是别的字段
- 如果你历史总表里填的不是 `serial_number`，先运行一次：

```bash
python3 scripts/sync_king_adspower_serials.py --dry-run
python3 scripts/sync_king_adspower_serials.py
```

- 浏览器接管主路径固定为：
  - 启动 AdsPower profile
  - 解析 `debug_port`
  - 用 Selenium `debuggerAddress` attach

## 总表与运行表

当前库直接读取 `King`，但不再使用 `important`。

主体规则：

- `subject_id = normalize(乐天账号)`
- `env_serial = King.指纹id = AdsPower Local API 真实 serial_number`
- 24 小时额度按 `subject_id` 统计
- `env_serial` 只保留为审计信息

`King` 依赖列：

- `指纹id`
- `乐天账号`
- `乐天密码`
- `乐天状态`

解析规则：

- 没有 `乐天账号` 的行直接跳过，不参与 Rakuten 自动化
- `指纹id` 列必须存真实 `serial_number`，不是 AdsPower UI 名称，也不是人工视觉排序号
- `类型` 只是账号定位标签，不参与 category 任务自动生成
- category 任务只能来自 `task_source`

`乐天状态` 枚举：

- `active`
- `blocked`
- `missing`

结构化任务源 `task_source`：

```text
乐天账号 | task_type | task_value | status | note
```

约束：

- `task_type`: `keyword` / `category`
- `status`: `active` / `disabled`
- `task_type=category` 时，`task_value` 必须是你显式维护的任务分类名
- 不能把 `King.类型` 直接当成 `task_source.category`

分类映射 `category_map`：

```text
category | url | updated_at | note
```

运行表继续使用：

- `caturl`
- `keywords`
- `branlist`
- `apply_window`
- `apply_log`
- `partnership_deeplinks`

第一版不做：

- `important` 复用
- 分类自动发现
- 手工长期维护 `caturl/keywords`

## Google Sheets 表结构

### `caturl`

```text
subject_id | env_serial | category | url | count | status | last_crawled_at | note
```

说明：

- `subject_id`：运行主体 ID，固定等于规范化后的乐天账号
- `env_serial`：AdsPower Local API 真实 `serial_number`
- `category`：分类名
- `url`：Rakuten 分类页 URL
- `count`：本次实际抓到的品牌数量
- `status`：`pending` / `done` / `partial` / `failed`
- `last_crawled_at`：最后一次采集时间
- `note`：补充说明

### `keywords`

```text
subject_id | env_serial | keyword | status | last_crawled_at | note
```

说明：

- `keyword`：站内搜索关键词
- `status`：`pending` / `done` / `partial` / `failed`

### `branlist`

```text
subject_id | env_serial | category | brand | brand_url | apply_status | note | source_type | search_keyword | discovered_at
```

说明：

- `apply_status`：`pending` / `applied` / `skipped` / `failed`
- `source_type`：
  - `category_listing`
  - `keyword_search`
- `search_keyword`：仅关键词采集来源会写值

去重规则：

- 仅在同一 `subject_id` 内按品牌名去重
- 去重键是 `brand.strip().lower()`
- 不跨主体去重

### `apply_window`

```text
subject_id | env_serial | window_start | window_end | limit | status
```

说明：

- 申请额度窗口按 `subject_id` 管理
- 每个新窗口固定随机生成 `30~40` 的额度
- `status` 当前主要写 `active`

### `apply_log`

```text
subject_id | env_serial | brand | brand_url | applied_at | result | note
```

说明：

- 只记录成功申请的品牌
- 当前 `result` 固定写 `applied`
- 24 小时窗口已用额度从这张表现算

### `partnership_deeplinks`

```text
subject_id | env_serial | advertiser_id | advertiser_name | advertiser_url | ships_to | partnership_status | advertiser_status | deep_links_enabled | homepage_deeplink | u1 | approved_at | status_updated_at | synced_at | note
```

说明：

- 这张表来自 Rakuten 官方 API，不依赖后台页面抓取
- 只同步 Partnerships API 返回的 `active` 合作广告主
- `advertiser_url` 来自 Advertisers API，作为品牌首页 URL
- `ships_to` 来自 Advertisers API 的 `policies.international_capabilities.ships_to`，表示广告主可配送/服务的国家或地区代码
- `homepage_deeplink` 优先由 Deep Links API 对品牌首页生成
- 如果广告主未开启 deep linking，或 Deep Links API 返回 URL 模板不匹配，脚本会用 Link Locator API 查找现成 Text/Banner tracking link 作为 fallback
- 如果 Deep Links API 和 Link Locator API 都没有可用链接，`homepage_deeplink` 留空，`note` 写明失败原因

## Helper 自检

先跑 helper 自检，再跑业务脚本。

### 0. 初始化工作表布局

如果目标 Spreadsheet 还是空表，先执行：

```bash
python3 scripts/init_sheet_layout.py
```

行为：

- 创建或校准 `task_source` / `category_map` / 5 张运行表
- 如果 `King` 缺少 `乐天状态`，自动补列
- 不读取也不修改 `important`

### 1. Google Sheets 自检

```bash
python3 scripts/check_google_sheets.py --spreadsheet-id YOUR_SPREADSHEET_ID --range 'Sheet1!A1:A5'
```

### 2. AdsPower 自检

```bash
python3 scripts/check_adspower.py --env-serial 3
```

如果你不确定 `King.指纹id` 现在填的是不是 `serial_number`，先执行：

```bash
python3 scripts/sync_king_adspower_serials.py --dry-run
```

## 使用方式

### 1. 先同步到运行表

```bash
python3 scripts/sync_master_to_runtime.py
```

### 2. 执行单主体

按指纹id执行：

```bash
python3 scripts/run_subject.py --env-serial 3
```

按乐天账号执行：

```bash
python3 scripts/run_subject.py --rakuten-account vc.ddom@outlook.com
```

只跑采集：

```bash
python3 scripts/run_subject.py --env-serial 3 --skip-apply
```

### 3. 执行每日批量任务

```bash
python3 scripts/run_daily.py
```

### 4. 同步已合作品牌并生成首页 deeplink

先确认 Google Sheet 的 `King` 表中，当前主体行已经填写 Rakuten API 凭据：

```text
RAKUTEN_ACCOUNT_ID=你的 publisher account id
RAKUTEN_CLIENT_ID=开发者后台 application client_id
RAKUTEN_CLIENT_SECRET=开发者后台 application client_secret
```

然后执行：

```bash
python3 scripts/sync_partnership_deeplinks.py --rakuten-account vc.ddom@outlook.com
```

常用参数：

```bash
python3 scripts/sync_partnership_deeplinks.py --env-serial 3 --network 1 --u1 homepage
python3 scripts/sync_partnership_deeplinks.py --subject-id vc.ddom@outlook.com --max-brands 10
```

脚本会写入 `partnership_deeplinks`：

- Partnerships API：检查哪些广告主已经是 `active` 合作关系
- Advertisers API：读取广告主首页 URL 和是否支持 deep link
- Deep Links API：对广告主首页生成 `homepage_deeplink`
- Link Locator API：在 deep linking 关闭或首页 URL 模板不匹配时，优先查 Text Links，再查 Banner Links，写入可用 tracking link

## 申请额度规则

申请脚本按 `subject_id` 维护 24 小时窗口。

规则：

- 如果当前主体没有有效窗口，则新建一个 24 小时窗口
- 新窗口的 `limit` 为 `30~40` 间的随机整数
- 同一窗口内多次运行，额度固定不变
- 已用额度从 `apply_log` 现算
- 达到额度后本次运行立即停止

`-n/--num` 的作用：

- 是本次运行最多处理的品牌数量上限
- `30~40` 窗口额度只限制成功申请数，不把 `skipped` / `failed` 计入已用额度
- 实际最多处理数量 = `-n` 与 `待申请品牌数` 二者中的较小值
- 实际最多成功申请数量仍受 `窗口剩余额度` 限制

## 首次联调建议

建议先准备：

- `King` 一条 active 主体
- `task_source` 一条 keyword 或 category
- `category_map` 至少一条分类映射

推荐联调顺序：

```bash
python3 scripts/check_google_sheets.py --spreadsheet-id YOUR_SPREADSHEET_ID --range 'caturl!A1:H3'
python3 scripts/sync_king_adspower_serials.py --dry-run
python3 scripts/check_adspower.py --env-serial 3
python3 scripts/init_sheet_layout.py
python3 scripts/sync_master_to_runtime.py
python3 scripts/run_subject.py --env-serial 3 --skip-apply
python3 scripts/run_subject.py --env-serial 3 -n 1
```

先用 `-n 1`，避免第一次直接跑太多申请。

## 联调检查点

跑完采集脚本后检查：

- `caturl` / `keywords` 是否自动生成
- `caturl.status` / `keywords.status` 是否更新
- `branlist` 是否新增品牌
- `source_type` 是否正确
- `search_keyword` 是否只在关键词来源写值

跑完申请脚本后检查：

- `branlist.apply_status` 是否更新为 `applied` / `skipped` / `failed`
- `branlist.brand_url` 是否补写
- `apply_window` 是否新增窗口
- `apply_log` 是否只记录成功申请

## 注意事项

- 表头名字必须和文档一致，否则脚本会报缺少表头
- `subject_id` 是规范化后的乐天账号，不再建议手工改写
- `brand_url` 允许为空，申请流程仍然会按品牌名搜索
- `skipped` 和 `failed` 默认不会自动重试
- 当前实现不处理并发运行同一 `subject_id` 的冲突

## 项目结构

```
rakuten-script/
├── rakuten_aff_apply.py        # 品牌申请主脚本
├── rakuten_aff_offer.py        # 品牌采集主脚本
├── lib/                        # 共享模块
│   ├── config.py               # 环境变量与配置读取
│   ├── errors.py               # 自定义异常体系
│   ├── env_manager.py          # 指纹环境打开（HubStudio/AdsPower）
│   ├── fingerprint_utils.py    # 指纹浏览器 API 操作
│   ├── google_sheets_helper.py # Google Sheets API 封装（含重试+批量读取）
│   ├── logger.py               # 统一日志模块（控制台+文件双写）
│   ├── rakuten_api.py          # Rakuten Advertising API 客户端
│   ├── rakuten_auth.py         # Rakuten 登录逻辑（Enter优先+按钮兜底）
│   ├── runtime_model.py        # 运行表数据模型与 Sheet 常量
│   ├── selenium_helpers.py     # Selenium 通用工具（find/click/wait/智能等待）
│   └── selenium_input.py       # 输入框操作（跨平台键位）
├── scripts/                    # 管理脚本
│   ├── check_adspower.py       # AdsPower 连通性自检
│   ├── check_google_sheets.py  # Google Sheets 连通性自检
│   ├── init_sheet_layout.py    # 初始化运行表结构
│   ├── run_daily.py            # 每日批量执行（sync+全部主体）
│   ├── run_subject.py          # 单主体执行
│   ├── sync_king_adspower_serials.py   # 指纹id 对齐迁移工具
│   ├── sync_master_to_runtime.py       # King/task_source → 运行表同步
│   └── sync_partnership_deeplinks.py   # 合作品牌 deeplink 生成
├── tests/                      # 单元测试（93 个用例）
├── logs/                       # 自动生成的日志文件（已 gitignore）
└── secrets/                    # 凭据文件（已 gitignore）
```

## 共享模块说明

### `lib/selenium_helpers.py`

Selenium 通用工具函数，供两个主脚本复用：

| 函数 | 说明 |
|------|------|
| `find_el()` | 等待元素出现 |
| `find_el_clickable()` | 等待元素可点击 |
| `click_el()` | 多策略点击（ActionChains → click → JS） |
| `wait_page_stable()` | 等待 `document.readyState == "complete"` |
| `wait_page_full_load()` | 等待页面内容稳定（0.5s 轮询，2 次稳定） |
| `wait_until()` | **智能等待**：轮询条件函数，支持 `min_wait` 最低等待时间 |
| `safe_navigate()` | 带重试机制的页面导航（默认重试 2 次） |

### `lib/rakuten_auth.py`

统一的 Rakuten Advertising 登录逻辑，采用 **Enter 键优先 + 按钮兜底**策略。

### `lib/env_manager.py`

统一的指纹环境打开逻辑，支持多内核版本降级尝试。

### `lib/logger.py`

零侵入日志模块：通过 `_TeeWriter` 劫持 `sys.stdout` / `sys.stderr`，所有 `print()` 自动同时写入控制台和日志文件，无需修改业务代码中的任何 `print` 语句。

日志文件自动生成在 `logs/` 目录，格式为 `{脚本名}_{日期时间}.log`。

### `lib/google_sheets_helper.py`

Google Sheets API 封装，所有操作内置 3 次重试（含 `append_rows_to_sheet`）。新增 `batch_read_sheet_data()` 支持一次 API 调用读取多个 Range。

### `lib/selenium_input.py`

输入框操作工具，自动适配 macOS (`Cmd`) 和 Windows/Linux (`Ctrl`) 快捷键。

## 性能优化配置

两个主脚本顶部定义了可调节的超时常量：

### `rakuten_aff_apply.py`

```python
PAGE_LOAD_TIMEOUT = 60        # 页面加载超时
WAIT_FULL_LOAD = 30           # 等待页面内容稳定超时
SEARCH_RESULT_TIMEOUT = 35    # 搜索结果等待超时
SUBMIT_WAIT_TIMEOUT = 12      # 提交后弹窗关闭等待超时
BRAND_INTERVAL = 3            # 品牌间隔等待
SEARCH_MIN_WAIT = 8           # 搜索触发后最少等待（保证内容渲染）
DIALOG_MIN_WAIT = 5           # Apply弹窗出现最少等待
TERMS_CLICK_SETTLE = 2        # 勾选条款后最少等待
```

### `rakuten_aff_offer.py`

```python
PAGE_LOAD_TIMEOUT = 60        # 页面加载超时
WAIT_FULL_LOAD = 30           # 等待页面内容稳定超时
TASK_INTERVAL = 2             # 任务间隔等待
```

### 智能等待机制

脚本使用 `wait_until(driver, condition_fn, timeout, min_wait)` 替代硬编码 `time.sleep()`：

- **`min_wait`**：最短等待秒数，即使条件已满足也要等够（保证网络稳定性）
- **`timeout`**：最长等待秒数
- 条件满足且过了 `min_wait` → 立即返回
- 超过 `timeout` → 强制返回

搜索结果等待还额外要求卡片必须有实际文字内容（> 10 字符），防止 DOM 骨架屏/占位符导致误判。

## 更新日志

### 2026-04-30 — 结构重构 + 性能优化

#### 结构重构

- **提取 9 个重复函数到共享模块**：`_find_el`、`_click_el`、`_wait_page_stable`、`_wait_page_full_load`、`_is_login_page`、`_is_logged_in`、`login_rakuten`、`open_env_by_serial` 等从两个主脚本中提取到 `lib/selenium_helpers.py`、`lib/rakuten_auth.py`、`lib/env_manager.py`
- **消除约 500 行重复代码**：apply.py 1561→1348 行，offer.py 948→733 行
- **统一登录策略**：offer.py 升级为 Enter 键优先+按钮兜底的更健壮版本
- **修复 `now_iso()` 重复定义**：删除 apply.py 本地版本，统一使用 `runtime_model.now_iso()`
- **修复跨平台键位**：`selenium_input.py` 从硬编码 `Keys.COMMAND` 改为平台自适应

#### 性能优化

- **智能等待替代硬编码 sleep**：6 处 `time.sleep()` 替换为条件检测+`min_wait` 最低等待
- **`_disable_profile_accordion` 优化**：从每品牌 6 次 DOM 操作改为 CSS 注入（每页面仅 1 次）
- **`wait_page_full_load` 优化**：轮询间隔 1.0s→0.5s，稳定阈值 3→2
- **`safe_navigate()` 导航重试**：首页和搜索页加载失败自动重试 2 次
- **搜索结果内容验证**：`_wait_for_offer_results` 新增卡片文字内容检查，防止骨架屏误判
- **超时参数常量化**：所有魔法数字集中到文件顶部常量区

#### 可靠性提升

- **KeyboardInterrupt 优雅处理**：Ctrl+C 后打印已处理/已成功数量，不再显示完整 traceback
- **`append_rows_to_sheet` 添加重试**：与其他 Sheets 操作一致，防止 429 限流
- **`batch_read_sheet_data` API**：支持一次调用读取多个 Range

#### 日志功能

- 新增 `lib/logger.py`：零侵入式日志记录，`print()` 自动双写到控制台+日志文件
- 日志文件自动存放在 `logs/` 目录，格式 `{脚本名}_{YYYYMMDD_HHMMSS}.log`
- `.gitignore` 已排除 `logs/` 目录
