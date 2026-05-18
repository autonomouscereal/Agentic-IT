import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_reference_skills.py"


def load_sync_module():
    scripts_dir = str(SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("sync_reference_skills", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_copy_preserves_excluded_local_state(tmp_path):
    sync = load_sync_module()
    config = {
        "exclude_names": [".cred_key", ".cred_vault.json"],
        "exclude_suffixes": [],
        "exclude_exact_files": ["servers.json"],
    }

    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "SKILL.md").write_text("# Test Skill\n", encoding="utf-8")
    (src / "tool.py").write_text("print('ok')\n", encoding="utf-8")

    (dest / ".cred_key").write_text("local-key", encoding="utf-8")
    (dest / ".cred_vault.json").write_text('{"demo": "ciphertext"}', encoding="utf-8")
    (dest / "servers.json").write_text('{"default_server": "ai"}', encoding="utf-8")
    (dest / "stale.txt").write_text("remove me", encoding="utf-8")

    copied, skipped = sync.copy_skill(src, dest, config, preserve_existing_excluded=True)

    assert copied == 2
    assert skipped == 0
    assert (dest / "SKILL.md").exists()
    assert (dest / "tool.py").exists()
    assert (dest / ".cred_key").read_text(encoding="utf-8") == "local-key"
    assert (dest / ".cred_vault.json").read_text(encoding="utf-8") == '{"demo": "ciphertext"}'
    assert (dest / "servers.json").read_text(encoding="utf-8") == '{"default_server": "ai"}'
    assert not (dest / "stale.txt").exists()


def test_stage_copy_drops_excluded_local_state_by_default(tmp_path):
    sync = load_sync_module()
    config = {
        "exclude_names": [".cred_key", ".cred_vault.json"],
        "exclude_suffixes": [],
        "exclude_exact_files": ["servers.json"],
    }

    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "SKILL.md").write_text("# Test Skill\n", encoding="utf-8")
    (dest / ".cred_key").write_text("local-key", encoding="utf-8")
    (dest / ".cred_vault.json").write_text('{"demo": "ciphertext"}', encoding="utf-8")
    (dest / "servers.json").write_text('{"default_server": "ai"}', encoding="utf-8")

    sync.copy_skill(src, dest, config)

    assert (dest / "SKILL.md").exists()
    assert not (dest / ".cred_key").exists()
    assert not (dest / ".cred_vault.json").exists()
    assert not (dest / "servers.json").exists()
