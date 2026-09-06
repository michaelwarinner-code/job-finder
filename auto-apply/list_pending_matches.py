"""
Lists every job currently sitting in 'judged_fit' status with nothing done
about it yet -- these were found and matched by discovery, but never
carried through materials generation, filling, or submission, since that
orchestration doesn't exist yet (every piece so far is a standalone script
you point at one URL by hand).

    python auto-apply/list_pending_matches.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import auto_apply_state as st


def main():
    state = st.load_state()
    pending = [j for j in state["jobs"].values() if j["status"] == "judged_fit"]

    if not pending:
        print("No jobs currently stuck in judged_fit.")
        return

    print(f"{len(pending)} job(s) matched but not yet applied to:\n")
    for j in pending:
        print(f"  {j['company_name']} -- {j['title']}")
        print(f"    {j['url']}")
        print(f"    first seen: {j['first_seen']}\n")


if __name__ == "__main__":
    main()
