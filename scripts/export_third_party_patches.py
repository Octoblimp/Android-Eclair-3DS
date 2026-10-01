#!/usr/bin/env python3
"""Export the nested third_party/ repositories as plain diffs against upstream.

The parent repository records the kernel, AOSP projects and linux-3ds trees
as gitlinks. A public copy carries their changes as patches instead:

  OUT/<name>.diff   text changes, upstream base -> HEAD (plain `git diff`, so
                    no author lines or e-mail addresses)
  OUT/MANIFEST.tsv  path, upstream URL, base commit, branch hint, patch file
  OUT/BINARIES.tsv  binary files the diffs leave out, with size and SHA-256
  OUT/linux.config  the kernel .config the release was built with

Binary files are never exported: some are Nintendo firmware (user-supplied,
README "Firmware"), the rest are build outputs and media that the build
scripts regenerate and the release zip carries.

--verify replays every diff onto its base in a scratch index and requires the
result to equal HEAD except for exactly the omitted binaries.

    scripts/export_third_party_patches.py OUT [--verify]
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str, env=None, data: bytes = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=off", *args],
                          input=data, env=env, check=True, stdout=subprocess.PIPE).stdout


def text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode().strip()


def gitlinks() -> list:
    out = git(ROOT, "ls-files", "-s", "-z").split(b"\0")
    links = []
    for entry in out:
        if entry.startswith(b"160000 "):
            links.append(entry.split(b"\t", 1)[1].decode())
    return sorted(links)


def upstream_base(repo: Path):
    """Merge-base with a remote-tracking ref, else the (shallow) root commit."""
    refs = text(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").split()
    for ref in refs:
        if ref.endswith("/HEAD"):
            continue
        try:
            # refs/remotes/<remote>/<branch...>
            return text(repo, "merge-base", "HEAD", ref), ref.split("/", 3)[3]
        except subprocess.CalledProcessError:
            continue
    roots = text(repo, "rev-list", "--max-parents=0", "HEAD").split()
    return roots[-1], ""


def kind(path: str) -> str:
    if "/usr/lib/firmware/ath6k/" in path or "/usr/lib/firmware/3ds/" in path:
        return "firmware: user-supplied, see README Firmware"
    if "/usr/lib/firmware/regulatory.db" in path:
        return "wireless-regdb (upstream, redistributable)"
    return "build output or media: rebuilt by scripts/, also in the release zip"


def export(out: Path, verify: bool) -> int:
    out.mkdir(parents=True, exist_ok=True)
    manifest = ["path\turl\tbase\tbranch\tpatch\ttext_files\tbinary_files_omitted"]
    binaries = ["repo\tpath\tstatus\tsize\tsha256\tkind"]
    failures = 0
    for path in gitlinks():
        repo = ROOT / path
        url = text(repo, "remote", "get-url", "origin")
        base, branch = upstream_base(repo)
        if text(repo, "status", "--porcelain", "--untracked-files=no"):
            print(f"warning: {path} has uncommitted changes; only HEAD is exported", file=sys.stderr)
        records = git(repo, "diff", "--numstat", "-z", "--no-renames", base, "HEAD").split(b"\0")
        text_files, binary_files = [], []
        for rec in records:
            if not rec:
                continue
            added, _deleted, name = rec.decode().split("\t", 2)
            (binary_files if added == "-" else text_files).append(name)
        patch = "-"
        if text_files:
            patch = path.replace("third_party/", "", 1).replace("/", "_") + ".diff"
            chunks = []
            for i in range(0, len(text_files), 400):
                chunks.append(git(repo, "diff", "--no-color", "--no-ext-diff", "--no-renames",
                                  "--full-index", base, "HEAD", "--", *text_files[i:i + 400]))
            (out / patch).write_bytes(b"".join(chunks))
        for name in binary_files:
            try:
                blob = git(repo, "show", f"HEAD:{name}")
                binaries.append(f"{path}\t{name}\tchanged\t{len(blob)}\t"
                                f"{hashlib.sha256(blob).hexdigest()}\t{kind(name)}")
            except subprocess.CalledProcessError:
                binaries.append(f"{path}\t{name}\tdeleted\t-\t-\t{kind(name)}")
        # "-" for an empty field: shell `read` collapses consecutive tabs.
        manifest.append(f"{path}\t{url}\t{base}\t{branch or '-'}\t{patch}\t"
                        f"{len(text_files)}\t{len(binary_files)}")
        print(f"{path:32} base {base[:12]}  text {len(text_files):5}  binary omitted {len(binary_files):4}  {patch}")

        if verify and patch != "-":
            with tempfile.TemporaryDirectory() as tmp:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
                git(repo, "read-tree", base, env=env)
                git(repo, "apply", "--cached", "--whitespace=nowarn", str(out / patch), env=env)
                tree = git(repo, "write-tree", env=env).decode().strip()
                left = sorted(git(repo, "diff", "--name-only", "-z", "--no-renames", tree, "HEAD")
                              .decode().split("\0"))
                left = [n for n in left if n]
                if left != sorted(binary_files):
                    failures += 1
                    extra = sorted(set(left) - set(binary_files))
                    print(f"  VERIFY FAIL: {len(extra)} non-binary paths differ, e.g. {extra[:3]}")
                else:
                    print("  verify: base + patch == HEAD except the omitted binaries")

    (out / "MANIFEST.tsv").write_text("\n".join(manifest) + "\n")
    (out / "BINARIES.tsv").write_text("\n".join(binaries) + "\n")
    config = ROOT / "third_party/linux/.config"
    if config.is_file():
        (out / "linux.config").write_bytes(config.read_bytes())
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if export(args.out, args.verify):
        sys.exit("patch verification failed")


if __name__ == "__main__":
    main()
