"""Test script to verify imports work"""
import sys
print(f"Python: {sys.executable}")
print(f"Python version: {sys.version}")
print("\nTrying imports...")

try:
    import reportlab
    print(f"[OK] reportlab {reportlab.__version__}")
except ImportError as e:
    print(f"[FAIL] reportlab: {e}")

try:
    import openpyxl
    print(f"[OK] openpyxl {openpyxl.__version__}")
except ImportError as e:
    print(f"[FAIL] openpyxl: {e}")

try:
    import markdown
    print(f"[OK] markdown {markdown.__version__}")
except ImportError as e:
    print(f"[FAIL] markdown: {e}")

print("\nAll done!")
