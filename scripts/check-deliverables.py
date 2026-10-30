#!/usr/bin/env python3
"""Check design deliverables and local Markdown links; no business execution.

Only Python's standard library is needed. --root can select a clean candidate
checkout, so the checker itself need not be part of that candidate commit.
"""
import argparse
from collections import Counter
from pathlib import Path
import re
import struct
import subprocess
import unicodedata
from urllib.parse import unquote
import xml.etree.ElementTree as ET


def prose(text):
    return re.sub(r"^```.*?^```\s*$", "", text, flags=re.S | re.M)


def headings(path):
    counts, result = Counter(), set()
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", prose(path.read_text(encoding="utf-8")), re.M):
        title = re.sub(r"<[^>]*>", "", title).strip().lower().replace("`", "")
        title = "".join(c for c in title if c in "-_ " or unicodedata.category(c)[0] in "LN").replace(" ", "-")
        result.add(title + ("-" + str(counts[title]) if counts[title] else ""))
        counts[title] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    errors, refs, anchors = [], 0, 0
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode("utf-8").split("\0")
    # Include newly prepared docs without traversing .git, virtualenvs or dependencies.
    markdown = {root / p for p in tracked if p.endswith(".md")}
    for folder in (root / "docs", root / "contracts"):
        markdown.update(folder.rglob("*.md"))
    for path in sorted(markdown):
        if not path.is_file():
            errors.append(f"missing tracked Markdown: {path.relative_to(root)}")
            continue
        text = re.sub(r"`[^`]*`", "", prose(path.read_text(encoding="utf-8")))
        for target in re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", text):
            dest, sep, fragment = target.strip("<>").partition("#")
            if re.match(r"^[a-zA-Z][\w+.-]*:", dest):
                continue
            refs += 1
            resolved = (path.parent / unquote(dest)).resolve() if dest else path
            if not resolved.exists():
                errors.append(f"{path.relative_to(root)}: missing {target}")
            elif sep and resolved.suffix == ".md":
                anchors += 1
                if unquote(fragment) not in headings(resolved):
                    errors.append(f"{path.relative_to(root)}: missing anchor {target}")

    required = ["README.md", "docs/design.md", "architecture.png", "docs/diagrams/architecture.svg",
                "contracts/http/openapi.yaml", "contracts/http/internal.yaml", "contracts/events/event.schema.json"]
    stems = ["data-model-ride", "data-model-billing", "data-model-support", "quote-request-match",
             "booking-recovery", "cancel-rebook", "cancellation-races", "pickup-trip-payment", "trip-payment-recovery"]
    for stem in stems:
        required += [f"docs/diagrams/{stem}.{ext}" for ext in ("mmd", "png")]
    for name in required:
        if not (root / name).is_file() or not (root / name).stat().st_size:
            errors.append(f"missing/empty deliverable: {name}")
    if errors:
        for error in errors:
            print("FAIL", error)
        return 1

    report = (root / "docs/design.md").read_text(encoding="utf-8")
    if "![" not in report or "(../architecture.png)" not in report:
        errors.append("root architecture.png is not embedded in design.md")
    svg = ET.parse(root / "docs/diagrams/architecture.svg")
    names = [e.attrib["data-service"] for e in svg.iter() if "data-service" in e.attrib]
    if len(names) != 8 or len(set(names)) != 8 or any(n not in report for n in names):
        errors.append("architecture/report service names disagree")
    section = report.partition("### 通信清单与整体图对照")[2]
    if set(re.findall(r"^\| (C-\d{2}) \|", section, re.M)) != {f"C-{n:02d}" for n in range(1, 19)}:
        errors.append("architecture mapping does not cover C-01..C-18")
    for stem in ["architecture"] + ["docs/diagrams/" + n for n in stems]:
        with (root / (stem + ".png")).open("rb") as stream:
            header = stream.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or len(header) != 24:
            errors.append(f"invalid PNG header: {stem}")
        else:
            print("IMAGE", stem + ".png", *struct.unpack(">II", header[16:24]))
    checklist = (root / "docs/review-checklist.md").read_text(encoding="utf-8")
    results = (root / "docs/review-results.md").read_text(encoding="utf-8")
    ids = lambda text: re.findall(r"^\| (DR-[A-Z]\d{2}) \|", text, re.M)
    if len(ids(checklist)) != 57 or len(set(ids(checklist))) != 57 or ids(checklist) != ids(results):
        errors.append("review checklist/results IDs differ or contain duplicates")
    for error in errors:
        print("FAIL", error)
    if not errors:
        print(f"PASS {len(markdown)} Markdown files; {refs} local references; {anchors} anchors; 10 PNG headers; 8 services; 18 interactions; 57 review IDs.")
    print("Static artifact/reference checks only; image readability and business semantics require review.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
