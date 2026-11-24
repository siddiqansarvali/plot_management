from pathlib import Path

from app.config import Settings


def test_relative_storage_paths_resolve_from_backend_directory(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, upload_dir=Path("uploads"), output_dir=Path("outputs"))
    monkeypatch.chdir(tmp_path)
    backend_root = Path(__file__).resolve().parents[1]

    assert settings.resolved_upload_dir == backend_root / "uploads"
    assert settings.resolved_output_dir == backend_root / "outputs"


def test_absolute_storage_paths_are_preserved(tmp_path):
    settings = Settings(_env_file=None, upload_dir=tmp_path / "my-uploads", output_dir=tmp_path / "my-outputs")

    assert settings.resolved_upload_dir == tmp_path / "my-uploads"
    assert settings.resolved_output_dir == tmp_path / "my-outputs"


def test_yolo_environment_uses_documented_names(monkeypatch):
    monkeypatch.setenv("YOLO_ENABLED", "true")
    monkeypatch.setenv("YOLO_MODEL_PATH", "survey.pt")
    monkeypatch.setenv("YOLO_ALLOWED_CLASSES", "plot,road")

    settings = Settings(_env_file=None)

    assert settings.enable_yolo is True
    assert settings.yolo_model == "survey.pt"
    assert settings.yolo_allowed_classes == "plot,road"
