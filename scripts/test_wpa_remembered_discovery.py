"""Regression checks for Nintendo 3DS remembered-first Wi-Fi discovery."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/patch_wpa_remembered_discovery.py"


def directed_order(profiles, explicit=None, capacity=5):
    """Reference model: explicit, protected remembered, then open remembered."""
    ordered = []
    if explicit is not None and explicit in profiles and profiles[explicit][1]:
        ordered.append(explicit)
    for protected in (True, False):
        for ssid, (is_protected, enabled) in profiles.items():
            if (
                enabled
                and is_protected == protected
                and ssid not in ordered
                and len(ordered) < capacity
            ):
                ordered.append(ssid)
    return ordered


def main() -> None:
    text = PATCHER.read_text()
    for marker in (
        "N3DS_REMEMBERED_FIRST_DISCOVERY",
        "n3ds_add_remembered_scan_ssids",
        "wpa_s->next_ssid",
        "protected_pass = 1",
        "remembered-first directed scan",
        "before wildcard discovery",
        "0004-n3ds-remembered-first-discovery.patch",
    ):
        assert marker in text, marker

    profiles = {
        "open-strong": (False, True),
        "secure-weak": (True, True),
        "secure-strong": (True, True),
        "disabled": (True, False),
    }
    assert directed_order(profiles) == [
        "secure-weak",
        "secure-strong",
        "open-strong",
    ]
    assert directed_order(profiles, explicit="open-strong") == [
        "open-strong",
        "secure-weak",
        "secure-strong",
    ]
    assert len(directed_order({str(i): (True, True) for i in range(9)})) == 5
    print("wpa_remembered_discovery: PASS")


if __name__ == "__main__":
    main()
