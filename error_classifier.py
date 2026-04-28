#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ErrorClassifier - 错误分类与优雅降级模块
基于multi_agent.py第707-712行增强，实现精细错误分类
"""

from typing import Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class ErrorCategory(Enum):
    """错误类型枚举（结构化错误上下文）"""
    CODE_ERROR = "code_error"
    NETWORK_ERROR = "network_error"
    FIELD_ERROR = "field_error"  # API字段错误
    PLANNING_ERROR = "planning_error"
    DATA_VACUUM = "data_vacuum"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT = "rate_limit"
    VALIDATION_ERROR = "validation_error"


@dataclass
class ErrorContext:
    """
    结构化错误上下文（参考PrimoAgent结构化输出设计）
    
    替代简单的字符串错误，提供丰富的错误信息供Error Handler精确处理
    """
    category: ErrorCategory
    message: str
    traceback: str = ""
    
    # 代码错误特有
    code_snippet: Optional[str] = None
    line_number: Optional[int] = None
    
    # 字段错误特有（ASA特色：RAG纠错）
    wrong_field: Optional[str] = None
    api_interface: Optional[str] = None
    suggested_field: Optional[str] = None  # RAG查询结果
    
    # 网络错误特有
    status_code: Optional[int] = None
    retry_after: Optional[int] = None
    
    # 元数据
    timestamp: datetime = field(default_factory=datetime.now)
    retry_count: int = 0
    
    def to_dict(self) -> dict:
        """转换为字典（用于state序列化）"""
        return {
            "category": self.category.value,
            "message": self.message,
            "traceback": self.traceback,
            "code_snippet": self.code_snippet,
            "line_number": self.line_number,
            "wrong_field": self.wrong_field,
            "api_interface": self.api_interface,
            "suggested_field": self.suggested_field,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
            "timestamp": self.timestamp.isoformat(),
            "retry_count": self.retry_count
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ErrorContext":
        """从字典恢复"""
        if "category" in data:
            data["category"] = ErrorCategory(data["category"])
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


@dataclass
class ErrorClassification:
    """错误分类结果（向后兼容）"""
    error_type: str           # 错误类型
    is_retryable: bool        # 是否可重试
    strategy: str             # 处理策略
    user_message: str         # 给用户的消息
    should_backoff: bool      # 是否需要退避
    backoff_seconds: int      # 退避秒数
    
    # 新增：结构化上下文
    context: Optional[ErrorContext] = None


class ErrorClassifier:
    """
    错误分类器：将API错误映射到不同的处理策略
    
    分类逻辑：
    1. auth_error - 授权失效（401/403/token过期）→ 不可重试，直接降级
    2. rate_limit - 限流（429/频率限制）→ 可重试，指数退避
    3. network_error - 网络超时 → 可重试，指数退避
    4. data_vacuum - 数据真空（空数据/停牌/未发布）→ 不可重试，优雅降级
    5. code_error - 代码错误（KeyError等）→ 可重试，立即重试
    """
    
    # 错误模式定义
    ERROR_PATTERNS = {
        "auth_error": {
            "patterns": ["授权", "auth", "401", "403", "token", "密钥", "apikey", "认证失败"],
            "is_retryable": False,
            "strategy": "graceful_degradation",
            "user_message": "[ERROR] API授权失效，请联系管理员检查Tushare Token配置"
        },
        "rate_limit": {
            "patterns": ["频率", "limit", "too many", "requests", "429", "限流", "过于频繁", "频繁"],
            "is_retryable": True,
            "strategy": "exponential_backoff",
            "user_message": "[INFO] 请求频率受限，正在自动重试..."
        },
        "network_error": {
            "patterns": ["超时", "timeout", "connection", "网络", "无法连接", "unreachable"],
            "is_retryable": True,
            "strategy": "exponential_backoff",
            "user_message": "[INFO] 网络连接不稳定，正在重试..."
        },
        "data_vacuum": {
            "patterns": ["empty", "无数据", "null", "数据为空", "未找到", "停牌", "退市"],
            "is_retryable": False,
            "strategy": "graceful_degradation",
            "user_message": "[INFO] 该时间段暂无数据，可能原因：1.财报尚未发布 2.股票停牌 3.数据真空期"
        },
        "code_error": {
            "patterns": ["keyerror", "typeerror", "valueerror", "indexerror", "nameerror"],
            "is_retryable": True,
            "strategy": "immediate_retry",
            "user_message": "[INFO] 代码执行异常，正在修复..."
        }
    }
    
    @classmethod
    def classify(cls, error_msg: str, retry_count: int = 0) -> ErrorClassification:
        """
        分类错误并返回处理策略
        
        Args:
            error_msg: 错误信息字符串
            retry_count: 当前重试次数（用于计算退避时间）
        
        Returns:
            ErrorClassification: 分类结果
        """
        if not error_msg:
            return cls._default_classification(retry_count)
        
        error_msg_lower = error_msg.lower()
        
        # 遍历所有错误模式进行匹配
        for error_type, config in cls.ERROR_PATTERNS.items():
            if any(pattern.lower() in error_msg_lower for pattern in config["patterns"]):
                backoff = 2 ** retry_count if config["strategy"] == "exponential_backoff" else 0
                return ErrorClassification(
                    error_type=error_type,
                    is_retryable=config["is_retryable"],
                    strategy=config["strategy"],
                    user_message=config["user_message"],
                    should_backoff=config["strategy"] == "exponential_backoff",
                    backoff_seconds=min(backoff, 30)  # 最大30秒
                )
        
        # 未知错误，默认可重试
        return cls._default_classification(retry_count)
    
    @classmethod
    def _default_classification(cls, retry_count: int) -> ErrorClassification:
        """默认分类：未知错误，允许重试"""
        return ErrorClassification(
            error_type="unknown",
            is_retryable=True,
            strategy="immediate_retry",
            user_message="[INFO] 遇到未知错误，正在尝试修复...",
            should_backoff=False,
            backoff_seconds=0
        )
    
    @classmethod
    def should_reject_query(cls, error_type: str, retry_count: int) -> bool:
        """
        判断是否应拒绝查询（超过最大重试次数或不可重试错误）
        
        Args:
            error_type: 错误类型
            retry_count: 当前重试次数
        
        Returns:
            bool: 是否应拒绝
        """
        # 不可重试的错误直接拒绝
        if error_type in ["auth_error", "data_vacuum"]:
            return True
        
        # 可重试错误但超过阈值也拒绝
        if retry_count >= 3:
            return True
        
        return False


# 便捷函数
def classify_error(error_msg: str, retry_count: int = 0) -> ErrorClassification:
    """便捷函数：快速分类错误"""
    return ErrorClassifier.classify(error_msg, retry_count)


if __name__ == "__main__":
    # 测试用例
    test_cases = [
        "API授权失效,请检查配置",
        "请求过于频繁，请稍后再试",
        "Connection timeout after 30 seconds",
        "KeyError: 'trade_date'",
        "[DATA]: {'error': '无数据'}",
        "股票已停牌，无法获取数据",
        "Unknown error occurred"
    ]
    
    print("=" * 80)
    print("ErrorClassifier 测试")
    print("=" * 80)
    
    for i, test_msg in enumerate(test_cases, 1):
        result = classify_error(test_msg, retry_count=1)
        print(f"\n测试 {i}: {test_msg[:50]}...")
        print(f"  类型: {result.error_type}")
        print(f"  可重试: {result.is_retryable}")
        print(f"  策略: {result.strategy}")
        print(f"  退避: {result.backoff_seconds}s")
        print(f"  用户消息: {result.user_message[:60]}...")
