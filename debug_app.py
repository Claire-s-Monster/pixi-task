import sys
sys.path.insert(0, 'src')
from pixi_task.server import app

print('App type:', type(app))
print('App attributes:', [attr for attr in dir(app) if not attr.startswith('_')])
print('Has tools?', hasattr(app, 'tools'))
print('Has resources?', hasattr(app, 'resources'))

# Try different attribute names
for attr_name in ['_tools', '_resources', 'tool_registry', 'resource_registry']:
    if hasattr(app, attr_name):
        attr_val = getattr(app, attr_name)
        print(f'Has {attr_name}: {type(attr_val)} with {len(attr_val) if hasattr(attr_val, "__len__") else "unknown"} items')