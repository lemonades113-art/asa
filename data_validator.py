#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据验证器 - API返回数据验证 + 自动重试逻辑

【核心流程】
┌─────────────────────────────────────────────────────────────────┐
│                    数据验证闭环 (Data Validation Loop)           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: API 调用                                                │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  Tushare API → 获取原始数据                          │       │
│  └──────────────────────────────────────────────────────┘       │
│                              ↓                                   │
│  Step 2: 数据验证 (5类问题检测)                                  │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  1. 空数据检测 (empty_data)                          │       │
│  │  2. 缺失字段检测 (missing_fields)                    │       │
│  │  3. 类型错误检测 (type_error)                        │       │
│  │  4. 数值异常检测 (value_anomaly)                     │       │
│  │  5. 格式错误检测 (format_error)                      │       │
│  └──────────────────────────────────────────────────────┘       │
│                              ↓                                   │
│  Step 3: 定向修复                                                │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  空数据      →  调整查询参数/换API                   │       │
│  │  类型错误    →  自动类型转换                         │       │
│  │  数值异常    →  过滤异常值                           │       │
│  │  格式错误    →  格式修正                             │       │
│  └──────────────────────────────────────────────────────┘       │
│                              ↓                                   │
│  Step 4: 再验证（循环 Step 2-3 直到通过或达到上限）              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

【与面经框架对齐】
- Self-Healing: 自动检测并修复数据问题
- Error-Specific: 不同问题类型使用不同修复策略
- 闭环验证: 修复后必须通过验证才算成功
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Callable, Dict, Any, Union
from datetime import datetime
import traceback
import re


# =============================================================================
# 1. 数据问题类型定义
# =============================================================================

class DataIssueType(Enum):
    """数据问题类型"""
    EMPTY_DATA = "empty_data"           # 空数据
    MISSING_FIELDS = "missing_fields"   # 缺失字段
    TYPE_ERROR = "type_error"           # 类型错误
    VALUE_ANOMALY = "value_anomaly"     # 数值异常
    FORMAT_ERROR = "format_error"       # 格式错误
    DATE_ERROR = "date_error"           # 日期格式错误
    API_ERROR = "api_error"             # API调用错误
    RATE_LIMIT = "rate_limit"           # 频率限制
    NO_ISSUE = "no_issue"               # 无问题


@dataclass
class ValidationIssue:
    """验证问题详情"""
    issue_type: DataIssueType
    severity: str  # "critical", "warning", "info"
    field_name: Optional[str] = None
    description: str = ""
    suggestion: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "type": self.issue_type.value,
            "severity": self.severity,
            "field": self.field_name,
            "description": self.description,
            "suggestion": self.suggestion
        }


@dataclass
class ValidationResult:
    """验证结果"""
    passed: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    fixed_data: Optional[pd.DataFrame] = None
    fix_applied: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
            "fix_applied": self.fix_applied
        }
    
    @property
    def has_critical_issues(self) -> bool:
        return any(i.severity == "critical" for i in self.issues)


@dataclass
class RetryResult:
    """重试结果"""
    success: bool
    final_data: Optional[pd.DataFrame]
    total_attempts: int
    validation_history: List[ValidationResult]
    error_progression: List[str]
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "total_attempts": self.total_attempts,
            "error_progression": self.error_progression,
            "has_data": self.final_data is not None and not self.final_data.empty
        }


# =============================================================================
# 2. 数据验证器
# =============================================================================

class DataValidator:
    """
    数据验证器 - 多维度验证 API 返回数据
    
    验证维度：
    1. 完整性验证（数据非空、必需字段存在）
    2. 类型验证（数值类型、日期类型）
    3. 范围验证（数值在合理范围内）
    4. 格式验证（日期格式、代码格式）
    """
    
    # 常见金融字段的预期类型
    FIELD_TYPE_MAP = {
        # 数值字段
        "revenue": "numeric",
        "n_income": "numeric",
        "net_profit": "numeric",
        "eps": "numeric",
        "roe": "numeric",
        "pe": "numeric",
        "pb": "numeric",
        "ps": "numeric",
        "close": "numeric",
        "open": "numeric",
        "high": "numeric",
        "low": "numeric",
        "vol": "numeric",
        "amount": "numeric",
        "dv_ratio": "numeric",
        "dv_ttm": "numeric",
        "total_mv": "numeric",
        "circ_mv": "numeric",
        
        # 日期字段
        "trade_date": "date",
        "ann_date": "date",
        "end_date": "date",
        "list_date": "date",
        "delist_date": "date",
        
        # 整数字段
        "report_type": "integer",
        "comp_type": "integer",
        
        # 字符串字段
        "ts_code": "string",
        "name": "string",
        "industry": "string",
    }
    
    # 数值范围验证（合理的金融数据范围）
    VALUE_RANGE_MAP = {
        "pe": (-1000, 10000),       # 市盈率
        "pb": (-100, 1000),         # 市净率
        "ps": (0, 10000),           # 市销率
        "roe": (-1000, 1000),       # ROE (%)
        "eps": (-100, 1000),        # 每股收益
        "dv_ratio": (0, 50),        # 股息率 (%)
        "close": (0, 100000),       # 股价
        "vol": (0, 1e12),           # 成交量
    }
    
    def __init__(self, 
                 required_fields: List[str] = None,
                 strict_mode: bool = False,
                 auto_fix: bool = True):
        """
        初始化验证器
        
        Args:
            required_fields: 必需字段列表
            strict_mode: 严格模式（所有警告视为错误）
            auto_fix: 是否自动修复可修复的问题
        """
        self.required_fields = required_fields or []
        self.strict_mode = strict_mode
        self.auto_fix = auto_fix
    
    def validate(self, 
                 data: pd.DataFrame,
                 context: str = "") -> ValidationResult:
        """
        验证数据
        
        Args:
            data: 待验证的 DataFrame
            context: 上下文信息（用于错误消息）
        
        Returns:
            ValidationResult
        """
        issues = []
        fixed_data = data.copy() if data is not None and not data.empty else None
        fix_applied = []
        
        # Step 1: 空数据检测
        if data is None or data.empty:
            issues.append(ValidationIssue(
                issue_type=DataIssueType.EMPTY_DATA,
                severity="critical",
                description=f"API返回空数据 {context}",
                suggestion="检查查询参数是否正确，或尝试扩大日期范围"
            ))
            return ValidationResult(passed=False, issues=issues)
        
        # Step 2: 缺失字段检测
        for field in self.required_fields:
            if field not in data.columns:
                issues.append(ValidationIssue(
                    issue_type=DataIssueType.MISSING_FIELDS,
                    severity="critical",
                    field_name=field,
                    description=f"缺少必需字段: {field}",
                    suggestion=f"检查API是否返回字段 {field}，或字段名是否变更"
                ))
        
        # Step 3: 类型验证 + 自动修复
        for col in data.columns:
            expected_type = self.FIELD_TYPE_MAP.get(col)
            if not expected_type:
                continue
            
            type_result = self._validate_field_type(fixed_data, col, expected_type)
            if type_result[0]:  # 有问题
                issues.append(type_result[0])
                
                # 尝试自动修复
                if self.auto_fix and type_result[1] is not None:
                    fixed_data[col] = type_result[1]
                    fix_applied.append(f"类型转换: {col} → {expected_type}")
        
        # Step 4: 数值范围验证
        for col in data.columns:
            if col in self.VALUE_RANGE_MAP:
                range_result = self._validate_value_range(fixed_data, col)
                if range_result[0]:
                    issues.append(range_result[0])
                    
                    if self.auto_fix and range_result[1] is not None:
                        fixed_data[col] = range_result[1]
                        fix_applied.append(f"数值修正: {col}")
        
        # Step 5: 日期格式验证
        for col in data.columns:
            if self.FIELD_TYPE_MAP.get(col) == "date":
                date_result = self._validate_date_format(fixed_data, col)
                if date_result[0]:
                    issues.append(date_result[0])
        
        # 计算是否通过
        has_critical = any(i.severity == "critical" for i in issues)
        passed = not has_critical
        if self.strict_mode:
            passed = len(issues) == 0
        
        return ValidationResult(
            passed=passed,
            issues=issues,
            fixed_data=fixed_data,
            fix_applied=fix_applied
        )
    
    def _validate_field_type(self, 
                             data: pd.DataFrame, 
                             col: str,
                             expected_type: str) -> Tuple[Optional[ValidationIssue], Optional[pd.Series]]:
        """验证字段类型"""
        try:
            if expected_type == "numeric":
                # 检测非数值
                if not pd.api.types.is_numeric_dtype(data[col]):
                    # 尝试转换
                    converted = pd.to_numeric(data[col], errors='coerce')
                    nan_count = converted.isna().sum() - data[col].isna().sum()
                    
                    if nan_count > 0:
                        issue = ValidationIssue(
                            issue_type=DataIssueType.TYPE_ERROR,
                            severity="warning",
                            field_name=col,
                            description=f"字段 {col} 包含 {nan_count} 个非数值",
                            suggestion="已自动转换为数值类型，非法值设为 NaN"
                        )
                        return (issue, converted)
                    else:
                        return (None, converted)
            
            elif expected_type == "integer":
                if not pd.api.types.is_integer_dtype(data[col]):
                    converted = pd.to_numeric(data[col], errors='coerce')
                    return (None, converted)
            
            elif expected_type == "date":
                # 日期类型单独处理
                pass
            
        except Exception as e:
            issue = ValidationIssue(
                issue_type=DataIssueType.TYPE_ERROR,
                severity="warning",
                field_name=col,
                description=f"类型转换失败: {str(e)[:50]}",
                suggestion="检查数据格式"
            )
            return (issue, None)
        
        return (None, None)
    
    def _validate_value_range(self, 
                              data: pd.DataFrame,
                              col: str) -> Tuple[Optional[ValidationIssue], Optional[pd.Series]]:
        """验证数值范围"""
        try:
            min_val, max_val = self.VALUE_RANGE_MAP.get(col, (None, None))
            if min_val is None:
                return (None, None)
            
            # 检测超出范围的值
            out_of_range = ((data[col] < min_val) | (data[col] > max_val)) & data[col].notna()
            count = out_of_range.sum()
            
            if count > 0:
                issue = ValidationIssue(
                    issue_type=DataIssueType.VALUE_ANOMALY,
                    severity="warning",
                    field_name=col,
                    description=f"字段 {col} 有 {count} 个值超出正常范围 [{min_val}, {max_val}]",
                    suggestion="已过滤异常值"
                )
                
                # 修复：将异常值设为 NaN
                fixed = data[col].copy()
                fixed[out_of_range] = np.nan
                return (issue, fixed)
        
        except Exception as e:
            pass
        
        return (None, None)
    
    def _validate_date_format(self, 
                              data: pd.DataFrame,
                              col: str) -> Tuple[Optional[ValidationIssue], None]:
        """验证日期格式"""
        try:
            # 尝试解析日期
            sample = data[col].dropna().iloc[:5] if len(data[col].dropna()) > 0 else []
            
            for val in sample:
                if not isinstance(val, str):
                    continue
                
                # 检测常见的日期格式
                if not re.match(r'^\d{8}$|^\d{4}-\d{2}-\d{2}$', str(val)):
                    return (ValidationIssue(
                        issue_type=DataIssueType.DATE_ERROR,
                        severity="warning",
                        field_name=col,
                        description=f"日期格式不标准: {val}",
                        suggestion="建议使用 YYYYMMDD 或 YYYY-MM-DD 格式"
                    ), None)
        
        except Exception as e:
            pass
        
        return (None, None)


# =============================================================================
# 3. 自动重试器
# =============================================================================

class DataRetrier:
    """
    数据自动重试器 - 基于验证反馈的闭环重试
    
    【核心策略】
    1. 空数据 → 调整参数重试
    2. 频率限制 → 等待后重试
    3. 类型错误 → 自动修复
    4. 持续失败 → 降级策略
    """
    
    def __init__(self,
                 validator: DataValidator = None,
                 max_retries: int = 3,
                 retry_delay: float = 1.0):
        """
        初始化重试器
        
        Args:
            validator: 数据验证器
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）
        """
        self.validator = validator or DataValidator()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
    
    def execute_with_retry(self,
                           api_func: Callable,
                           api_params: Dict,
                           fallback_params: List[Dict] = None,
                           context: str = "") -> RetryResult:
        """
        执行 API 调用并自动重试
        
        Args:
            api_func: API 调用函数
            api_params: 初始参数
            fallback_params: 备选参数列表
            context: 上下文信息
        
        Returns:
            RetryResult
        """
        import time
        
        validation_history = []
        error_progression = []
        current_params = api_params.copy()
        fallback_index = 0
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Step 1: 调用 API
                print(f"[🔄 重试 {attempt}/{self.max_retries}] 参数: {current_params}")
                data = api_func(**current_params)
                
                # Step 2: 验证数据
                validation = self.validator.validate(data, context)
                validation_history.append(validation)
                
                # 记录错误类型
                if validation.issues:
                    error_types = [i.issue_type.value for i in validation.issues[:2]]
                    error_progression.append(f"Attempt{attempt}: {','.join(error_types)}")
                
                # Step 3: 检查是否通过
                if validation.passed:
                    print(f"[✅ 验证通过] 第 {attempt} 次尝试成功")
                    return RetryResult(
                        success=True,
                        final_data=validation.fixed_data,
                        total_attempts=attempt,
                        validation_history=validation_history,
                        error_progression=error_progression
                    )
                
                # Step 4: 根据问题类型调整参数
                adjusted = self._adjust_params(current_params, validation, fallback_params, fallback_index)
                if adjusted[0]:
                    current_params = adjusted[0]
                    fallback_index = adjusted[1]
                
                # 等待后重试
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
            
            except Exception as e:
                error_msg = str(e)[:100]
                error_progression.append(f"Attempt{attempt}: API_ERROR - {error_msg}")
                
                # 检测是否为频率限制
                if "rate limit" in error_msg.lower() or "too many" in error_msg.lower():
                    print(f"[⏳ 频率限制] 等待 {self.retry_delay * 2} 秒后重试")
                    time.sleep(self.retry_delay * 2)
                elif attempt < self.max_retries:
                    time.sleep(self.retry_delay)
        
        # 所有重试失败
        print(f"[❌ 重试失败] 达到最大重试次数 {self.max_retries}")
        
        # 返回最后一次的数据（即使有问题）
        last_validation = validation_history[-1] if validation_history else None
        return RetryResult(
            success=False,
            final_data=last_validation.fixed_data if last_validation else None,
            total_attempts=self.max_retries,
            validation_history=validation_history,
            error_progression=error_progression
        )
    
    def _adjust_params(self,
                       current_params: Dict,
                       validation: ValidationResult,
                       fallback_params: List[Dict],
                       fallback_index: int) -> Tuple[Optional[Dict], int]:
        """根据验证结果调整参数"""
        new_params = current_params.copy()
        
        for issue in validation.issues:
            if issue.issue_type == DataIssueType.EMPTY_DATA:
                # 空数据：尝试扩大日期范围或使用备选参数
                if fallback_params and fallback_index < len(fallback_params):
                    return (fallback_params[fallback_index], fallback_index + 1)
                
                # 尝试扩大日期范围
                if 'start_date' in new_params:
                    try:
                        start = pd.to_datetime(new_params['start_date'])
                        new_start = (start - pd.Timedelta(days=30)).strftime('%Y%m%d')
                        new_params['start_date'] = new_start
                        return (new_params, fallback_index)
                    except:
                        pass
        
        # 没有特殊处理，尝试下一个备选参数
        if fallback_params and fallback_index < len(fallback_params):
            return (fallback_params[fallback_index], fallback_index + 1)
        
        return (None, fallback_index)


# =============================================================================
# 4. 便捷接口
# =============================================================================

def create_data_validator(
    required_fields: List[str] = None,
    strict_mode: bool = False,
    auto_fix: bool = True
) -> DataValidator:
    """创建数据验证器"""
    return DataValidator(
        required_fields=required_fields,
        strict_mode=strict_mode,
        auto_fix=auto_fix
    )


def create_data_retrier(
    validator: DataValidator = None,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> DataRetrier:
    """创建数据重试器"""
    return DataRetrier(
        validator=validator,
        max_retries=max_retries,
        retry_delay=retry_delay
    )


def validate_and_fix(data: pd.DataFrame, 
                     required_fields: List[str] = None) -> Tuple[bool, pd.DataFrame, List[str]]:
    """
    便捷函数：验证并修复数据
    
    Args:
        data: 待验证的 DataFrame
        required_fields: 必需字段
    
    Returns:
        (passed, fixed_data, issues_summary)
    """
    validator = DataValidator(required_fields=required_fields or [])
    result = validator.validate(data)
    
    issues_summary = [f"{i.issue_type.value}: {i.description}" for i in result.issues]
    
    return (result.passed, result.fixed_data, issues_summary)


# =============================================================================
# 5. 测试代码
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("数据验证模块测试")
    print("=" * 60)
    
    # 创建验证器
    validator = DataValidator(required_fields=["ts_code", "trade_date", "close"])
    
    # 测试用例 1: 正常数据
    print("\n测试1 - 正常数据:")
    normal_data = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": ["20231201", "20231202"],
        "close": [10.5, 11.0],
        "pe": [15.0, 16.0]
    })
    result = validator.validate(normal_data)
    print(f"  通过: {result.passed}")
    print(f"  问题数: {len(result.issues)}")
    
    # 测试用例 2: 空数据
    print("\n测试2 - 空数据:")
    empty_data = pd.DataFrame()
    result = validator.validate(empty_data)
    print(f"  通过: {result.passed}")
    print(f"  问题类型: {result.issues[0].issue_type.value if result.issues else 'None'}")
    
    # 测试用例 3: 类型错误
    print("\n测试3 - 类型错误:")
    type_error_data = pd.DataFrame({
        "ts_code": ["000001.SZ"],
        "trade_date": ["20231201"],
        "close": ["10.5元"],  # 字符串类型，需要转换
        "report_type": ["1"]   # 字符串 "1"，需要转为整数
    })
    result = validator.validate(type_error_data)
    print(f"  通过: {result.passed}")
    print(f"  修复应用: {result.fix_applied}")
    if result.fixed_data is not None:
        print(f"  修复后 close 类型: {result.fixed_data['close'].dtype}")
    
    # 测试用例 4: 数值异常
    print("\n测试4 - 数值异常:")
    anomaly_data = pd.DataFrame({
        "ts_code": ["000001.SZ"],
        "trade_date": ["20231201"],
        "close": [10.5],
        "pe": [99999]  # 超出正常范围
    })
    result = validator.validate(anomaly_data)
    print(f"  通过: {result.passed}")
    for issue in result.issues:
        print(f"  问题: {issue.description}")
    
    # 测试用例 5: 缺失字段
    print("\n测试5 - 缺失字段:")
    missing_data = pd.DataFrame({
        "ts_code": ["000001.SZ"],
        "close": [10.5]
        # 缺少 trade_date
    })
    result = validator.validate(missing_data)
    print(f"  通过: {result.passed}")
    for issue in result.issues:
        print(f"  问题: {issue.description}")
    
    print("\n" + "=" * 60)
    print("便捷函数测试")
    print("=" * 60)
    
    passed, fixed, issues = validate_and_fix(type_error_data, ["ts_code", "close"])
    print(f"验证通过: {passed}")
    print(f"问题摘要: {issues}")
