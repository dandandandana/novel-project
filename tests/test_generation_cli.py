from novel_rag.cli import _model_from_args, build_parser
from novel_rag.model_config import ModelConfigStore


def test_generate_command_is_registered() -> None:
    args = build_parser().parse_args([
        "generate", "--story", "demo", "--outline", "写一章", "--model-command", "fake-model"
    ])
    assert args.command == "generate"
    assert args.timeline == "main"
    assert args.task_id == "generation"
    assert args.model_timeout == 300


def test_generate_command_accepts_length_policy() -> None:
    args = build_parser().parse_args([
        "generate", "--story", "demo", "--outline", "写一章", "--model-command", "fake-model",
        "--length-target", "8000", "--expand-at", "争吵段",
    ])
    assert args.length_target == 8000
    assert args.expand_at == ["争吵段"]


def test_generate_command_accepts_openai_compatible_api() -> None:
    args = build_parser().parse_args([
        "generate", "--story", "demo", "--outline", "写一章",
        "--api-model", "writer", "--api-base", "http://localhost:1234/v1",
        "--api-mode", "chat", "--api-no-auth",
    ])
    assert args.model_command is None
    assert args.api_model == "writer"
    assert args.api_mode == "chat"
    assert args.api_no_auth is True


def test_init_preferences_command_is_registered() -> None:
    args = build_parser().parse_args(["init-preferences", "--story", "demo"])
    assert args.command == "init-preferences"


def test_confirm_command_requires_coordinates_and_explicit_yes() -> None:
    args = build_parser().parse_args([
        "confirm", "--runtime", "outputs/.workflow/demo/task", "--yes",
        "--volume", "1", "--chapter", "2",
    ])
    assert args.command == "confirm"
    assert args.yes is True
    assert args.scene == 1


def test_tui_command_is_registered() -> None:
    args = build_parser().parse_args(["tui"])
    assert args.command == "tui"


def test_continue_and_state_review_commands_are_registered() -> None:
    parser = build_parser()
    continued = parser.parse_args([
        "continue", "--runtime", "outputs/.workflow/demo/task", "--guidance", "补足动机",
        "--model-command", "fake-model",
    ])
    assert continued.command == "continue"
    assert continued.task_id is None

    review = parser.parse_args(["state-review", "--runtime", "outputs/.workflow/demo/task"])
    approve = parser.parse_args([
        "state-approve", "--runtime", "outputs/.workflow/demo/task", "--yes", "--character", "hero",
    ])
    assert review.command == "state-review"
    assert approve.character == ["hero"]


def test_versioned_import_and_feedback_commands_are_registered() -> None:
    parser = build_parser()
    upload = parser.parse_args([
        "import-rag", "--source", "canon.yaml", "--story", "demo",
        "--version", "1.1", "--supersedes", "canon-demo-v1.0", "--yes",
    ])
    feedback = parser.parse_args([
        "feedback-create", "--story", "demo", "--target-type", "runtime",
        "--target-id", "task-1", "--issue", "对白太快", "--rule", "补足反应", "--yes",
    ])
    assert upload.supersedes == ["canon-demo-v1.0"]
    assert feedback.rule == ["补足反应"]
    assert feedback.yes is True


def test_generate_can_use_local_profile_without_model_flags() -> None:
    args = build_parser().parse_args(["generate", "--story", "demo", "--outline", "写一章"])
    assert args.model_command is None
    assert args.api_model is None


def test_api_config_command_saves_active_profile(tmp_path) -> None:
    config = tmp_path / "model-api.json"
    args = build_parser().parse_args([
        "--model-config", str(config), "api-config", "set", "--name", "local",
        "--base-url", "http://localhost:8000/v1", "--model", "writer",
        "--mode", "chat", "--no-auth", "--active",
    ])
    assert args.func(args) == 0
    profile = ModelConfigStore(config).get()
    assert profile is not None
    assert profile.name == "local"
    assert profile.api_key is None


def test_cli_builds_model_from_active_local_profile_without_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = tmp_path / "model-api.json"
    store = ModelConfigStore(config)
    store.set_profile("local", {"base_url": "http://localhost:8000/v1", "model": "writer",
                                "mode": "chat", "no_auth": True})
    store.set_active("local")
    args = build_parser().parse_args([
        "--model-config", str(config), "generate", "--story", "demo", "--outline", "写一章",
    ])
    model = _model_from_args(args)
    assert model.model == "writer"
    assert model.api_key is None
