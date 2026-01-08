# AstrBot 高级关键词监听插件

## 功能特性

### 核心功能
- **多关键词监听**: 支持同时监听多个关键词
- **智能过滤**: 支持排除词，避免误触发
- **大小写不敏感**: 自动识别大小写变体
- **冷却机制**: 防止同一用户频繁触发

### 通知功能
- **实时通知**: 关键词触发时立即通知管理员
- **自定义模板**: 支持自定义通知格式
- **重试机制**: 发送失败时自动重试
- **启动/停止通知**: 插件状态变更时通知

### 统计功能
- **实时统计**: 记录触发次数、用户数、关键词分布
- **历史统计**: 支持多天统计报告
- **自动清理**: 定期清理过期数据

### 管理功能
- **名单管理**: 支持群组/用户白名单和黑名单
- **状态控制**: 可随时暂停/恢复监听
- **关键词管理**: 支持动态添加/删除关键词
- **详细日志**: 记录所有触发事件

### 用户体验
- **自动回复**: 触发关键词后可自动回复用户
- **状态查询**: 随时查看插件运行状态
- **调试模式**: 可开启详细调试日志

## 安装方法

1. 将插件文件夹放入 AstrBot 的插件目录：`data/plugin/`
2. 重启 AstrBot 或通过管理面板加载插件
3. 在插件配置页面设置相关参数

## 配置说明

### 基本配置
- `admin_qq`: 管理员QQ号
- `keywords`: 监听的关键词列表
- `exclude_words`: 排除关键词列表
- `cooldown_time`: 冷却时间（秒）

### 监听设置
- `enable_group_monitor`: 是否监听群聊
- `enable_private_monitor`: 是否监听私聊
- `max_message_length`: 最大消息处理长度

### 通知设置
- `enable_notification`: 是否启用通知
- `notification_format`: 通知消息格式模板
- `notification_retry_times`: 重试次数
- `notification_retry_delay`: 重试延迟（秒）

### 名单管理
- `whitelist_groups`: 白名单群组
- `blacklist_groups`: 黑名单群组
- `whitelist_users`: 白名单用户
- `blacklist_users`: 黑名单用户

### 统计设置
- `enable_statistics`: 是否启用统计
- `statistics_retention_days`: 统计保留天数

### 自动回复
- `enable_auto_reply`: 是否启用自动回复
- `auto_reply_message`: 自动回复消息模板

### 调试设置
- `enable_debug_log`: 是否启用调试日志

## 使用命令

### 状态查询
- `/监听状态` - 查看插件运行状态
- `/监听统计 [天数]` - 查看统计报告（默认7天）
- `/关键词列表` - 查看关键词列表
- `/最近触发 [数量]` - 查看最近触发记录

### 管理命令（仅管理员）
- `/通知测试` - 测试通知功能
- `/暂停监听` - 暂停关键词监听
- `/恢复监听` - 恢复关键词监听
- `/添加关键词 <关键词>` - 添加监听关键词
- `/删除关键词 <关键词>` - 删除监听关键词

## 通知模板变量

在 `notification_format` 中可以使用以下变量：
- `{keyword}` - 触发关键词
- `{time}` - 触发时间
- `{user}` - 用户名
- `{user_id}` - 用户ID
- `{source}` - 消息来源（群聊/私聊）
- `{group_id}` - 群组ID（仅群聊）
- `{group_info}` - 群组信息（自动包含换行）
- `{message}` - 消息内容
- `{message_id}` - 消息ID

## 自动回复模板变量

在 `auto_reply_message` 中可以使用以下变量：
- `{user}` - 用户名
- `{keyword}` - 触发关键词

## 数据存储

插件数据存储在以下位置：
- `data/plugin_data/astrbot_plugin_keyword_monitor/trigger_records.json` - 触发记录
- `data/plugin_data/astrbot_plugin_keyword_monitor/statistics.json` - 统计信息
- `data/plugin_data/astrbot_plugin_keyword_monitor/last_trigger_time.json` - 最后触发时间

## 性能优化

1. **异步处理**: 所有IO操作均为异步，不阻塞主线程
2. **延迟保存**: 数据定期保存，避免频繁IO
3. **内存管理**: 自动清理过期数据，防止内存泄漏
4. **错误恢复**: 完善的错误处理机制

## 兼容性

- AstrBot 版本：>= 3.4.28
- Python 版本：>= 3.8
- 平台支持：QQ (aiocqhttp/QQ)

## 更新日志

### v2.0.0
- 完全重构，代码结构更清晰
- 支持多关键词和排除词
- 添加统计功能和自动清理
- 支持白名单/黑名单管理
- 添加自动回复功能
- 优化性能和稳定性
