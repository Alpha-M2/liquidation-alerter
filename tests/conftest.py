import pytest

import app.services.cache as cache_module


@pytest.fixture(autouse=True)
def reset_position_cache():
    """Reset the singleton PositionCache between tests to prevent cross-test pollution."""
    cache_module._position_cache = None
    cache_module._reserve_cache = None
    yield
    cache_module._position_cache = None
    cache_module._reserve_cache = None
