"""Tests for configuration."""

import os
from unittest.mock import patch

from aion.config import AionSettings, EstixeSettings, FailMode


def test_default_settings():
    with patch.dict(os.environ, {}, clear=False):
        s = AionSettings()
        assert s.port == 8080
        assert s.fail_mode == FailMode.OPEN
        assert s.estixe_enabled is True
        assert s.nomos_enabled is False
        assert s.metis_enabled is False
        assert s.default_provider == "openai"


def test_fail_mode_closed():
    with patch.dict(os.environ, {"AION_FAIL_MODE": "closed"}, clear=False):
        s = AionSettings()
        assert s.fail_mode == FailMode.CLOSED


def test_estixe_settings():
    s = EstixeSettings()
    assert s.bypass_threshold == 0.85
    assert s.embedding_model == "all-MiniLM-L6-v2"
    assert s.max_tokens_per_request == 4096


def test_custom_threshold():
    with patch.dict(os.environ, {"ESTIXE_BYPASS_THRESHOLD": "0.90"}, clear=False):
        s = EstixeSettings()
        assert s.bypass_threshold == 0.90
