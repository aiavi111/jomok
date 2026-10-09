"""Ключи и названия моделей живут только в .env: проверяем код, шаблоны и документацию."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "venv", "data", "demo_output", "__pycache__", ".pytest_cache", ".git", "node_modules"}
SECRET_KEYS = ["TELEGRAM_BOT_TOKEN", "WEBAPP_URL", "ADMIN_CHAT_ID", "OPENAI_API_KEY", "GEMINI_API_KEY",
               "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"]


def project_files(*patterns):
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
                yield path


def env_values(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, rest = line.partition("=")
            values[key.strip()] = rest.split("#", 1)[0].strip()
    return values


def test_env_example_has_every_variable_with_empty_secrets():
    values = env_values(ROOT / ".env.example")
    for key in ["TELEGRAM_BOT_TOKEN", "WEBAPP_URL", "ADMIN_CHAT_ID", "TEXT_PROVIDER", "IMAGE_PROVIDER", "OPENAI_API_KEY",
                "OPENAI_BASE_URL", "OPENAI_TEXT_MODEL", "OPENAI_IMAGE_MODEL", "OPENAI_IMAGE_QUALITY", "GEMINI_API_KEY",
                "GEMINI_MODEL", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "DEV_MODE", "MAX_BOOKS_PER_USER_PER_DAY",
                "KEEP_FILES_DAYS", "TEXT_OVERLAY_MODE"]:
        assert key in values, f"{key} нет в .env.example"
    for key in SECRET_KEYS:
        assert values[key] == "", f"в .env.example у {key} должно быть пусто"
    assert values["TEXT_PROVIDER"] == "mock" and values["IMAGE_PROVIDER"] == "mock" and values["DEV_MODE"] == "0"
    assert values["TEXT_OVERLAY_MODE"] == "auto"


def test_env_file_is_ignored_by_git():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in lines and "data/" in lines


def test_real_secrets_from_dotenv_appear_nowhere_else_in_the_project():
    env = ROOT / ".env"
    if not env.exists():
        return
    secrets = [v for k, v in env_values(env).items()
               if v and len(v) >= 12 and any(w in k for w in ("TOKEN", "KEY", "ACCOUNT"))]
    for path in project_files("**/*"):
        if path.name == ".env" or path.suffix in {".ttf", ".jpg", ".png", ".pdf", ".sqlite3", ".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for secret in secrets:
            assert secret not in text, f"секрет найден в {path.relative_to(ROOT)}"


def test_no_hardcoded_secret_looking_strings_in_code_or_docs():
    pattern = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}")
    for path in project_files("*.py", "app/**/*.py", "webapp/*", "*.md", "*.sh", "*.bat", ".env.example"):
        if path.name in {"test_providers.py", "test_misc.py", "test_check_keys.py", "conftest.py", "test_auth.py"}:
            continue
        assert not pattern.search(path.read_text(encoding="utf-8")), f"похоже на ключ: {path.relative_to(ROOT)}"


def test_model_names_are_not_hardcoded_in_application_code():
    pattern = re.compile(r"gpt-\d|gpt-image|gemini-\d|flux-1|@cf/")
    for path in project_files("app/**/*.py", "app/*.py", "demo.py", "check_keys.py", "webapp/*"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            assert not pattern.search(line), f"название модели в коде: {path.relative_to(ROOT)}:{number}"
