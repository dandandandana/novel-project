from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_rag.model_config import (
    ModelConfigError,
    ModelConfigStore,
    ModelProfile,
    default_config_path,
    model_from_config,
)


def test_default_path_is_outside_project_rag_and_outputs() -> None:
    path = default_config_path()
    assert path.name == "model-api.json"
    assert "outputs" not in {part.lower() for part in path.parts}
    assert "novel-rag" not in {part.lower() for part in path.parts[-2:]}


def test_profile_crud_and_active_selection(tmp_path: Path) -> None:
    store = ModelConfigStore(tmp_path / "model-api.json")
    assert store.load()["profiles"] == {}
    saved = store.set_profile(
        "local",
        base_url="http://localhost:1234/v1",
        model="qwen",
        mode="chat",
        api_key="secret",
        timeout="20",
        retries="1",
        max_output_tokens="512",
        no_auth="false",
        future_option={"kept": True},
    )
    assert saved.model == "qwen"
    assert store.list() == ["local"]
    assert store.get() is None  # active is unset until explicitly selected
    assert store.get("local").api_key == "secret"  # type: ignore[union-attr]
    assert store.set_active("local") == "local"
    assert store.get().name == "local"  # type: ignore[union-attr]
    assert store.delete("local") is True
    assert store.list_profiles() == []
    assert store.load()["active"] is None


def test_unknown_fields_round_trip_and_key_is_redacted(tmp_path: Path) -> None:
    path = tmp_path / "model-api.json"
    store = ModelConfigStore(path)
    store.save(
        {
            "schema_version": 88,
            "future_envelope": "kept",
            "active": "local",
            "profiles": {
                "local": {
                    "base_url": "http://localhost:1234/v1",
                    "model": "qwen",
                    "api_key": "very-secret",
                    "future_field": [1, 2],
                }
            },
        }
    )
    profile = store.get("local")
    assert profile is not None
    assert "very-secret" not in repr(profile)
    assert profile.to_dict()["api_key"] == "***"
    store.set_profile("local", future_field=[3, 4])
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["schema_version"] == 88
    assert value["future_envelope"] == "kept"
    assert value["profiles"]["local"]["future_field"] == [3, 4]
    assert value["profiles"]["local"]["api_key"] == "very-secret"


def test_corrupt_file_error_does_not_echo_contents(tmp_path: Path) -> None:
    path = tmp_path / "model-api.json"
    path.write_text('{"api_key":"very-secret",', encoding="utf-8")
    with pytest.raises(ModelConfigError) as error:
        ModelConfigStore(path).load()
    assert "very-secret" not in str(error.value)
    assert "model-api.json" in str(error.value)


def test_build_model_uses_no_auth_and_exposes_adapter_kwargs(tmp_path: Path) -> None:
    store = ModelConfigStore(tmp_path / "model-api.json")
    store.set_profile(
        "local", base_url="http://localhost:1234/v1", model="qwen", api_key="secret", no_auth=True
    )
    model = store.build_model("local")
    assert model.api_key is None
    assert model.base_url == "http://localhost:1234/v1"
    assert model.model == "qwen"
    # Module-level construction is available to TUI/CLI callers too.
    assert model_from_config("local", path=store.path).model == "qwen"


def test_invalid_known_field_is_friendly_and_key_free(tmp_path: Path) -> None:
    path = tmp_path / "model-api.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    "local": {
                        "base_url": "http://localhost",
                        "model": "qwen",
                        "api_key": "secret",
                        "retries": -1,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelConfigError) as error:
        ModelConfigStore(path).get("local")
    assert "secret" not in str(error.value)


def test_profile_model_kwargs_and_public_mapping() -> None:
    profile = ModelProfile.from_mapping(
        "x", {"base_url": "http://localhost", "model": "m", "api_key": "k", "no_auth": False}
    )
    assert profile.model_kwargs()["api_key"] == "k"
    assert profile.to_dict()["api_key"] == "***"
