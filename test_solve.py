#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'opsora_cmd'))

from opsora_v2 import main

# Simulate command line arguments for /solve test
sys.argv = ['opsora', '/solve', 'test']
try:
    main()
except SystemExit:
    pass
except Exception as e:
    print(f"Error: {e}")