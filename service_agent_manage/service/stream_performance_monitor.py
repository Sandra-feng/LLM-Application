#!/usr/bin/env python
"""
流式输出性能监控和配置管理
"""

import json
from loguru import logger
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from service_agent_manage.service.call_agent_service import BatchUpdateConfig
# logger = loguru logger (auto-migrated)
@dataclass
class PerformanceMetrics:
    """性能指标"""

    total_tokens: int = 0
    total_db_writes: int = 0
    total_response_time: float = 0.0
    avg_tokens_per_write: float = 0.0
    db_write_frequency: float = 0.0  # 每秒写入次数
    memory_usage_mb: float = 0.0
    queue_size: int = 0
    error_count: int = 0

    def to_dict(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "total_db_writes": self.total_db_writes,
            "total_response_time": self.total_response_time,
            "avg_tokens_per_write": self.avg_tokens_per_write,
            "db_write_frequency": self.db_write_frequency,
            "memory_usage_mb": self.memory_usage_mb,
            "queue_size": self.queue_size,
            "error_count": self.error_count,
        }


@dataclass
class AdaptiveConfig:
    """自适应配置"""

    base_batch_size: int = 10
    base_time_interval: float = 0.5
    max_batch_size: int = 50
    min_batch_size: int = 1
    max_time_interval: float = 2.0
    min_time_interval: float = 0.1

    # 自适应阈值
    high_load_threshold: float = 0.8  # CPU/内存使用率阈值
    low_latency_threshold: float = 0.1  # 延迟阈值（秒）
    error_rate_threshold: float = 0.05  # 错误率阈值

    def adjust_for_load(self, current_load: float) -> "AdaptiveConfig":
        """根据负载调整配置"""
        if current_load > self.high_load_threshold:
            # 高负载：增加批量大小，减少写入频率
            self.base_batch_size = min(self.max_batch_size, self.base_batch_size * 2)
            self.base_time_interval = min(self.max_time_interval, self.base_time_interval * 1.5)
        elif current_load < 0.3:
            # 低负载：减少批量大小，提高响应性
            self.base_batch_size = max(self.min_batch_size, self.base_batch_size // 2)
            self.base_time_interval = max(self.min_time_interval, self.base_time_interval * 0.8)

        return self


class StreamPerformanceMonitor:
    """流式输出性能监控器"""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.metrics_history = deque(maxlen=window_size)
        self.current_metrics = PerformanceMetrics()
        self.session_metrics = defaultdict(PerformanceMetrics)
        self.start_time = time.time()

        # 实时监控数据
        self.token_timestamps = deque(maxlen=1000)
        self.write_timestamps = deque(maxlen=1000)
        self.error_timestamps = deque(maxlen=100)

        # 配置管理
        self.adaptive_config = AdaptiveConfig()

    def record_token(self, talk_id: str, token_count: int = 1):
        """记录token处理"""
        current_time = time.time()
        self.token_timestamps.append(current_time)
        self.current_metrics.total_tokens += token_count
        self.session_metrics[talk_id].total_tokens += token_count

    def record_db_write(self, talk_id: str, token_count: int):
        """记录数据库写入"""
        current_time = time.time()
        self.write_timestamps.append(current_time)
        self.current_metrics.total_db_writes += 1
        self.session_metrics[talk_id].total_db_writes += 1

        # 更新平均token数
        if self.current_metrics.total_db_writes > 0:
            self.current_metrics.avg_tokens_per_write = (
                self.current_metrics.total_tokens / self.current_metrics.total_db_writes
            )

    def record_error(self, talk_id: str, error_type: str):
        """记录错误"""
        current_time = time.time()
        self.error_timestamps.append(current_time)
        self.current_metrics.error_count += 1
        self.session_metrics[talk_id].error_count += 1

        logger.warning(f"流式输出错误 - 会话: {talk_id}, 类型: {error_type}")

    def calculate_real_time_metrics(self) -> PerformanceMetrics:
        """计算实时性能指标"""
        current_time = time.time()
        time_window = 60.0  # 1分钟窗口

        # 计算写入频率
        recent_writes = [t for t in self.write_timestamps if current_time - t <= time_window]
        self.current_metrics.db_write_frequency = len(recent_writes) / time_window

        # 计算总响应时间
        self.current_metrics.total_response_time = current_time - self.start_time

        return self.current_metrics

    def get_adaptive_config(self, talk_id: str) -> AdaptiveConfig:
        """获取自适应配置"""
        metrics = self.calculate_real_time_metrics()

        # 计算当前负载（简化版本）
        current_load = min(1.0, metrics.db_write_frequency / 10.0)  # 假设10次/秒为满负载

        # 调整配置
        return self.adaptive_config.adjust_for_load(current_load)

    def get_session_summary(self, talk_id: str) -> dict:
        """获取会话性能摘要"""
        session_metrics = self.session_metrics.get(talk_id, PerformanceMetrics())

        return {
            "talk_id": talk_id,
            "metrics": session_metrics.to_dict(),
            "efficiency_score": self._calculate_efficiency_score(session_metrics),
            "recommendations": self._generate_recommendations(session_metrics),
        }

    def _calculate_efficiency_score(self, metrics: PerformanceMetrics) -> float:
        """计算效率分数 (0-100)"""
        if metrics.total_tokens == 0:
            return 0.0

        # 基于多个因素计算效率分数
        token_efficiency = min(100, metrics.avg_tokens_per_write * 2)  # 每次写入更多token更高效
        error_penalty = max(0, 100 - metrics.error_count * 10)  # 错误越少越好

        return (token_efficiency + error_penalty) / 2

    def _generate_recommendations(self, metrics: PerformanceMetrics) -> list[str]:
        """生成优化建议"""
        recommendations = []

        if metrics.avg_tokens_per_write < 5:
            recommendations.append("建议增加批量大小以减少数据库写入频率")

        if metrics.error_count > 0:
            recommendations.append("检查错误日志，优化错误处理机制")

        if metrics.total_db_writes > metrics.total_tokens * 0.5:
            recommendations.append("数据库写入过于频繁，考虑增加缓冲时间")

        return recommendations

    def export_metrics(self, filepath: str):
        """导出性能指标"""
        export_data = {
            "timestamp": time.time(),
            "current_metrics": self.current_metrics.to_dict(),
            "session_metrics": {talk_id: metrics.to_dict() for talk_id, metrics in self.session_metrics.items()},
            "adaptive_config": {
                "base_batch_size": self.adaptive_config.base_batch_size,
                "base_time_interval": self.adaptive_config.base_time_interval,
                "current_load_estimate": min(1.0, self.current_metrics.db_write_frequency / 10.0),
            },
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            logger.info(f"性能指标已导出到: {filepath}")
        except Exception as e:
            logger.error(f"导出性能指标失败: {str(e)}", exc_info=True)


# 全局性能监控器实例
_global_monitor = None


def get_performance_monitor() -> StreamPerformanceMonitor:
    """获取全局性能监控器"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = StreamPerformanceMonitor()
    return _global_monitor


class PerformanceOptimizedBatchConfig:
    """基于性能监控的动态批量配置"""

    def __init__(self, talk_id: str):
        self.talk_id = talk_id
        self.monitor = get_performance_monitor()

    def get_current_config(self) -> "BatchUpdateConfig":
        """获取当前优化配置"""
        from service_agent_manage.service.call_agent_service import BatchUpdateConfig

        adaptive_config = self.monitor.get_adaptive_config(self.talk_id)

        return BatchUpdateConfig(
            batch_size=adaptive_config.base_batch_size,
            time_interval=adaptive_config.base_time_interval,
            max_buffer_size=adaptive_config.max_batch_size * 2,
            force_update_on_thinking_complete=True,
        )

    def record_operation(self, operation_type: str, **kwargs):
        """记录操作"""
        if operation_type == "token":
            self.monitor.record_token(self.talk_id, kwargs.get("count", 1))
        elif operation_type == "db_write":
            self.monitor.record_db_write(self.talk_id, kwargs.get("token_count", 0))
        elif operation_type == "error":
            self.monitor.record_error(self.talk_id, kwargs.get("error_type", "unknown"))
