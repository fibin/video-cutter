import json
import re
from pathlib import Path

from video_cutter.messages import EN

STATIC = Path(__file__).parent.parent / "video_cutter" / "static"
I18N = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))


def test_languages_have_the_same_keys():
    assert set(I18N["en"]) == set(I18N["uk"])


def test_every_server_message_is_translated():
    assert set(EN) <= set(I18N["en"])


def test_placeholders_match_between_languages():
    for key, text in I18N["en"].items():
        names = set(re.findall(r"\{(\w+)\}", text))
        assert names == set(re.findall(r"\{(\w+)\}", I18N["uk"][key])), key


def test_every_key_used_by_the_page_exists():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-html|-title|-placeholder)?="(\w+)"', html))
    used |= set(re.findall(r'(?:setT\([^,]+, |\[)"([a-z_]+)"', js))
    used |= {f"{base}_{form}" for base in re.findall(r'plural: "(\w+)"', js) for form in ("one", "few", "many")}
    used -= {"dragenter", "dragover", "dragleave", "drop"}  # DOM event names, not message keys
    missing = sorted(k for k in used if k not in I18N["en"])
    assert not missing, missing
