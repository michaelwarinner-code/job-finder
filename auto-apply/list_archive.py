"""
Lists every archived application under auto-apply/pipeline_output/, so you
can find and review what actually went into a given one without hunting
through folders by hand.

    python auto-apply/list_archive.py
"""
import json
import os

OUTPUT_ROOT = os.path.join(os.path.dirname(__file__), "pipeline_output")


def main():
    if not os.path.isdir(OUTPUT_ROOT):
        print("No archived applications yet.")
        return

    entries = []
    for folder in sorted(os.listdir(OUTPUT_ROOT)):
        manifest_path = os.path.join(OUTPUT_ROOT, folder, "application_manifest.json")
        if not os.path.exists(manifest_path):
            continue
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        entries.append((folder, manifest))

    if not entries:
        print("No archived applications yet.")
        return

    print(f"{len(entries)} archived application(s):\n")
    for folder, m in entries:
        status = "SUBMITTED" if m["submitted"] else "dry run"
        print(f"  [{status}] {m['company_name']} -- {m['title']}")
        print(f"    {m['url']}")
        print(f"    archived: {m['archived_at']}")
        print(f"    filled: {len(m['filled'])}, skipped: {len(m['skipped'])}")
        print(f"    folder: {os.path.join(OUTPUT_ROOT, folder)}")
        print()


if __name__ == "__main__":
    main()
