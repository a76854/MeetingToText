"""SETTING_SPECS is the single source of truth for setting keys (todo 15).

Locks the guarantees the three former parallel registries used to provide,
with the legacy tables reconstructed inline as literals:

- (a) superset: every key from startup._USER_SETTING_KEYS / _BOOL_KEYS and the
  settings router _INT_FIELDS / _FLOAT_FIELDS / _DELETABLE_KEYS exists in
  SETTING_SPECS with a caster of the right kind;
- (b) deletable flags encode current reality (Metis F11:
  reconnect_grace_seconds is user-settable but NOT deletable);
- (c) sensitive flags mark secrets (llm_api_key).
"""

import pytest

pytestmark = pytest.mark.unit

from backend.app.config import SETTING_SPECS, Settings

# Former startup._USER_SETTING_KEYS (key -> caster).
_LEGACY_USER_SETTING_KEYS = {
    "llm_base_url": str,
    "llm_api_key": str,
    "llm_model": str,
    "llm_temperature": float,
    "llm_max_tokens": int,
    "asr_model_type": str,
    "asr_model_name": str,
    "ncpu": int,
    "asr_batch_size_s": int,
    "asr_merge_length_s": float,
    "asr_max_single_segment_time": int,
    "streaming_asr_model_name": str,
    "reconnect_grace_seconds": int,
    "audio_source": str,
}

# Former startup._BOOL_KEYS.
_LEGACY_BOOL_KEYS = {"asr_needs_punc", "streaming_asr_enabled", "browser_noise_suppression", "asr_merge_vad"}

# Former settings router _INT_FIELDS / _FLOAT_FIELDS.
_LEGACY_INT_FIELDS = {"llm_max_tokens", "ncpu", "asr_batch_size_s", "asr_max_single_segment_time"}
_LEGACY_FLOAT_FIELDS = {"llm_temperature", "asr_merge_length_s"}

# Former settings router _DELETABLE_KEYS.
_LEGACY_DELETABLE_KEYS = {
    "llm_base_url", "llm_api_key", "llm_model", "llm_temperature", "llm_max_tokens",
    "asr_model_type", "asr_model_name", "asr_needs_punc", "ncpu",
    "asr_batch_size_s", "asr_merge_length_s", "asr_merge_vad", "asr_max_single_segment_time",
    "streaming_asr_enabled", "streaming_asr_model_name",
    "browser_noise_suppression", "audio_source",
}


def test_superset_covers_legacy_user_keys_with_matching_caster():
    for key, caster in _LEGACY_USER_SETTING_KEYS.items():
        assert key in SETTING_SPECS, f"{key} missing from SETTING_SPECS"
        assert SETTING_SPECS[key].caster is caster, f"{key} caster mismatch"


def test_superset_covers_legacy_bool_keys_with_bool_caster():
    for key in _LEGACY_BOOL_KEYS:
        assert key in SETTING_SPECS, f"{key} missing from SETTING_SPECS"
        spec = SETTING_SPECS[key]
        assert spec.caster("true") is True
        assert spec.caster("false") is False
        assert spec.caster("True") is True  # legacy capitalized rows
        assert spec.caster(False) is False
        assert spec.caster(True) is True


def test_superset_covers_router_int_float_fields():
    for key in _LEGACY_INT_FIELDS:
        assert SETTING_SPECS[key].caster is int, f"{key} caster mismatch"
    for key in _LEGACY_FLOAT_FIELDS:
        assert SETTING_SPECS[key].caster is float, f"{key} caster mismatch"


def test_deletable_set_matches_legacy_deletable_keys():
    deletable = {key for key, spec in SETTING_SPECS.items() if spec.deletable}
    assert deletable == _LEGACY_DELETABLE_KEYS


def test_reconnect_grace_seconds_user_settable_but_not_deletable():
    # Metis F11: present in the legacy user-keys table (int caster), absent
    # from _DELETABLE_KEYS — DELETE must keep rejecting it.
    spec = SETTING_SPECS["reconnect_grace_seconds"]
    assert spec.caster is int
    assert spec.deletable is False


def test_sensitive_flag_true_only_for_llm_api_key():
    assert SETTING_SPECS["llm_api_key"].sensitive is True
    assert SETTING_SPECS["llm_base_url"].sensitive is False
    assert SETTING_SPECS["llm_model"].sensitive is False
    others = {key: spec for key, spec in SETTING_SPECS.items() if key != "llm_api_key"}
    assert all(spec.sensitive is False for spec in others.values())


def test_spec_defaults_equal_pydantic_field_defaults():
    # Spec defaults must equal the Settings class field defaults exactly
    # (env-aware snapshot), so DELETE-reset and the pydantic model never drift.
    fresh = Settings()
    for key, spec in SETTING_SPECS.items():
        assert spec.key == key
        assert spec.default == getattr(fresh, key), f"{key} default drifted"
