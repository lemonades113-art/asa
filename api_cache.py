#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
API响应缓存模块
解决：rate_limit限流问题，减少重复API调用

缓存策略：
- TTL: 5分钟（实时性数据）/ 1小时（历史数据）
- Key: API名称+参数哈希
- 内存存储 + 可选持久化
"""

import hashlib
import json
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    data: Any
    created_at: float
    ttl_seconds: int
    api_name: str
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.created_at > self.ttl_seconds
    
    def get_age_seconds(self) -> float:
        """获取缓存年龄"""
        return time.time() - self.created_at


class APICache:
    """
    API响应缓存管理器
    
    使用示例：
        cache = APICache()
        
        # 查询缓存
        result = cache.get("daily_basic", ts_code="000001.SZ")
        if result:
            return result
        
        # 调用API并缓存
        data = pro.daily_basic(ts_code="000001.SZ")
        cache.set("daily_basic", data, ts_code="000001.SZ")
        return data
    """
    
    # 不同API的TTL配置（秒）
    DEFAULT_TTL = 300  # 5分钟默认
    API_TTL_CONFIG = {
        # 实时行情数据 - 短TTL
        "daily_basic": 60,      # 1分钟
        "daily": 60,            # 1分钟
        "quote": 30,            # 30秒
        
        # 财务数据 - 中等TTL
        "income": 3600,         # 1小时
        "balance_sheet": 3600,  # 1小时
        "cashflow": 3600,       # 1小时
        "fina_indicator": 1800, # 30分钟
        
        # 静态数据 - 长TTL
        "stock_basic": 86400,   # 1天
        "trade_cal": 86400,     # 1天
        "namechange": 86400,    # 1天
        
        # 分红数据 - 中等TTL
        "dividend": 1800,       # 30分钟
    }
    
    def __init__(self, max_size: int = 1000):
        """
        初始化缓存
        
        Args:
            max_size: 最大缓存条目数，超过则LRU淘汰
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._hit_count = 0
        self._miss_count = 0
        
        print(f"[APICache] 初始化完成，最大缓存数: {max_size}")
    
    def _generate_key(self, api_name: str, **params) -> str:
        """
        生成缓存Key
        
        Args:
            api_name: API名称
            **params: API参数
        
        Returns:
            缓存Key字符串
        """
        # 排序参数确保一致性
        param_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        key_base = f"{api_name}:{param_str}"
        return hashlib.md5(key_base.encode()).hexdigest()[:16]
    
    def get(self, api_name: str, **params) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            api_name: API名称
            **params: API参数
        
        Returns:
            缓存数据或None
        """
        key = self._generate_key(api_name, **params)
        
        if key not in self._cache:
            self._miss_count += 1
            return None
        
        entry = self._cache[key]
        
        # 检查过期
        if entry.is_expired():
            del self._cache[key]
            self._miss_count += 1
            print(f"[APICache] 缓存过期: {api_name} ({entry.get_age_seconds():.0f}s)")
            return None
        
        # 更新访问时间（LRU）
        self._cache.move_to_end(key)
        self._hit_count += 1
        
        age = entry.get_age_seconds()
        print(f"[APICache] 缓存命中: {api_name} (年龄: {age:.0f}s)")
        
        return entry.data
    
    def set(self, api_name: str, data: Any, **params) -> str:
        """
        设置缓存数据
        
        Args:
            api_name: API名称
            data: 要缓存的数据
            **params: API参数
        
        Returns:
            缓存Key
        """
        key = self._generate_key(api_name, **params)
        ttl = self.API_TTL_CONFIG.get(api_name, self.DEFAULT_TTL)
        
        # LRU淘汰
        while len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            print(f"[APICache] LRU淘汰: {self._cache[oldest_key].api_name if oldest_key in self._cache else 'unknown'}")
        
        entry = CacheEntry(
            key=key,
            data=data,
            created_at=time.time(),
            ttl_seconds=ttl,
            api_name=api_name
        )
        
        self._cache[key] = entry
        print(f"[APICache] 缓存设置: {api_name} (TTL: {ttl}s)")
        
        return key
    
    def invalidate(self, api_name: str = None):
        """
        使缓存失效
        
        Args:
            api_name: 指定API名称，None则清空所有
        """
        if api_name is None:
            count = len(self._cache)
            self._cache.clear()
            print(f"[APICache] 清空所有缓存: {count}条")
        else:
            keys_to_delete = [
                k for k, v in self._cache.items() 
                if v.api_name == api_name
            ]
            for k in keys_to_delete:
                del self._cache[k]
            print(f"[APICache] 清空 {api_name} 缓存: {len(keys_to_delete)}条")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total_requests = self._hit_count + self._miss_count
        hit_rate = self._hit_count / total_requests if total_requests > 0 else 0
        
        # 按API统计
        api_stats = {}
        for entry in self._cache.values():
            api_stats[entry.api_name] = api_stats.get(entry.api_name, 0) + 1
        
        return {
            "total_entries": len(self._cache),
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": f"{hit_rate:.1%}",
            "api_distribution": api_stats
        }
    
    def cleanup_expired(self) -> int:
        """
        清理过期缓存
        
        Returns:
            清理的条目数
        """
        expired_keys = [
            k for k, v in self._cache.items() 
            if v.is_expired()
        ]
        for k in expired_keys:
            del self._cache[k]
        
        if expired_keys:
            print(f"[APICache] 清理过期: {len(expired_keys)}条")
        
        return len(expired_keys)


# 全局缓存实例
_global_api_cache = None

def get_api_cache() -> APICache:
    """获取全局API缓存实例"""
    global _global_api_cache
    if _global_api_cache is None:
        _global_api_cache = APICache(max_size=500)
    return _global_api_cache


def cached_api_call(api_name: str, ttl: int = None):
    """
    装饰器：缓存API调用
    
    使用示例：
        @cached_api_call("daily_basic", ttl=60)
        def fetch_daily_basic(ts_code: str):
            return pro.daily_basic(ts_code=ts_code)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache = get_api_cache()
            
            # 尝试从缓存获取
            cached_result = cache.get(api_name, **kwargs)
            if cached_result is not None:
                return cached_result
            
            # 调用API
            result = func(*args, **kwargs)
            
            # 缓存结果
            cache.set(api_name, result, **kwargs)
            
            return result
        return wrapper
    return decorator


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("=== API缓存模块测试 ===\n")
    
    cache = APICache(max_size=100)
    
    # 测试1: 基本缓存
    print("【测试1】基本缓存")
    cache.set("daily_basic", {"pe": 15.2, "pb": 2.1}, ts_code="000001.SZ")
    result = cache.get("daily_basic", ts_code="000001.SZ")
    print(f"缓存数据: {result}\n")
    
    # 测试2: 缓存命中
    print("【测试2】缓存命中")
    result = cache.get("daily_basic", ts_code="000001.SZ")
    print(f"再次获取: {result}")
    print(f"统计: {cache.get_stats()}\n")
    
    # 测试3: 不同API不同TTL
    print("【测试3】TTL配置")
    print(f"daily_basic TTL: {cache.API_TTL_CONFIG.get('daily_basic', cache.DEFAULT_TTL)}s")
    print(f"income TTL: {cache.API_TTL_CONFIG.get('income', cache.DEFAULT_TTL)}s")
    print(f"stock_basic TTL: {cache.API_TTL_CONFIG.get('stock_basic', cache.DEFAULT_TTL)}s\n")
    
    # 测试4: 缓存失效
    print("【测试4】缓存失效")
    cache.invalidate("daily_basic")
    result = cache.get("daily_basic", ts_code="000001.SZ")
    print(f"失效后获取: {result}\n")
    
    print("=== 测试完成 ===")
