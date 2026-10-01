#!/usr/bin/env python3
"""Fit Launcher2's landscape workspace into the physical 320x240 panel."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/launcher2")
LAND_DIMS = ROOT / "res/values-land/dimens.xml"
WORKSPACE = ROOT / "res/layout-land/workspace_screen.xml"
STYLES = ROOT / "res/values/styles.xml"
DEFAULTS = ROOT / "res/xml/default_workspace.xml"
PROVIDER = ROOT / "src/com/android/launcher2/LauncherProvider.java"


def replace(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


dims = LAND_DIMS.read_text()
dims = dims.replace('<dimen name="workspace_cell_width">106dip</dimen>',
                    '<dimen name="workspace_cell_width">66dip</dimen>')
LAND_DIMS.write_text(dims)

workspace = WORKSPACE.read_text()
workspace = workspace.replace('launcher:longAxisEndPadding="55dip"',
                              'launcher:longAxisEndPadding="56dip"')
workspace = workspace.replace('launcher:shortAxisCells="4"',
                              'launcher:shortAxisCells="3"')
workspace = workspace.replace('3*74 <= 240.', '3*74 = 222.')
workspace = workspace.replace(
    '    <!-- N3DS_320X240_NONOVERLAP_GRID: 4*66 + 56 = 320; '
    '3*74 = 222. -->\n', '')
if "N3DS_320X240_NONOVERLAP_GRID" not in workspace:
    workspace = workspace.replace(
        "<com.android.launcher2.CellLayout",
        "<!-- N3DS_320X240_NONOVERLAP_GRID: 4*66 + 56 = 320; "
        "3*74 = 222. -->\n<com.android.launcher2.CellLayout",
        1,
    )
WORKSPACE.write_text(workspace)

styles = STYLES.read_text()
styles = styles.replace('<item name="android:textSize">13dip</item>',
                        '<item name="android:textSize">10dip</item>')
styles = styles.replace('<item name="android:paddingLeft">5dip</item>',
                        '<item name="android:paddingLeft">2dip</item>')
styles = styles.replace('<item name="android:paddingRight">5dip</item>',
                        '<item name="android:paddingRight">2dip</item>')
styles = styles.replace('<item name="android:layout_marginLeft">10dip</item>',
                        '<item name="android:layout_marginLeft">2dip</item>')
styles = styles.replace('<item name="android:layout_marginRight">10dip</item>',
                        '<item name="android:layout_marginRight">2dip</item>')
STYLES.write_text(styles)

defaults = DEFAULTS.read_text()
global_block_old = '''        launcher:className="com.android.globaltime.GlobalTime"
        launcher:screen="1"
        launcher:x="0"
        launcher:y="1" />'''
global_block_new = '''        launcher:className="com.android.globaltime.GlobalTime"
        launcher:screen="1"
        launcher:x="1"
        launcher:y="0" />'''
if global_block_old in defaults:
    defaults = replace(defaults, global_block_old, global_block_new,
                       "default Global Time position")
DEFAULTS.write_text(defaults)

provider = PROVIDER.read_text()
provider = provider.replace("private static final int DATABASE_VERSION = 9;",
                            "private static final int DATABASE_VERSION = 10;")
if "N3DS_320X240_WORKSPACE_MIGRATION" not in provider:
    anchor = '''            if (version < 9) {
                // N3DS_SPACED_THREE_APP_WORKSPACE: version 8 inserted Global
                // Time into the gap that version 7 deliberately created. Move
                // it below Settings and repair existing databases in place.
                arrangeN3dsFavorites(db);
                version = 9;
            }
'''
    insertion = anchor + '''
            if (version < 10) {
                // N3DS_320X240_WORKSPACE_MIGRATION: the old 106px cells
                // overlapped because four could not fit beside the 56px app
                // drawer. Repack bundled apps into the corrected 66px row.
                arrangeN3dsFavorites(db);
                version = 10;
            }
'''
    provider = replace(provider, anchor, insertion, "database v10 migration")
provider = provider.replace(
    '''moveFavorite(db, "com.android.globaltime",
                    "com.android.globaltime.GlobalTime", 0, 1);''',
    '''moveFavorite(db, "com.android.globaltime",
                    "com.android.globaltime.GlobalTime", 1, 0);''')

anchor_gpu = '''moveFavorite(db, "com.android.globaltime",
                    "com.android.globaltime.GlobalTime", 1, 0);
        }'''
insertion_gpu = '''moveFavorite(db, "com.android.globaltime",
                    "com.android.globaltime.GlobalTime", 1, 0);
            moveFavorite(db, "com.android.gpuz",
                    "com.android.gpuz.GPUZActivity", 3, 0);
        }'''
if anchor_gpu in provider:
    provider = provider.replace(anchor_gpu, insertion_gpu, 1)

PROVIDER.write_text(provider)

checks = {
    LAND_DIMS: 'workspace_cell_width">66dip',
    WORKSPACE: "N3DS_320X240_NONOVERLAP_GRID",
    DEFAULTS: 'launcher:x="1"\n        launcher:y="0"',
    PROVIDER: "N3DS_320X240_WORKSPACE_MIGRATION",
}
for path, needle in checks.items():
    if needle not in path.read_text():
        raise SystemExit(f"layout verification failed: {path}: {needle}")

print("patch_n3ds_launcher_layout: exact 4x3 320x240 grid and v10 migration")
