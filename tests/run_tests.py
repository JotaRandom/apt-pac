import unittest
import sys
import os
import time

def run_tests():
    # Ensure src is in python path
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    src_path = os.path.join(project_root, 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Setup logging directory
    log_dir = os.path.join(project_root, 'test_logs')
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    log_file = os.path.join(log_dir, f"test_run_{timestamp}.log")

    # Discover and run tests
    loader = unittest.TestLoader()
    start_dir = os.path.dirname(__file__)
    suite = loader.discover(start_dir, pattern='test_*.py')

    print(f"Running tests... logging to {log_file}")
    
    with open(log_file, "w") as f:
        runner = unittest.TextTestRunner(stream=f, verbosity=2)
        result = runner.run(suite)
        
        # Also print brief summary to console
        print(f"Ran {result.testsRun} tests")
        if not result.wasSuccessful():
            print("FAILED")
            print(f"Errors: {len(result.errors)}, Failures: {len(result.failures)}")
            print(f"See {log_file} for details.")
            sys.exit(1)
        else:
            print("OK")
            sys.exit(0)

if __name__ == '__main__':
    run_tests()
