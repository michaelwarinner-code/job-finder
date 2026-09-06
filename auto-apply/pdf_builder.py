"""
Turns resume_data/coverletter_data dicts (from materials_writer.py) into
actual DOCX and PDF files, by calling into the separate ResumeCustomizer
folder -- the same Node scripts and LibreOffice conversion your existing
build.bat uses, just driven from Python instead of a batch file. Does NOT
modify build.bat or anything inside ResumeCustomizer -- this is a thin
wrapper that runs the same commands.

Requires Node.js and LibreOffice already installed and working locally
(both already confirmed working via your existing manual workflow).

Update RESUMECUSTOMIZER_DIR / SOFFICE_PATH below if either ever moves.
"""
import json
import os
import subprocess

RESUMECUSTOMIZER_DIR = r"C:\Users\thebo\OneDrive\Documents\ResumeCustomizer"
SOFFICE_PATH = r"C:\Program Files\LibreOffice\program\soffice.exe"
COMMAND_TIMEOUT_SECONDS = 120


def _run(cmd: list, cwd: str = None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
    return result


def build_resume_and_coverletter(resume_data: dict, coverletter_data: dict, output_dir: str) -> tuple:
    """
    Writes resume_data/coverletter_data to JSON files in output_dir, runs
    the same generate_resume.js / generate_cover_letter.js / LibreOffice
    conversion steps build.bat uses, and returns (resume_pdf_path,
    coverletter_pdf_path).

    Raises RuntimeError with the real stdout/stderr from whichever step
    failed, rather than silently producing a missing or corrupt file.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_dir = os.path.abspath(output_dir)

    resume_json_path = os.path.join(output_dir, "resume_data.json")
    cl_json_path = os.path.join(output_dir, "coverletter_data.json")
    with open(resume_json_path, "w", encoding="utf-8") as f:
        json.dump(resume_data, f, indent=2)
    with open(cl_json_path, "w", encoding="utf-8") as f:
        json.dump(coverletter_data, f, indent=2)

    resume_docx = os.path.join(output_dir, "resume.docx")
    cl_docx = os.path.join(output_dir, "cover_letter.docx")

    _run(["node", "generate_resume.js", resume_json_path, resume_docx], cwd=RESUMECUSTOMIZER_DIR)
    _run(["node", "generate_cover_letter.js", cl_json_path, cl_docx], cwd=RESUMECUSTOMIZER_DIR)

    _run([SOFFICE_PATH, "--headless", "--convert-to", "pdf", "--outdir", output_dir, resume_docx])
    _run([SOFFICE_PATH, "--headless", "--convert-to", "pdf", "--outdir", output_dir, cl_docx])

    resume_pdf = os.path.join(output_dir, "resume.pdf")
    cl_pdf = os.path.join(output_dir, "cover_letter.pdf")

    if not os.path.exists(resume_pdf) or not os.path.exists(cl_pdf):
        raise RuntimeError(f"Expected PDFs not found after build -- resume exists: {os.path.exists(resume_pdf)}, "
                            f"cover letter exists: {os.path.exists(cl_pdf)}. Check the command output above.")

    return resume_pdf, cl_pdf
