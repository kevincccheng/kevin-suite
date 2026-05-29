import sys, time
sys.path.insert(0, '.')
from flow_core.hk_flows import get_hkma_balance

start = time.time()
result = get_hkma_balance()
elapsed = time.time() - start
print(f'HKMA fetch: {elapsed:.1f}s')
print(f'Result: {result}')
