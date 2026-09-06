"""
Archives exactly what went into each application -- the Q&A record to sit
alongside the resume/cover letter PDFs pdf_builder.py already saves in the
same folder, so you can review what was actually submitted (or would have
been, for a dry run) later.

Not wired to auto-delete anything -- these accumulate under
auto-apply/pipeline_output/. Fine to manually delete old job folders
whenever you want; nothing else depends on them persisting.
"""
import json
import os
from datetime import datetime, timezone


def archive_application(job_output_dir: str, company_name: str, title: str, url: str,
                         report: dict, submitted: bool) -> str:
    """Saves application_manifest.json into job_output_dir -- the same
    folder pdf_builder.py already wrote resume.pdf/cover_letter.pdf/
    resume_data.json/coverletter_data.json into -- recording exactly what
    was asked, what was answered and from where (answer bank, EEO
    settings, Telegram escalation, etc.), and whether this run actually
    submitted or was a dry run. Returns the manifest's path."""
    manifest = {
        "company_name": company_name,
        "title": title,
        "url": url,
        "submitted": submitted,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "filled": report.get("filled", []),
        "skipped": report.get("skipped", []),
        "screenshot_path": report.get("screenshot_path", ""),
    }
    os.makedirs(job_output_dir, exist_ok=True)
    manifest_path = os.path.join(job_output_dir, "application_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest_path
