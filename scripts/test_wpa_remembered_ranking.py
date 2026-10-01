"""Contract checks for Nintendo 3DS remembered-network selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/patch_wpa_remembered_ranking.py"


def choose(results, profiles, explicit=None):
    """Reference model: explicit choice, then protected class, then signal."""
    if explicit is not None:
        matches = [r for r in results if r[0] == explicit]
        if matches:
            return max(matches, key=lambda item: item[1])
    for protected in (True, False):
        matches = [
            result
            for result in results
            if result[0] in profiles and profiles[result[0]] == protected
        ]
        if matches:
            return max(matches, key=lambda item: item[1])
    return None


def main() -> None:
    text = PATCHER.read_text()
    for marker in (
        "N3DS_REMEMBERED_NETWORK_RANKING",
        "n3ds_saved_network_is_protected",
        "#ifdef CONFIG_WEP",
        "return 0;",
        "protected_pass = 1",
        "wpa_s->conf->ssid",
        "wpa_scan_res_match",
        "if (next_ssid)",
        "n3ds_select_remembered_bss",
    ):
        assert marker in text, marker

    profiles = {"secure-weak": True, "secure-strong": True, "open": False}
    results = [("open", -25), ("secure-weak", -70), ("secure-strong", -40)]
    assert choose(results, profiles) == ("secure-strong", -40)
    assert choose(results, profiles, explicit="secure-weak") == (
        "secure-weak",
        -70,
    )
    assert choose([("open", -60), ("open", -35)], {"open": False}) == (
        "open",
        -35,
    )
    print("wpa_remembered_ranking: PASS")


if __name__ == "__main__":
    main()
