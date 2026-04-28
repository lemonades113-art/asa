# ASA (AI Stock Analyst) - Multi-Agent Financial Data Analysis System

## Project Overview

ASA is a LangGraph-based multi-agent collaboration system designed to solve "long-chain reasoning" and "data vacuum" problems in financial quantitative analysis. The system coordinates multiple Agent nodes through a Supervisor pattern, implementing a complete closed loop from task planning, code generation, logical auditing to fault self-healing.

**Core Code Scale**: 7800+ lines
- `multi_agent.py`: 3268 lines - Supervisor orchestration framework
- `lib.py`: 1598 lines - Model factory, execution kernel, utility functions
- `memory_system.py`: 1201 lines - Hierarchical memory system
- `orchestrator.py`: 1656 lines - Agent coordination layer
- `rca_module.py`: 551 lines - Root cause analysis module
- `trajectory_collector.py`: 433 lines - Trajectory collector

---

## System Architecture

### Core Agent Nodes

```
User Input
    ↓
Supervisor (Task Planning & Routing)
    ↓
Coder (Code Generation & Execution) ←→ Tools (Tool Invocation)
    ↓
Reviewer (Logical Auditing)
    ↓
ErrorHandler (Error Recovery) ←→ ProfileUpdater (Profile Update)
    ↓
FINISH
```

### Key Design Patterns

1. **Supervisor Pattern**: Central controller responsible for task decomposition and node scheduling
2. **Physical Task Queue**: Enforces execution order via `remaining_steps.pop(0)`
3. **Model Tiering**: qwen-plus (strong logic) vs qwen-turbo (lightweight)
4. **Skill-on-demand**: Dynamic skill injection mechanism
5. **Thread Isolation**: KernelManager achieves session-level namespace isolation

---

## Core Mechanisms

### 1. Deterministic Flow Control

**Physical Task Queue** (`multi_agent.py` lines 728, 762, 804):

```python
# Only pop on successful execution
finished_step = remaining_steps.pop(0)
```

**Problem Solved**:
- LLMs are prone to "false completion" hallucinations in long-chain tasks
- `pop(0)` enforces physical control: as long as the list is not empty, execution must continue

### 2. Dynamic Skill Injection (Skill-on-demand)

**Skill Library** (`skills.json`):

| Skill Name | Trigger Keywords | Core Function |
|------------|-----------------|---------------|
| dividend_expert | dividend, dividend yield | dv_ttm unit conversion, status filtering |
| charting_expert | plot, visualize | Chinese font, path generation |
| finance_audit | financial report, revenue | unit conversion, time lag check |
| market_expert | HK stock, ETF | code suffix, valuation switch |
| error_handling | error, retry | retry strategy, graceful degradation |

**Workflow**:
1. Supervisor identifies intent → suggests loading skill
2. Coder calls `load_skill()` tool
3. System reads skills.json, injects rules as ToolMessage
4. Coder generates code after receiving skill

### 3. Model Tiering Factory

**Implementation** (`lib.py` lines 67-108):

```python
def get_chat_model(model_type):
    config = {
        "smart": {"model": "qwen-plus", "temperature": 0.1},   # Supervisor, Coder, Reviewer
        "fast": {"model": "qwen-turbo", "temperature": 0.1}   # ErrorHandler, ProfileUpdater
    }
```

**Effect**: Lightweight nodes use low-cost models, core logic nodes use high-performance models, effectively controlling inference costs.

### 4. Session Isolation (KernelManager)

**Implementation** (`lib.py` lines 481-552):

```python
class KernelManager:
    def get_kernel(self, thread_id: str):
        if thread_id not in self._kernels:
            self._kernels[thread_id] = StatefulPythonKernel()
        return self._kernels[thread_id]
```

**Features**:
- Each thread_id has an independent Python execution environment
- Physical variable isolation between multi-tenants
- Multi-turn conversations from the same user can接力 use variables

### 5. 4-Level Backtracking Strategy (BacktrackingRouter)

**Implementation** (`multi_agent.py` lines 105-160):

| Level | Strategy | Trigger Condition |
|-------|----------|-------------------|
| L1 | direct_query | First attempt |
| L2 | step_by_step | Empty data |
| L3 | alternative_fields | Primary field failure |
| L4 | reject_with_reason | All strategies exhausted |

### 6. Self-Correction Reflection Mechanism

**Implementation** (`multi_agent.py` lines 646-681):

```python
if execution_status == "error" and retry_count >= 2:
    # Trigger reflection loop
    reflection_prompt = f"""
    User Intent: {last_msg_content}
    Error Type: {error_type}
    Retry Count: {retry_count}
    
    Please reflect:
    1. Was intent understanding biased?
    2. Was skill selection appropriate?
    3. Were API parameters correct?
    4. Are there alternative approaches?
    """
```

---

## Extension Modules

### 1. Hierarchical Memory System (memory_system.py)

```
┌─────────────────┐  ┌─────────────────┐
│  Short-Term     │  │  Long-Term      │
│  (Working)      │  │  (Long-Term)    │
│                 │  │                 │
│ - Last 5 rounds │  │ - Success       │
│ - TTL: 30min    │  │   strategies    │
│                 │  │ - Knowledge     │
│                 │  │   fragments     │
└─────────────────┘  └─────────────────┘
         ↓                    ↓
┌─────────────────────────────────────┐
│      Memory Decay Mechanism          │
│ - Time: 30 days no access → -50%    │
│   weight                              │
│ - Importance: success_count>3 →     │
│   permanent retention                 │
│ - Relevance: embedding<0.5 → no     │
│   recall                              │
└─────────────────────────────────────┘
```

### 2. Agent Coordination Layer (orchestrator.py)

**Features**:
- Inter-agent conflict arbitration (voting, priority, consensus)
- 4-level Fallback strategy (retry → switch → human → reject)
- Human-in-the-Loop (triggers human confirmation at low confidence)
- ToolUsageGraph (intelligent tool routing)

### 3. Root Cause Analysis (rca_module.py)

**Features**:
- Fault Propagation Graph: Traces error propagation path across Agents
- Root Cause Localization: Identifies the true error source
- Propagation-Aware Retry: Selects retry strategy based on propagation chain

### 4. Trajectory Collection (trajectory_collector.py)

**Features**:
- Automatically collects Agent execution trajectories
- Generates DPO-format preference data
- Error-Specific classification (12 error types)

---

## Testing & Validation

### Stress Test Results

| Test Batch | Samples | Success Rate | Key Observations |
|------------|---------|--------------|------------------|
| batch_run_20260130_173002 | 45 | **80.0%** | finance_audit skill, completed in 28 steps |
| batch_run_20260130_155446 | 27 | **66.7%** | charting_expert skill, API authorization issues |
| **Total** | **72** | **73%** | Skill loading 100% successful |

### Real Case Demonstration

**Input**: `"Query the proportion of iFlytek's government subsidies to net profit and analyze its earnings quality."`

**Execution Flow**:
1. Supervisor identifies intent → suggests loading finance_audit
2. Coder calls load_skill("finance_audit") → ✅ Skill loaded successfully
3. Coder generates Tushare query code
4. Tools execute code → returns raw data
5. Coder processes data → unit conversion, field extraction
6. ... (28 steps total)
7. Reviewer logical audit → ⚠️ Detects data anomalies
8. Reviewer generates report → detailed risk analysis
9. ProfileUpdater updates profile

**Output**: Successfully completed. Reviewer correctly identified data issues such as "2025 net profit cannot exist before February 2025".

---

## Project Status

**Current Phase**: Functional prototype成型, production-grade reliability optimization in progress

**Verified**:
- ✅ Supervisor pattern orchestration
- ✅ Physical task queue control
- ✅ Dynamic skill injection
- ✅ Model tiered scheduling
- ✅ KernelManager session isolation
- ✅ 72-round stress test validation (73% success rate)

**In Progress**:
- 🔄 Execution sequence audit mechanism (prevent recursive dead loops)
- 🔄 OpenSandbox kernel integration
- 🔄 Deep memory system integration

---

## Tech Stack

- **Orchestration Framework**: LangGraph
- **LLM**: Alibaba Cloud Tongyi Qwen (qwen-plus / qwen-turbo)
- **Data Source**: Tushare Pro API
- **Data Processing**: Pandas, NumPy
- **Vector Storage**: ChromaDB (optional)
- **Execution Isolation**: StatefulPythonKernel / OpenSandbox (reserved)

---

## File Structure

```
ASA/
├── multi_agent.py          # Core orchestration framework (3268 lines)
├── lib.py                  # Model factory, execution kernel (1598 lines)
├── memory_system.py        # Hierarchical memory system (1201 lines)
├── orchestrator.py         # Agent coordination layer (1656 lines)
├── rca_module.py           # Root cause analysis (551 lines)
├── trajectory_collector.py # Trajectory collection (433 lines)
├── skills.json             # 5-type skill library
├── conf.py                 # Configuration management
├── batch_test_runner.py    # Stress test framework
└── evaluation_results/     # Test results
    ├── batch_run_20260130_173002.jsonl  # 45-round test
    └── batch_run_20260130_155446.jsonl  # 27-round test
```

---

## Core Code References

| Mechanism | File | Lines |
|-----------|------|-------|
| remaining_steps.pop(0) | multi_agent.py | 728, 762, 804 |
| Model tiering factory | lib.py | 67-108 |
| KernelManager | lib.py | 481-552 |
| BacktrackingRouter | multi_agent.py | 105-160 |
| Self-Correction | multi_agent.py | 646-681 |
| MultiAgentState | multi_agent.py | 317-336 |

---

**Project Author**: way  
**Created**: 2025-11-06  
**Last Updated**: 2026-01-30
