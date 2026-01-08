import asyncio
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import traceback

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


class MessageSource(Enum):
    """消息来源类型"""
    GROUP = "群聊"
    PRIVATE = "私聊"
    OTHER = "其他"


@dataclass
class TriggerRecord:
    """触发记录"""
    timestamp: float
    keyword: str
    user_id: str
    user_name: str
    message_id: str
    source: MessageSource
    group_id: str = ""
    message_preview: str = ""
    notified: bool = False


@dataclass
class DailyStatistics:
    """每日统计"""
    date: str  # YYYY-MM-DD
    total_triggers: int = 0
    unique_users: Set[str] = None
    keyword_counts: Dict[str, int] = None
    source_counts: Dict[str, int] = None
    
    def __post_init__(self):
        if self.unique_users is None:
            self.unique_users = set()
        if self.keyword_counts is None:
            self.keyword_counts = {}
        if self.source_counts is None:
            self.source_counts = {}


@register(
    "astrbot_plugin_keyword_monitor",
    "AI Assistant",
    "高级关键词监听插件，支持多关键词、白名单、统计等功能",
    "v0.1.0",
)
class KeywordMonitorPlugin(Star):
    """
    高级关键词监听插件
    监听所有消息中的关键词并报告给管理员
    """
    
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        
        # 基本配置
        self.admin_qq = str(self.config.get("admin_qq", "475407353"))
        self.admin_umo = f"QQ:FriendMessage:{self.admin_qq}"
        
        # 关键词配置
        self.keywords = self._parse_keywords(self.config.get("keywords", ["服务器"]))
        self.exclude_words = set(self.config.get("exclude_words", []))
        
        # 监听配置
        self.cooldown_time = self.config.get("cooldown_time", 60)
        self.max_message_length = self.config.get("max_message_length", 500)
        self.enable_group_monitor = self.config.get("enable_group_monitor", True)
        self.enable_private_monitor = self.config.get("enable_private_monitor", True)
        self.enable_notification = self.config.get("enable_notification", True)
        self.notification_format = self.config.get("notification_format", "")
        
        # 自动回复配置
        self.enable_auto_reply = self.config.get("enable_auto_reply", False)
        self.auto_reply_message = self.config.get("auto_reply_message", "")
        
        # 名单配置
        self.whitelist_groups = set(self.config.get("whitelist_groups", []))
        self.blacklist_groups = set(self.config.get("blacklist_groups", []))
        self.whitelist_users = set(self.config.get("whitelist_users", []))
        self.blacklist_users = set(self.config.get("blacklist_users", []))
        
        # 统计配置
        self.enable_statistics = self.config.get("enable_statistics", True)
        self.statistics_retention_days = self.config.get("statistics_retention_days", 30)
        
        # 重试配置
        self.notification_retry_times = self.config.get("notification_retry_times", 3)
        self.notification_retry_delay = self.config.get("notification_retry_delay", 2)
        
        # 调试配置
        self.enable_debug_log = self.config.get("enable_debug_log", False)
        
        # 数据存储
        self.data_dir = self._get_plugin_data_dir()
        self.trigger_records_file = os.path.join(self.data_dir, "trigger_records.json")
        self.statistics_file = os.path.join(self.data_dir, "statistics.json")
        self.last_trigger_time_file = os.path.join(self.data_dir, "last_trigger_time.json")
        
        # 运行时数据
        self.last_trigger_time: Dict[str, float] = self._load_last_trigger_time()
        self.trigger_records: List[TriggerRecord] = self._load_trigger_records()
        self.daily_statistics: Dict[str, DailyStatistics] = self._load_statistics()
        
        # 异步任务
        self._background_tasks: Set[asyncio.Task] = set()
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # 启动初始化
        self._log_initialization()
        asyncio.create_task(self._initialize_async())
    
    def _get_plugin_data_dir(self) -> str:
        """获取插件数据目录"""
        data_dir = os.path.join(get_astrbot_data_path(), "plugin_data", "astrbot_plugin_keyword_monitor")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    
    def _parse_keywords(self, keywords_config: List[str]) -> Set[str]:
        """解析关键词配置"""
        keywords = set()
        for keyword in keywords_config:
            keyword = keyword.strip()
            if keyword:
                keywords.add(keyword)
                # 同时添加小写版本用于大小写不敏感匹配
                keywords.add(keyword.lower())
        return keywords
    
    def _log_initialization(self):
        """记录初始化日志"""
        logger.info("=" * 60)
        logger.info("关键词监听插件 v0.1.0 初始化")
        logger.info(f"管理员QQ: {self.admin_qq}")
        logger.info(f"监听关键词数量: {len(self.keywords) // 2}")  # 因为包含大小写版本
        logger.info(f"排除关键词数量: {len(self.exclude_words)}")
        logger.info(f"群聊监听: {'启用' if self.enable_group_monitor else '禁用'}")
        logger.info(f"私聊监听: {'启用' if self.enable_private_monitor else '禁用'}")
        logger.info(f"通知功能: {'启用' if self.enable_notification else '禁用'}")
        logger.info(f"统计功能: {'启用' if self.enable_statistics else '禁用'}")
        logger.info("=" * 60)
    
    async def _initialize_async(self):
        """异步初始化"""
        await asyncio.sleep(2)  # 等待系统稳定
        
        # 发送启动通知
        if self.enable_notification:
            await self._send_startup_notification()
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_task_loop())
        self._background_tasks.add(self._cleanup_task)
        self._cleanup_task.add_done_callback(self._background_tasks.discard)
    
    async def _send_startup_notification(self):
        """发送启动通知"""
        try:
            startup_message = (
                "【插件启动通知】\n"
                f"YiChex-CNKD关键词监听插件已启动\n"
                f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"监听关键词: {', '.join(sorted(set(k for k in self.keywords if k == k.lower())))[:100]}\n"
                f"插件版本: v0.1.0"
            )
            
            await self._send_message_to_admin(startup_message, "startup")
            logger.info("✓ 启动通知发送成功")
        except Exception as e:
            logger.error(f"发送启动通知失败: {e}")
    
    def _load_last_trigger_time(self) -> Dict[str, float]:
        """加载最后触发时间"""
        try:
            if os.path.exists(self.last_trigger_time_file):
                with open(self.last_trigger_time_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {k: float(v) for k, v in data.items()}
        except Exception as e:
            logger.error(f"加载最后触发时间失败: {e}")
        return {}
    
    def _save_last_trigger_time(self):
        """保存最后触发时间"""
        try:
            with open(self.last_trigger_time_file, 'w', encoding='utf-8') as f:
                json.dump(self.last_trigger_time, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存最后触发时间失败: {e}")
    
    def _load_trigger_records(self) -> List[TriggerRecord]:
        """加载触发记录"""
        try:
            if os.path.exists(self.trigger_records_file):
                with open(self.trigger_records_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    records = []
                    for item in data:
                        record = TriggerRecord(
                            timestamp=item['timestamp'],
                            keyword=item['keyword'],
                            user_id=item['user_id'],
                            user_name=item['user_name'],
                            message_id=item['message_id'],
                            source=MessageSource(item['source']),
                            group_id=item.get('group_id', ''),
                            message_preview=item.get('message_preview', ''),
                            notified=item.get('notified', False)
                        )
                        records.append(record)
                    return records
        except Exception as e:
            logger.error(f"加载触发记录失败: {e}")
        return []
    
    def _save_trigger_records(self):
        """保存触发记录"""
        try:
            # 只保留最近1000条记录，防止文件过大
            recent_records = self.trigger_records[-1000:] if len(self.trigger_records) > 1000 else self.trigger_records
            
            data = []
            for record in recent_records:
                item = {
                    'timestamp': record.timestamp,
                    'keyword': record.keyword,
                    'user_id': record.user_id,
                    'user_name': record.user_name,
                    'message_id': record.message_id,
                    'source': record.source.value,
                    'group_id': record.group_id,
                    'message_preview': record.message_preview[:100],
                    'notified': record.notified
                }
                data.append(item)
            
            with open(self.trigger_records_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存触发记录失败: {e}")
    
    def _load_statistics(self) -> Dict[str, DailyStatistics]:
        """加载统计信息"""
        try:
            if os.path.exists(self.statistics_file):
                with open(self.statistics_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    stats = {}
                    for date_str, stat_data in data.items():
                        stat = DailyStatistics(
                            date=date_str,
                            total_triggers=stat_data.get('total_triggers', 0),
                            unique_users=set(stat_data.get('unique_users', [])),
                            keyword_counts=stat_data.get('keyword_counts', {}),
                            source_counts=stat_data.get('source_counts', {})
                        )
                        stats[date_str] = stat
                    return stats
        except Exception as e:
            logger.error(f"加载统计信息失败: {e}")
        return {}
    
    def _save_statistics(self):
        """保存统计信息"""
        try:
            data = {}
            for date_str, stat in self.daily_statistics.items():
                data[date_str] = {
                    'total_triggers': stat.total_triggers,
                    'unique_users': list(stat.unique_users),
                    'keyword_counts': stat.keyword_counts,
                    'source_counts': stat.source_counts
                }
            
            with open(self.statistics_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存统计信息失败: {e}")
    
    def _should_monitor_message(self, event: AstrMessageEvent) -> bool:
        """判断是否应该监听此消息"""
        try:
            # 检查消息类型
            if not event.message_str:
                return False
            
            # 检查消息来源类型
            is_group = bool(getattr(event.message_obj, 'group_id', ''))
            
            if is_group:
                if not self.enable_group_monitor:
                    return False
                
                # 检查群组名单
                group_id = event.message_obj.group_id
                if self.whitelist_groups and group_id not in self.whitelist_groups:
                    return False
                if group_id in self.blacklist_groups:
                    return False
            else:
                if not self.enable_private_monitor:
                    return False
            
            return True
            
        except Exception as e:
            if self.enable_debug_log:
                logger.error(f"检查消息监听条件失败: {e}")
            return False
    
    def _check_contains_keywords(self, message: str) -> Tuple[bool, str]:
        """检查消息是否包含关键词"""
        try:
            # 转换为小写进行不区分大小写的匹配
            message_lower = message.lower()
            
            # 检查排除词
            for exclude_word in self.exclude_words:
                if exclude_word.lower() in message_lower:
                    return False, ""
            
            # 检查关键词
            for keyword in self.keywords:
                # 如果关键词是小写版本，使用小写消息进行匹配
                if keyword.islower():
                    if keyword in message_lower:
                        # 找到原始大小写的关键词
                        original_keyword = next((k for k in self.keywords if k.lower() == keyword and k != keyword), keyword)
                        return True, original_keyword
                # 否则使用原始消息匹配
                else:
                    if keyword in message:
                        return True, keyword
            
            return False, ""
            
        except Exception as e:
            if self.enable_debug_log:
                logger.error(f"检查关键词失败: {e}")
            return False, ""
    
    def _check_user_in_list(self, user_id: str) -> bool:
        """检查用户是否在名单中"""
        # 如果白名单不为空，只允许白名单用户
        if self.whitelist_users:
            return user_id in self.whitelist_users
        
        # 如果黑名单不为空，排除黑名单用户
        if user_id in self.blacklist_users:
            return False
        
        return True
    
    def _check_cooldown(self, user_id: str) -> bool:
        """检查冷却时间"""
        current_time = time.time()
        last_time = self.last_trigger_time.get(user_id, 0)
        
        if current_time - last_time < self.cooldown_time:
            if self.enable_debug_log:
                logger.debug(f"用户 {user_id} 处于冷却期")
            return False
        
        # 更新最后触发时间
        self.last_trigger_time[user_id] = current_time
        
        # 异步保存，避免阻塞
        asyncio.create_task(self._async_save_last_trigger_time())
        
        return True
    
    async def _async_save_last_trigger_time(self):
        """异步保存最后触发时间"""
        await asyncio.sleep(1)  # 延迟保存，避免频繁IO
        self._save_last_trigger_time()
    
    def _format_notification(self, event: AstrMessageEvent, keyword: str, user_name: str, user_id: str) -> str:
        """格式化通知消息"""
        try:
            # 获取消息来源信息
            is_group = bool(getattr(event.message_obj, 'group_id', ''))
            source = MessageSource.GROUP if is_group else MessageSource.PRIVATE
            
            # 基本信息
            timestamp = getattr(event.message_obj, 'timestamp', time.time())
            message_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            
            # 消息内容预览
            message_content = event.message_str
            if len(message_content) > self.max_message_length:
                message_content = message_content[:self.max_message_length] + "..."
            
            # 群组信息
            group_info = ""
            if is_group:
                group_id = event.message_obj.group_id
                group_info = f"\n群组ID: {group_id}"
            
            # 消息ID
            message_id = getattr(event.message_obj, 'message_id', '未知')
            
            # 使用模板或默认格式
            if self.notification_format:
                notification = self.notification_format.format(
                    keyword=keyword,
                    time=message_time,
                    user=user_name,
                    user_id=user_id,
                    source=source.value,
                    group_id=group_id if is_group else "",
                    group_info=group_info,
                    message=message_content,
                    message_id=message_id
                )
            else:
                # 默认格式
                notification = (
                    f"【关键词监听报告】\n"
                    f"关键词: {keyword}\n"
                    f"触发时间: {message_time}\n"
                    f"触发用户: {user_name} (ID: {user_id})\n"
                    f"消息来源: {source.value}{group_info}\n"
                    f"消息内容: {message_content}\n"
                    f"消息ID: {message_id}\n\n"
                    f"--- CNKD YiChex 0.1.0 ---"
                )
            
            return notification
            
        except Exception as e:
            logger.error(f"格式化通知失败: {e}")
            # 返回简单通知
            return f"【关键词监听】检测到关键词: {keyword}\n用户: {user_name}\n时间: {datetime.now().strftime('%H:%M:%S')}"
    
    def _format_auto_reply(self, user_name: str, keyword: str) -> str:
        """格式化自动回复"""
        if self.auto_reply_message:
            return self.auto_reply_message.format(user=user_name, keyword=keyword)
        else:
            return f"您提到了{keyword}，已通知管理员处理。"
    
    async def _send_message_to_admin(self, message: str, message_type: str = "notification") -> bool:
        """向管理员发送消息（带重试机制）"""
        if not self.enable_notification:
            return False
        
        for attempt in range(self.notification_retry_times + 1):
            try:
                # 创建消息链
                message_chain = MessageChain()
                message_chain.chain = [Plain(message)]
                
                # 发送消息
                await self.context.send_message(self.admin_umo, message_chain)
                
                if attempt > 0:
                    logger.info(f"✓ {message_type}消息发送成功 (第{attempt + 1}次重试)")
                else:
                    if self.enable_debug_log:
                        logger.debug(f"✓ {message_type}消息发送成功")
                
                return True
                
            except Exception as e:
                if attempt < self.notification_retry_times:
                    logger.warning(f"{message_type}消息发送失败，{self.notification_retry_delay}秒后重试 ({attempt + 1}/{self.notification_retry_times}): {e}")
                    await asyncio.sleep(self.notification_retry_delay)
                else:
                    logger.error(f"{message_type}消息发送失败 (已重试{self.notification_retry_times}次): {e}")
        
        return False
    
    async def _send_auto_reply(self, event: AstrMessageEvent, reply_message: str):
        """发送自动回复"""
        try:
            # 创建消息链
            message_chain = MessageChain()
            message_chain.chain = [Plain(reply_message)]
            
            # 使用原始事件的UMO进行回复
            await self.context.send_message(event.unified_msg_origin, message_chain)
            
            if self.enable_debug_log:
                logger.debug(f"✓ 自动回复发送成功: {reply_message[:50]}...")
                
        except Exception as e:
            logger.error(f"发送自动回复失败: {e}")
    
    def _update_statistics(self, keyword: str, user_id: str, source: MessageSource):
        """更新统计信息"""
        if not self.enable_statistics:
            return
        
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            
            # 获取或创建今日统计
            if today not in self.daily_statistics:
                self.daily_statistics[today] = DailyStatistics(date=today)
            
            stat = self.daily_statistics[today]
            
            # 更新统计
            stat.total_triggers += 1
            stat.unique_users.add(user_id)
            
            # 关键词统计
            if keyword in stat.keyword_counts:
                stat.keyword_counts[keyword] += 1
            else:
                stat.keyword_counts[keyword] = 1
            
            # 来源统计
            source_str = source.value
            if source_str in stat.source_counts:
                stat.source_counts[source_str] += 1
            else:
                stat.source_counts[source_str] = 1
            
            # 异步保存
            asyncio.create_task(self._async_save_statistics())
            
        except Exception as e:
            logger.error(f"更新统计信息失败: {e}")
    
    async def _async_save_statistics(self):
        """异步保存统计信息"""
        await asyncio.sleep(2)  # 延迟保存
        self._save_statistics()
    
    def _create_trigger_record(self, event: AstrMessageEvent, keyword: str, notified: bool = False) -> TriggerRecord:
        """创建触发记录"""
        try:
            sender = event.message_obj.sender
            user_id = getattr(sender, 'user_id', '未知')
            user_name = event.get_sender_name() if hasattr(event, 'get_sender_name') else getattr(sender, 'nickname', '未知')
            
            # 判断消息来源
            is_group = bool(getattr(event.message_obj, 'group_id', ''))
            source = MessageSource.GROUP if is_group else MessageSource.PRIVATE
            
            # 创建记录
            record = TriggerRecord(
                timestamp=time.time(),
                keyword=keyword,
                user_id=user_id,
                user_name=user_name,
                message_id=getattr(event.message_obj, 'message_id', '未知'),
                source=source,
                group_id=getattr(event.message_obj, 'group_id', ''),
                message_preview=event.message_str[:100],
                notified=notified
            )
            
            # 添加到记录列表
            self.trigger_records.append(record)
            
            # 异步保存
            asyncio.create_task(self._async_save_trigger_records())
            
            return record
            
        except Exception as e:
            logger.error(f"创建触发记录失败: {e}")
            return None
    
    async def _async_save_trigger_records(self):
        """异步保存触发记录"""
        await asyncio.sleep(1)
        self._save_trigger_records()
    
    async def _cleanup_task_loop(self):
        """清理任务循环"""
        while True:
            try:
                await self._perform_cleanup()
                # 每小时清理一次
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理任务失败: {e}")
                await asyncio.sleep(300)  # 失败后等待5分钟
    
    async def _perform_cleanup(self):
        """执行清理"""
        try:
            # 清理过期的统计信息
            if self.enable_statistics:
                cutoff_date = datetime.now() - timedelta(days=self.statistics_retention_days)
                cutoff_str = cutoff_date.strftime('%Y-%m-%d')
                
                dates_to_remove = []
                for date_str in self.daily_statistics:
                    if date_str < cutoff_str:
                        dates_to_remove.append(date_str)
                
                for date_str in dates_to_remove:
                    del self.daily_statistics[date_str]
                
                if dates_to_remove:
                    logger.info(f"清理了 {len(dates_to_remove)} 天前的统计信息")
                    self._save_statistics()
            
            # 清理过时的最后触发时间（30天前）
            cutoff_time = time.time() - (30 * 24 * 3600)
            users_to_remove = []
            
            for user_id, last_time in self.last_trigger_time.items():
                if last_time < cutoff_time:
                    users_to_remove.append(user_id)
            
            for user_id in users_to_remove:
                del self.last_trigger_time[user_id]
            
            if users_to_remove:
                logger.info(f"清理了 {len(users_to_remove)} 个用户的最后触发时间")
                self._save_last_trigger_time()
                
        except Exception as e:
            logger.error(f"执行清理失败: {e}")
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def keyword_monitor(self, event: AstrMessageEvent):
        """
        监听所有消息，检查是否包含关键词
        """
        try:
            # 1. 检查是否应该监听此消息
            if not self._should_monitor_message(event):
                return
            
            # 2. 检查是否包含关键词
            contains_keyword, keyword = self._check_contains_keywords(event.message_str)
            if not contains_keyword:
                return
            
            # 3. 获取用户信息
            sender = event.message_obj.sender
            user_id = getattr(sender, 'user_id', '未知')
            user_name = event.get_sender_name() if hasattr(event, 'get_sender_name') else getattr(sender, 'nickname', '未知')
            
            # 4. 检查用户名单
            if not self._check_user_in_list(user_id):
                if self.enable_debug_log:
                    logger.debug(f"用户 {user_id} 不在白名单中或处于黑名单中")
                return
            
            # 5. 检查冷却时间
            if not self._check_cooldown(user_id):
                return
            
            # 6. 判断消息来源
            is_group = bool(getattr(event.message_obj, 'group_id', ''))
            source = MessageSource.GROUP if is_group else MessageSource.PRIVATE
            
            # 7. 更新统计
            self._update_statistics(keyword, user_id, source)
            
            # 8. 创建触发记录
            trigger_record = self._create_trigger_record(event, keyword)
            
            # 9. 发送通知（异步）
            if self.enable_notification:
                notification = self._format_notification(event, keyword, user_name, user_id)
                asyncio.create_task(self._send_message_to_admin(notification, "关键词通知"))
                if trigger_record:
                    trigger_record.notified = True
            
            # 10. 发送自动回复（如果需要）
            if self.enable_auto_reply:
                reply_message = self._format_auto_reply(user_name, keyword)
                asyncio.create_task(self._send_auto_reply(event, reply_message))
            
            # 11. 记录日志
            source_str = "群聊" if is_group else "私聊"
            group_info = f" ({event.message_obj.group_id})" if is_group else ""
            logger.info(f"检测到关键词 '{keyword}' | 用户: {user_name}({user_id}) | 来源: {source_str}{group_info}")
            
        except Exception as e:
            logger.error(f"关键词监听处理出错: {e}")
            if self.enable_debug_log:
                traceback.print_exc()
    
    # ==================== 管理命令 ====================
    
    @filter.command("监听状态")
    async def monitor_status(self, event: AstrMessageEvent):
        """
        查看监听状态
        """
        try:
            # 检查权限
            sender = event.message_obj.sender
            sender_id = getattr(sender, 'user_id', '')
            is_admin = (str(sender_id) == self.admin_qq)
            
            # 获取今日统计
            today = datetime.now().strftime('%Y-%m-%d')
            today_stat = self.daily_statistics.get(today, DailyStatistics(date=today))
            
            # 构建状态消息
            status_lines = [
                "【关键词监听插件状态】",
                f"插件版本: v0.1.0",
                f"运行状态: {'运行中' if self.enable_notification else '已暂停'}",
                "",
                "📊 今日统计:",
                f"  触发次数: {today_stat.total_triggers}",
                f"  触发用户: {len(today_stat.unique_users)}",
                f"  关键词数: {len(today_stat.keyword_counts)}",
                "",
                "⚙️ 配置信息:",
                f"  监听关键词: {len(self.keywords) // 2} 个",
                f"  冷却时间: {self.cooldown_time} 秒",
                f"  群聊监听: {'启用' if self.enable_group_monitor else '禁用'}",
                f"  私聊监听: {'启用' if self.enable_private_monitor else '禁用'}",
                f"  自动回复: {'启用' if self.enable_auto_reply else '禁用'}",
            ]
            
            if is_admin:
                status_lines.extend([
                    "",
                    "🔧 管理命令:",
                    "  /监听统计 - 查看详细统计",
                    "  /关键词列表 - 查看关键词列表",
                    "  /最近触发 - 查看最近触发记录",
                    "  /通知测试 - 测试通知功能",
                    "  /暂停监听 - 暂停关键词监听",
                    "  /恢复监听 - 恢复关键词监听",
                ])
            
            yield event.plain_result("\n".join(status_lines))
            
        except Exception as e:
            logger.error(f"获取监听状态失败: {e}")
            yield event.plain_result("获取状态失败，请查看日志")
    
    @filter.command("监听统计")
    async def view_statistics(self, event: AstrMessageEvent, days: int = 7):
        """
        查看统计信息
        格式: /监听统计 [天数]
        """
        # 检查权限
        sender = event.message_obj.sender
        sender_id = getattr(sender, 'user_id', '')
        
        if str(sender_id) != self.admin_qq:
            yield event.plain_result("❌ 此指令仅限管理员使用")
            return
        
        try:
            if days < 1 or days > 365:
                yield event.plain_result("❌ 天数范围: 1-365")
                return
            
            # 获取日期范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days-1)
            
            # 收集统计信息
            total_triggers = 0
            total_users = set()
            keyword_summary = {}
            source_summary = {}
            
            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                if date_str in self.daily_statistics:
                    stat = self.daily_statistics[date_str]
                    total_triggers += stat.total_triggers
                    total_users.update(stat.unique_users)
                    
                    # 汇总关键词
                    for keyword, count in stat.keyword_counts.items():
                        if keyword in keyword_summary:
                            keyword_summary[keyword] += count
                        else:
                            keyword_summary[keyword] = count
                    
                    # 汇总来源
                    for source, count in stat.source_counts.items():
                        if source in source_summary:
                            source_summary[source] += count
                        else:
                            source_summary[source] = count
                
                current_date += timedelta(days=1)
            
            # 构建统计报告
            report_lines = [
                f"【{days}天统计报告】",
                f"统计时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "",
                "📈 总体统计:",
                f"  总触发次数: {total_triggers}",
                f"  总触发用户: {len(total_users)}",
                f"  日均触发: {total_triggers / days:.1f} 次",
                "",
                "🔑 关键词排名 (前10):",
            ]
            
            # 关键词排名
            sorted_keywords = sorted(keyword_summary.items(), key=lambda x: x[1], reverse=True)
            for i, (keyword, count) in enumerate(sorted_keywords[:10], 1):
                percentage = (count / total_triggers * 100) if total_triggers > 0 else 0
                report_lines.append(f"  {i}. {keyword}: {count} 次 ({percentage:.1f}%)")
            
            report_lines.extend([
                "",
                "📍 触发来源:",
            ])
            
            # 来源统计
            for source, count in source_summary.items():
                percentage = (count / total_triggers * 100) if total_triggers > 0 else 0
                report_lines.append(f"  {source}: {count} 次 ({percentage:.1f}%)")
            
            yield event.plain_result("\n".join(report_lines))
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            yield event.plain_result(f"获取统计失败: {str(e)}")
    
    @filter.command("关键词列表")
    async def keyword_list(self, event: AstrMessageEvent):
        """
        查看关键词列表
        """
        try:
            # 过滤掉小写版本（用于大小写不敏感匹配的副本）
            original_keywords = sorted([k for k in self.keywords if k == k or k.lower() not in self.keywords])
            exclude_words = sorted(self.exclude_words)
            
            response_lines = [
                "【关键词列表】",
                "",
                "✅ 监听关键词:",
            ]
            
            if original_keywords:
                for i, keyword in enumerate(original_keywords, 1):
                    response_lines.append(f"  {i}. {keyword}")
            else:
                response_lines.append("  暂无监听关键词")
            
            response_lines.extend([
                "",
                "❌ 排除关键词:",
            ])
            
            if exclude_words:
                for i, word in enumerate(exclude_words, 1):
                    response_lines.append(f"  {i}. {word}")
            else:
                response_lines.append("  暂无排除关键词")
            
            response_lines.extend([
                "",
                f"总计: {len(original_keywords)} 个监听词, {len(exclude_words)} 个排除词"
            ])
            
            yield event.plain_result("\n".join(response_lines))
            
        except Exception as e:
            logger.error(f"获取关键词列表失败: {e}")
            yield event.plain_result("获取关键词列表失败")
    
    @filter.command("最近触发")
    async def recent_triggers(self, event: AstrMessageEvent, count: int = 10):
        """
        查看最近触发记录
        格式: /最近触发 [数量]
        """
        # 检查权限
        sender = event.message_obj.sender
        sender_id = getattr(sender, 'user_id', '')
        
        if str(sender_id) != self.admin_qq:
            yield event.plain_result("❌ 此指令仅限管理员使用")
            return
        
        try:
            if count < 1 or count > 50:
                yield event.plain_result("❌ 数量范围: 1-50")
                return
            
            # 获取最近的触发记录
            recent_records = self.trigger_records[-count:] if self.trigger_records else []
            
            if not recent_records:
                yield event.plain_result("📝 暂无触发记录")
                return
            
            response_lines = [f"【最近{len(recent_records)}条触发记录】"]
            
            for i, record in enumerate(reversed(recent_records), 1):
                time_str = datetime.fromtimestamp(record.timestamp).strftime('%m-%d %H:%M')
                group_info = f" ({record.group_id})" if record.group_id else ""
                
                line = (
                    f"{i}. [{time_str}] {record.keyword}\n"
                    f"   用户: {record.user_name} | 来源: {record.source.value}{group_info}\n"
                    f"   消息: {record.message_preview}"
                )
                response_lines.append(line)
            
            yield event.plain_result("\n".join(response_lines))
            
        except Exception as e:
            logger.error(f"获取触发记录失败: {e}")
            yield event.plain_result(f"获取记录失败: {str(e)}")
    
    @filter.command("通知测试")
    async def test_notification(self, event: AstrMessageEvent):
        """
        测试通知功能
        """
        # 检查权限
        sender = event.message_obj.sender
        sender_id = getattr(sender, 'user_id', '')
        
        if str(sender_id) != self.admin_qq:
            yield event.plain_result("❌ 此指令仅限管理员使用")
            return
        
        try:
            test_message = (
                "【通知测试】\n"
                f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"插件状态: 运行正常\n"
                f"关键词数量: {len(self.keywords) // 2}\n"
                f"测试说明: 这是一条测试通知消息"
            )
            
            success = await self._send_message_to_admin(test_message, "测试")
            
            if success:
                yield event.plain_result("✅ 测试通知已发送，请检查是否收到")
            else:
                yield event.plain_result("❌ 测试通知发送失败，请查看日志")
                
        except Exception as e:
            logger.error(f"测试通知失败: {e}")
            yield event.plain_result(f"❌ 测试失败: {str(e)}")
    
    @filter.command("暂停监听")
    async def pause_monitor(self, event: AstrMessageEvent):
        """
        暂停关键词监听
        """
        # 检查权限
        sender = event.message_obj.sender
        sender_id = getattr(sender, 'user_id', '')
        
        if str(sender_id) != self.admin_qq:
            yield event.plain_result("❌ 此指令仅限管理员使用")
            return
        
        try:
            self.enable_notification = False
            pause_message = "【插件状态变更】\n关键词监听已暂停\n暂停时间: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 发送暂停通知
            await self._send_message_to_admin(pause_message, "状态变更")
            
            yield event.plain_result("✅ 关键词监听已暂停")
            
        except Exception as e:
            logger.error(f"暂停监听失败: {e}")
            yield event.plain_result(f"❌ 暂停失败: {str(e)}")
    
    @filter.command("恢复监听")
    async def resume_monitor(self, event: AstrMessageEvent):
        """
        恢复关键词监听
        """
        # 检查权限
        sender = event.message_obj.sender
        sender_id = getattr(sender, 'user_id', '')
        
        if str(sender_id) != self.admin_qq:
            yield event.plain_result("❌ 此指令仅限管理员使用")
            return
        
        try:
            self.enable_notification = True
            resume_message = "【插件状态变更】\n关键词监听已恢复\n恢复时间: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 发送恢复通知
            await self._send_message_to_admin(resume_message, "状态变更")
            
            yield event.plain_result("✅ 关键词监听已恢复")
            
        except Exception as e:
            logger.error(f"恢复监听失败: {e}")
            yield event.plain_result(f"❌ 恢复失败: {str(e)}")
    
    @filter.command("添加关键词")
    async def add_keyword(self, event: AstrMessageEvent, keyword: str):
        """
        添加监听关键词
        格式: /添加关键词 <关键词>
        """
        # 检查权限
        sender = event.message_obj.sender
        sender_id = getattr(sender, 'user_id', '')
        
        if str(sender_id) != self.admin_qq:
            yield event.plain_result("❌ 此指令仅限管理员使用")
            return
        
        try:
            if not keyword.strip():
                yield event.plain_result("❌ 关键词不能为空")
                return
            
            # 添加到关键词列表
            keywords_config = self.config.get("keywords", [])
            if keyword not in keywords_config:
                keywords_config.append(keyword)
                self.config["keywords"] = keywords_config
                self.config.save_config()
                
                # 更新运行时关键词
                self.keywords = self._parse_keywords(keywords_config)
                
                yield event.plain_result(f"✅ 已添加关键词: {keyword}\n当前关键词数量: {len(keywords_config)}")
            else:
                yield event.plain_result(f"⚠️ 关键词 '{keyword}' 已存在")
                
        except Exception as e:
            logger.error(f"添加关键词失败: {e}")
            yield event.plain_result(f"❌ 添加失败: {str(e)}")
    
    @filter.command("删除关键词")
    async def remove_keyword(self, event: AstrMessageEvent, keyword: str):
        """
        删除监听关键词
        格式: /删除关键词 <关键词>
        """
        # 检查权限
        sender = event.message_obj.sender
        sender_id = getattr(sender, 'user_id', '')
        
        if str(sender_id) != self.admin_qq:
            yield event.plain_result("❌ 此指令仅限管理员使用")
            return
        
        try:
            keywords_config = self.config.get("keywords", [])
            
            if keyword in keywords_config:
                keywords_config.remove(keyword)
                self.config["keywords"] = keywords_config
                self.config.save_config()
                
                # 更新运行时关键词
                self.keywords = self._parse_keywords(keywords_config)
                
                yield event.plain_result(f"✅ 已删除关键词: {keyword}\n剩余关键词数量: {len(keywords_config)}")
            else:
                yield event.plain_result(f"❌ 关键词 '{keyword}' 不存在")
                
        except Exception as e:
            logger.error(f"删除关键词失败: {e}")
            yield event.plain_result(f"❌ 删除失败: {str(e)}")
    
    async def terminate(self):
        """插件卸载时调用"""
        logger.info("关键词监听插件正在卸载...")
        
        # 取消所有后台任务
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        
        # 等待任务完成
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        
        # 保存数据
        self._save_last_trigger_time()
        self._save_trigger_records()
        self._save_statistics()
        
        # 发送卸载通知
        if self.enable_notification:
            try:
                shutdown_message = (
                    "【插件状态变更】\n"
                    f"新的配置已生效\n"
                    f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"累计触发: {len(self.trigger_records)} 次"
                )
                
                message_chain = MessageChain()
                message_chain.chain = [Plain(shutdown_message)]
                await self.context.send_message(self.admin_umo, message_chain)
            except Exception as e:
                logger.error(f"发送卸载通知失败: {e}")
        
        logger.info("关键词监听插件已完全卸载")
