import os

# Tests describe the committed configuration: a local sim/config.local.toml must not change them.
os.environ['SIM_CONFIG_OVERLAY'] = 'none'
