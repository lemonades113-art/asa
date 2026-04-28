"""
改进的KernelManager - 带内存管理和自动清理
这是面试时可以提出的优化方案
"""

import time
import threading
import psutil  # 需要: pip install psutil
from typing import Dict, Tuple, Union, Optional
from lib import StatefulPythonKernel, OpenSandboxKernel


class ImprovedKernelManager:
    """
    生产级内核管理器
    
    【核心特性】
    1. 每kernel一个独立的Lock（不是全局锁）→ 高并发
    2. 自动LRU清理 → 不活跃kernel自动释放
    3. 内存监控 → 单个kernel超过阈值时警告
    4. 统计信息 → 便于运维监控
    """
    
    def __init__(self, 
                 max_kernels: int = 100,           # 最多保留100个kernel
                 inactivity_timeout: int = 1800,  # 30分钟不活跃自动释放
                 memory_limit_mb: int = 500,       # 单个kernel最多500MB
                 cleanup_interval: int = 300):     # 每5分钟检查一次
        
        self._kernels: Dict[str, StatefulPythonKernel] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._last_access: Dict[str, float] = {}  # ← 时间戳追踪
        self._memory_usage: Dict[str, int] = {}   # ← 内存监控
        
        self._manager_lock = threading.Lock()  # 保护字典本身
        self._max_kernels = max_kernels
        self._inactivity_timeout = inactivity_timeout
        self._memory_limit_mb = memory_limit_mb
        self._cleanup_interval = cleanup_interval
        
        self._stats = {
            "total_created": 0,
            "total_released": 0,
            "oom_events": 0,
            "timeout_releases": 0
        }
        
        # 启动后台清理线程
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        """启动后台清理线程"""
        def cleanup_loop():
            while True:
                time.sleep(self._cleanup_interval)
                self.cleanup_inactive_kernels()
                self.check_memory_usage()
        
        cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        cleanup_thread.start()
        print(f"[KernelManager] 后台清理线程已启动 (间隔{self._cleanup_interval}秒)")
    
    def get_kernel(self, thread_id: str) -> Tuple[StatefulPythonKernel, threading.Lock]:
        """
        获取kernel，如果达到上限则触发LRU清理
        """
        with self._manager_lock:
            # 记录访问时间
            self._last_access[thread_id] = time.time()
            
            if thread_id in self._kernels:
                return self._kernels[thread_id], self._locks[thread_id]
            
            # 检查是否达到上限
            if len(self._kernels) >= self._max_kernels:
                # 触发LRU清理：删除最久未使用的kernel
                self._evict_lru_kernel()
            
            # 创建新kernel
            kernel = StatefulPythonKernel()
            lock = threading.Lock()
            
            self._kernels[thread_id] = kernel
            self._locks[thread_id] = lock
            self._last_access[thread_id] = time.time()
            
            self._stats["total_created"] += 1
            print(f"[KernelManager] 为 {thread_id} 创建新内核 (当前活跃: {len(self._kernels)})")
            
            return kernel, lock
    
    def _evict_lru_kernel(self):
        """
        删除最久未使用的kernel（LRU淘汰）
        """
        if not self._kernels:
            return
        
        # 找到最久未访问的thread_id
        lru_thread = min(self._last_access.items(), key=lambda x: x[1])[0]
        
        kernel = self._kernels[lru_thread]
        if hasattr(kernel, 'reset'):
            kernel.reset()
        
        del self._kernels[lru_thread]
        del self._locks[lru_thread]
        del self._last_access[lru_thread]
        
        self._stats["total_released"] += 1
        print(f"[KernelManager] 触发LRU清理，释放 {lru_thread} 的内核")
    
    def cleanup_inactive_kernels(self):
        """
        定期清理不活跃的kernel（超过inactivity_timeout）
        """
        current_time = time.time()
        inactive_threads = []
        
        with self._manager_lock:
            for thread_id, last_access_time in self._last_access.items():
                if current_time - last_access_time > self._inactivity_timeout:
                    inactive_threads.append(thread_id)
            
            for thread_id in inactive_threads:
                kernel = self._kernels[thread_id]
                if hasattr(kernel, 'reset'):
                    kernel.reset()
                
                del self._kernels[thread_id]
                del self._locks[thread_id]
                del self._last_access[thread_id]
                
                self._stats["total_released"] += 1
                self._stats["timeout_releases"] += 1
        
        if inactive_threads:
            print(f"[KernelManager] 清理了 {len(inactive_threads)} 个不活跃内核")
    
    def check_memory_usage(self):
        """
        检查每个kernel的内存占用，如果超过阈值发警告
        """
        import pandas as pd
        
        for thread_id, kernel in self._kernels.items():
            total_size_mb = 0
            large_vars = []
            
            for var_name, var_value in kernel.globals.items():
                if isinstance(var_value, pd.DataFrame):
                    size_mb = var_value.memory_usage(deep=True).sum() / 1024 / 1024
                    total_size_mb += size_mb
                    
                    if size_mb > 100:  # 超过100MB
                        large_vars.append((var_name, size_mb))
            
            self._memory_usage[thread_id] = int(total_size_mb)
            
            # 检查是否超过阈值
            if total_size_mb > self._memory_limit_mb:
                print(f"[警告] {thread_id} 内存占用 {total_size_mb:.1f}MB > {self._memory_limit_mb}MB")
                print(f"       大变量: {large_vars}")
                self._stats["oom_events"] += 1
                
                # 可选：触发强制清理
                if total_size_mb > self._memory_limit_mb * 2:  # 超过2倍阈值
                    print(f"[紧急] 强制释放 {thread_id} 的内核")
                    self._release_kernel(thread_id)
    
    def _release_kernel(self, thread_id: str):
        """内部释放方法"""
        with self._manager_lock:
            if thread_id in self._kernels:
                kernel = self._kernels[thread_id]
                if hasattr(kernel, 'reset'):
                    kernel.reset()
                
                del self._kernels[thread_id]
                del self._locks[thread_id]
                if thread_id in self._last_access:
                    del self._last_access[thread_id]
                
                self._stats["total_released"] += 1
    
    def get_stats(self) -> Dict:
        """获取管理器统计信息"""
        with self._manager_lock:
            return {
                "active_kernels": len(self._kernels),
                "total_created": self._stats["total_created"],
                "total_released": self._stats["total_released"],
                "oom_events": self._stats["oom_events"],
                "timeout_releases": self._stats["timeout_releases"],
                "memory_usage_mb": {
                    tid: self._memory_usage.get(tid, 0)
                    for tid in self._kernels.keys()
                }
            }


# ============================================================================
# 面试讲解用的对比表格（写在你的面试稿里）
# ============================================================================

"""
【当前代码 vs 改进方案】

┌──────────────┬─────────────────────┬──────────────────────────┐
│   特性       │   当前KernelManager │  改进的KernelManager      │
├──────────────┼─────────────────────┼──────────────────────────┤
│ 最多kernel数 │ 无限制 → OOM风险    │ 最多100个（可配置）      │
│              │                     │                          │
│ 不活跃清理   │ ❌ 无              │ ✓ 30分钟自动释放         │
│              │                     │                          │
│ 内存监控     │ ❌ 无              │ ✓ 单个kernel 500MB限制   │
│              │                     │                          │
│ 溢出时处理   │ 直接OOM崩溃         │ 触发LRU清理或警告        │
│              │                     │                          │
│ 统计信息     │ 只有get_stats()    │ 完整的运维指标           │
│              │                     │                          │
│ 并发粒度     │ 全局锁             │ 每kernel一个Lock         │
└──────────────┴─────────────────────┴──────────────────────────┘
"""
