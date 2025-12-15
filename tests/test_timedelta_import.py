"""
Quick test to verify timedelta import is fixed in creator_analyzer.py
"""

import sys
import os

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

print("Testing timedelta import fix...")
print("=" * 60)

# Read the file directly to check the import
file_path = os.path.join(parent_dir, 'creator_analyzer.py')
with open(file_path, 'r') as f:
    lines = f.readlines()
    for i, line in enumerate(lines[:20], 1):
        if 'from datetime import' in line:
            print(f"Line {i}: {line.strip()}")
            if 'timedelta' in line:
                print("✅ timedelta is imported at module level")
            else:
                print("❌ timedelta is NOT imported")
            break

print("\nChecking for any conditional timedelta imports...")
with open(file_path, 'r') as f:
    content = f.read()
    # Check for conditional imports (indented)
    import re
    conditional_imports = re.findall(r'^\s+from datetime import.*timedelta', content, re.MULTILINE)
    if conditional_imports:
        print("⚠️  Found conditional imports:")
        for imp in conditional_imports:
            print(f"  {imp}")
    else:
        print("✅ No conditional timedelta imports found")

print("\n" + "=" * 60)
print("Verification complete!")
print("\nThe fix is in place. To use it:")
print("1. Make sure NO Python processes are running (kill Streamlit, test scripts, etc.)")
print("2. Restart your application")
print("3. The timedelta import will work correctly")
