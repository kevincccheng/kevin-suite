import sys, time
sys.path.insert(0, '.')

print('Testing _fetch_flow_data() timing...')
start = time.time()

from tab_flow_monitor import _fetch_flow_data
result = _fetch_flow_data()
elapsed = time.time() - start

print(f'Total fetch time: {elapsed:.1f}s')
print(f'Keys returned: {list(result.keys())}')

for key, val in result.items():
    if isinstance(val, dict):
        status = 'ERROR' if val.get('error', False) else 'OK'
        print(f'  {key}: {status}')
    elif isinstance(val, str):
        print(f'  {key}: {val}')
