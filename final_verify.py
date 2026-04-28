import sys
sys.path.insert(0, r'd:\HuaweiMoveData\Users\HUAWEI\Desktop\简历\ASA')

print("1. Testing memory_system...")
from memory_system import memory_system
print("   OK - memory initialized")

print("2. Testing orchestrator...")
from orchestrator import orchestrator  
print("   OK - orchestrator initialized")

print("3. Testing multi_agent...")
import multi_agent
print(f"   MEMORY_ENABLED = {multi_agent.MEMORY_ENABLED}")
print(f"   ORCHESTRATOR_ENABLED = {multi_agent.ORCHESTRATOR_ENABLED}")

print("\n=== ALL TESTS PASSED ===")
