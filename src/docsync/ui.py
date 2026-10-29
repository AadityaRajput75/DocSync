import os

import httpx
import streamlit as st

from docsync.config import local_url
from docsync.documentation import preview_markdown, unified_diff

API = local_url(os.getenv("DOCSYNC_API_URL", "http://127.0.0.1:8000"))
st.set_page_config(page_title="DocSync · Documentation that follows your code", page_icon="📝", layout="wide")


def request(method, path, body=None):
    try:
        with httpx.Client(trust_env=False, timeout=40) as client:
            response = client.request(method, API + path, json=body)
        if response.is_error:
            st.error(response.json().get("detail", "Request failed"))
            return None
        return response.json()
    except httpx.RequestError:
        st.error("DocSync’s local API is unavailable. Start it with `docsync start`.")
        return None


st.title("DocSync")
st.caption("Documentation that follows your code. Review every change before it reaches your project.")
projects = request("GET", "/projects") or []
with st.sidebar:
    st.header("Your workspace")
    with st.expander("Connect a repository", expanded=not projects):
        with st.form("register"):
            root = st.text_input("Local Git repository folder", placeholder="C:/projects/my-api")
            if st.form_submit_button("Connect repository", type="primary"):
                if request("POST", "/projects", {"root": root}):
                    st.rerun()
    if not projects:
        st.info("Connect a repository to start preparing documentation.")
        st.stop()
    project_id = st.selectbox("Repository", [p["id"] for p in projects],
                              format_func=lambda key: next(p["name"] for p in projects if p["id"] == key))
    project = next(p for p in projects if p["id"] == project_id)
    st.caption(project["root"])
    with st.form("settings-" + project_id):
        watching = st.checkbox("Prepare updates after saved changes", value=project["watching"])
        provider = st.radio("Generation", ["local", "gemini"], index=0 if project["provider"] == "local" else 1,
                            format_func=lambda value: "Local · Ollama" if value == "local" else "Cloud · Gemini")
        st.caption("Gemini sends selected source code, documentation, and investigation evidence to Google. Embeddings remain local.")
        consent = st.checkbox("I allow this project’s selected code and docs to be sent to Gemini",
                              value=project["cloud_consent"])
        ignored = st.text_area("Additional ignored paths (one pattern per line)", value="\n".join(project["ignore"]))
        if st.form_submit_button("Save settings"):
            if request("PATCH", f"/projects/{project_id}", {"watching": watching, "provider": provider,
                       "cloud_consent": consent if provider == "gemini" else False,
                       "ignore": [line.strip() for line in ignored.splitlines() if line.strip()]}):
                st.rerun()
    st.caption("Source code is never executed by DocSync. Only approved Markdown changes are written.")

left, right = st.columns([3, 2])
with left:
    st.subheader(project["name"])
    st.caption("Local generation" if project["provider"] == "local" else "Cloud generation enabled for this project")
with right:
    a, b = st.columns(2)
    if a.button("Scan saved changes", use_container_width=True):
        request("POST", f"/projects/{project_id}/scan")
    if b.button("Draft initial overview", use_container_width=True):
        request("POST", f"/projects/{project_id}/bootstrap")


@st.fragment(run_every="3s")
def workspace():
    status = request("GET", f"/projects/{project_id}/status")
    if not status:
        return
    jobs = status["jobs"]
    st.caption("Configured generation model: " + status["generation_model"])
    st.divider()
    a, b, c = st.columns(3)
    a.metric("Ready for review", status["pending"])
    b.metric("Watching", "On" if status["project"]["watching"] else "Paused")
    c.metric("Latest activity", jobs[0]["state"].replace("_", " ").title() if jobs else "Ready")
    if jobs:
        st.info(jobs[0]["message"])
    with st.expander("Investigation activity"):
        for job in jobs[:8]:
            st.markdown(f"**{job['action']} · {job['state']}** — {job['message']}")
            for activity in job.get("activity", []):
                st.write(activity["message"])
                if activity.get("tool"):
                    st.caption(f"Tool: {activity['tool']}")
                if activity.get("files"):
                    st.caption(", ".join(activity["files"]))
            if job.get("usage"):
                st.caption(f"Model usage: {job['usage']}")
    if status["parse_errors"]:
        st.warning("Generation is paused while saved Python files contain syntax errors.")
        st.json(status["parse_errors"])
    if status["skipped"]:
        with st.expander(f"Skipped files ({len(status['skipped'])})"):
            st.dataframe(status["skipped"], use_container_width=True)
    proposals = request("GET", f"/projects/{project_id}/proposals") or []
    st.subheader("Documentation updates")
    if not proposals:
        st.write("Updates will appear here after a code change. You can also draft an initial overview.")
        return
    choice = st.selectbox("Update", [p["id"] for p in proposals],
                          format_func=lambda key: next(f"{p['path']} · {p['state']}" for p in proposals if p["id"] == key))
    proposal = request("GET", f"/proposals/{choice}")
    if not proposal:
        return
    st.write(proposal["summary"])
    st.caption(proposal["reason"] + " · Source revision " + proposal["source_hash"][:12])
    diff_tab, preview_tab, evidence_tab = st.tabs(["Changes", "Preview", "Supporting evidence"])
    with diff_tab:
        st.code(proposal["diff"] or "No text changes", language="diff")
    with preview_tab:
        st.markdown(preview_markdown(proposal.get("applied_content", proposal["content"])))
    with evidence_tab:
        for item in proposal["evidence"]:
            st.markdown(f"**{item['path']} · lines {item['start']}–{item['end']}**")
            st.code(item["text"], language="python" if item["path"].endswith(".py") else "markdown")
    st.download_button("Download proposed Markdown", proposal["content"], file_name=proposal["path"].split("/")[-1])
    if proposal["state"] == "pending":
        accept, reject = st.columns(2)
        if accept.button("Accept and apply", key="accept-" + choice, type="primary", use_container_width=True):
            if request("POST", f"/proposals/{choice}/review", {"decision": "accept"}):
                st.rerun(scope="fragment")
        if reject.button("Reject", key="reject-" + choice, use_container_width=True):
            if request("POST", f"/proposals/{choice}/review", {"decision": "reject"}):
                st.rerun(scope="fragment")
        with st.expander("Edit before applying"):
            content = st.text_area("Markdown", proposal["content"], height=300, key="edit-" + choice)
            st.code(unified_diff(proposal["path"], proposal["before"], content), language="diff")
            if st.button("Apply my edited version", key="edited-" + choice):
                if request("POST", f"/proposals/{choice}/review", {"decision": "edit", "content": content}):
                    st.rerun(scope="fragment")


workspace()
