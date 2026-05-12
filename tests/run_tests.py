import pytest
import sys
import os
from datetime import datetime

def main():
    """Run tests with pytest and coverage."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    src_path = os.path.join(project_root, 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Ensure test logs directory
    log_dir = os.path.join(project_root, 'test_logs')
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = os.path.join(log_dir, f"test_run_{timestamp}.log")

    print(f"Running tests at {datetime.now().isoformat()}")
    print(f"Logging detailed output to: {log_file}")
    
    args = [
        "tests",
        "-v",
        "--tb=short",
        "--cov=apt_pac",
        "--cov-report=term-missing",
        "--cov-report=html:coverage-report",
        "--durations=10",
        "--cov-fail-under=70",  # Require at least 70% coverage
    ]
    
    retcode = pytest.main(args)
    
    if retcode == 0:
        print("\n✅ All tests passed successfully!")
    else:
        print("\n❌ Some tests failed. Check the output above.")
    
    sys.exit(retcode)

if __name__ == '__main__':
    main()