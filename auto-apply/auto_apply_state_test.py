"""
Standalone test for auto_apply_state.py. Doesn't touch your real
state/auto_apply_state.json -- uses a temp path instead. Run:

    python auto-apply/auto_apply_state_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import auto_apply_state as st

# Redirect to a temp file so this test never touches your real state.
st.STATE_PATH = os.path.join(tempfile.gettempdir(), "auto_apply_state_test.json")
if os.path.exists(st.STATE_PATH):
    os.remove(st.STATE_PATH)


def main():
    state = st.load_state()
    print(f"[start] daily count: {st.get_daily_count(state)}, cap reached: {st.is_daily_cap_reached(state, cap=15)}")

    job_id = "greenhouse:datagrail:7807686003"
    print(f"\n[test] is_already_handled before any status set: {st.is_already_handled(state, job_id)} (expect False)")

    st.set_job_status(state, job_id, "discovered", company_name="DataGrail",
                       title="Senior Product Marketing Manager", url="https://job-boards.greenhouse.io/datagrail/jobs/7807686003")
    print(f"[test] status after discovery: {st.get_job_status(state, job_id)} (expect 'discovered')")

    st.set_job_status(state, job_id, "submitted")
    st.increment_daily_count(state)
    print(f"[test] status after submit: {st.get_job_status(state, job_id)} (expect 'submitted')")
    print(f"[test] is_already_handled after submit: {st.is_already_handled(state, job_id)} (expect True -- won't reprocess)")
    print(f"[test] daily count after 1 submit: {st.get_daily_count(state)} (expect 1)")

    # Pending-answer expiry test -- manually backdate pending_since to simulate 25 hours ago.
    from datetime import datetime, timezone, timedelta
    job_id_2 = "ashby:clera:abc123"
    st.set_job_status(state, job_id_2, "pending_answer", company_name="Clera", title="Growth Lead")
    state["jobs"][job_id_2]["pending_since"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()

    expired = st.expire_stale_pending(state, timeout_hours=24)
    print(f"\n[test] jobs expired after 25h pending (24h timeout): {expired} (expect [{job_id_2!r}])")
    print(f"[test] status after expiry: {st.get_job_status(state, job_id_2)} (expect 'skipped_no_response')")

    for i in range(14):
        st.increment_daily_count(state)
    print(f"\n[test] daily count after 15 total: {st.get_daily_count(state)} (expect 15)")
    print(f"[test] cap reached at 15/15: {st.is_daily_cap_reached(state, cap=15)} (expect True)")

    st.save_state(state)
    print(f"\n[done] state saved to {st.STATE_PATH}")


if __name__ == "__main__":
    main()
