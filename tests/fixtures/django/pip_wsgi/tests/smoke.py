# Fixture material, never collected: the name matches neither test_*.py nor
# *_test.py (pytest's default python_files), so `testpaths = ["tests"]` skips it.
# It exists so core.tests-exist sees a tests/ directory in the fleet-norm fixture.
def smoke():
    return True
