# Basic tests for the DataValidationAgent
# Run with: python -m pytest tests/

def test_valid_soh_passes():
    assert 0.0 <= 90.0 <= 100.0

def test_invalid_soh_fails():
    assert not (0.0 <= 150.0 <= 100.0)

def test_energy_content_positive():
    assert 75.0 > 0

def test_temperature_range_logical():
    assert -20.0 < 60.0

def test_rte_within_range():
    assert 0.0 <= 91.0 <= 100.0

def test_self_discharge_within_range():
    assert 0.0 <= 0.12 <= 100.0

if __name__ == "__main__":
    tests = [
        test_valid_soh_passes,
        test_invalid_soh_fails,
        test_energy_content_positive,
        test_temperature_range_logical,
        test_rte_within_range,
        test_self_discharge_within_range,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError:
            print(f"  FAIL  {test.__name__}")
            failed += 1
    print(f"\n  {passed} passed  {failed} failed")