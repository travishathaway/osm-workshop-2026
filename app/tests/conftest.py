def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require live services",
    )
