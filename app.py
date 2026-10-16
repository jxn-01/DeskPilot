import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from openai import OpenAI


ROOT = Path(__file__).resolve().parent
TICKET_PATH = ROOT / "sample_tickets.csv"
GUIDE_PATH = ROOT / "support_guides.md"
CATEGORIES = {"connectivity", "account_access", "software", "security", "other"}
URGENCIES = {"high", "normal"}
STOP_WORDS = {
    "a", "an", "and", "are", "after", "but", "can", "for", "from", "i",
    "in", "is", "it", "my", "of", "on", "or", "the", "to", "use", "was",
    "we", "with", "yesterday",
}


st.set_page_config(page_title="DeskPilot", page_icon="D", layout="wide")
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 3rem; }
    [data-testid="stMetric"] { border-left: 3px solid #2b7a78; padding-left: 0.75rem; }
    div[data-testid="stAlert"] { border-radius: 4px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_guides(text: str) -> list[dict[str, str]]:
    sections = re.split(r"(?m)^##\s+(.+)$", text)
    guides: list[dict[str, str]] = []
    for index in range(1, len(sections), 2):
        title = sections[index].strip()
        body = sections[index + 1].strip()
        if body:
            guides.append({"title": title, "body": body})
    return guides


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 2 and token not in STOP_WORDS
    }


def retrieve_guides(ticket_text: str, guides: list[dict[str, str]], limit: int = 2) -> list[dict[str, str]]:
    query_terms = tokenize(ticket_text)
    scored: list[tuple[int, dict[str, str]]] = []
    for guide in guides:
        guide_terms = tokenize(f"{guide['title']} {guide['body']}")
        score = len(query_terms & guide_terms)
        if score:
            scored.append((score, guide))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [guide for _, guide in scored[:limit]]


def mandatory_review(ticket_text: str, category: str, evidence: list[dict[str, str]]) -> bool:
    text = ticket_text.casefold()
    security_signals = (
        "phishing", "suspicious link", "entered my password", "entered my password on",
        "unexpected attachment", "security warning", "clicked a link",
    )
    access_request_signals = ("shared mailbox", "give me access", "grant access", "permission")
    software_signals = ("install", "installation", "remote desktop", "download")
    if not evidence or category == "security":
        return True
    if any(signal in text for signal in security_signals):
        return True
    if category == "account_access" and any(signal in text for signal in access_request_signals):
        return True
    if category == "software" and any(signal in text for signal in software_signals):
        return True
    return False


def classify_locally(ticket_text: str, evidence: list[dict[str, str]]) -> dict[str, Any]:
    text = ticket_text.casefold()
    security_signals = (
        "phishing", "suspicious link", "entered my password", "unexpected attachment",
        "security warning", "clicked a link",
    )
    if any(signal in text for signal in security_signals):
        category = "security"
    elif any(word in text for word in ("vpn", "network", "connection", "connecting")):
        category = "connectivity"
    elif any(word in text for word in ("install", "installation", "application", "software", "remote desktop")):
        category = "software"
    elif any(word in text for word in ("locked out", "account recovery", "shared mailbox", "sign-in", "access")):
        category = "account_access"
    else:
        category = "other"

    urgency = "high" if category == "security" else "normal"
    if category == "security":
        action = "Escalate to the security team immediately; do not continue routine troubleshooting."
    elif category == "connectivity":
        action = "Try the approved VPN checks in the guide; route to network support if the issue continues."
    elif category == "software":
        action = "Use the approved software catalog and approval process; do not install unapproved software."
    elif category == "account_access" and any(
        signal in text for signal in ("shared mailbox", "give me access", "grant access", "permission")
    ):
        action = "Follow the approved access-request process and obtain manager approval before granting access."
    elif category == "account_access":
        action = "Direct the user to the approved account-recovery page; never request passwords or codes."
    else:
        action = "No reliable guide match was found; ask an analyst to review the ticket."

    review = mandatory_review(ticket_text, category, evidence) or category == "other"
    return {
        "category": category,
        "urgency": urgency,
        "suggested_action": action,
        "needs_human_review": review,
        "reason": "Offline demo mode uses transparent keyword rules; verify this suggestion against the retrieved guide.",
    }


def analyze_with_llm(
    ticket_id: str,
    ticket_text: str,
    evidence: list[dict[str, str]],
    client: OpenAI,
    model: str,
) -> dict[str, Any]:
    evidence_text = "\n\n".join(
        f"[{guide['title']}]\n{guide['body']}" for guide in evidence
    ) or "No relevant support guide was retrieved."
    system_message = (
        "You assist a human enterprise service desk analyst. Use only the supplied ticket and support guides. "
        "Never claim to have performed an action. Never request passwords or verification codes. "
        "Return one JSON object with category, urgency, suggested_action, needs_human_review, and reason. "
        "category must be connectivity, account_access, software, security, or other. "
        "urgency must be high or normal. Set needs_human_review to true for security issues, access grants, "
        "software installation approvals, missing evidence, or uncertainty. If no guide supports a next step, "
        "say that an analyst must review it."
    )
    user_message = (
        f"Ticket ID: {ticket_id}\nTicket: {ticket_text}\n\nRetrieved support-guide evidence:\n{evidence_text}"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
    )
    content = response.choices[0].message.content or ""
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("The model did not return a JSON result.")
    result = json.loads(match.group(0))
    category = str(result.get("category", "other")).casefold()
    urgency = str(result.get("urgency", "normal")).casefold()
    if category not in CATEGORIES or urgency not in URGENCIES:
        raise ValueError("The model returned an unsupported category or urgency.")
    result["category"] = category
    result["urgency"] = urgency
    result["needs_human_review"] = bool(result.get("needs_human_review", True))
    result["needs_human_review"] = (
        result["needs_human_review"]
        or mandatory_review(ticket_text, category, evidence)
        or category == "other"
    )
    if category == "security":
        result["urgency"] = "high"
    result["suggested_action"] = str(result.get("suggested_action", "Analyst review required."))
    result["reason"] = str(result.get("reason", "Analyst review required."))
    return result


def read_uploaded_guides(uploaded_files: list[Any] | None) -> list[dict[str, str]]:
    if uploaded_files:
        parsed: list[dict[str, str]] = []
        for uploaded_file in uploaded_files:
            text = uploaded_file.getvalue().decode("utf-8", errors="replace")
            parsed.extend(parse_guides(text))
        return parsed
    return parse_guides(GUIDE_PATH.read_text(encoding="utf-8"))


def render_product_guide() -> None:
    st.title("DeskPilot Product Guide")
    st.caption("Product overview, usage instructions, and technical details")
    if st.button("Back to ticket queue", icon=":material/arrow_back:"):
        st.query_params.clear()
        st.rerun()

    guide_path = ROOT / "README.html"
    try:
        guide_html = guide_path.read_text(encoding="utf-8")
    except OSError as error:
        st.error(f"Could not load the product guide: {error}")
        return
    st.html(guide_html, width="stretch")


def get_config_value(name: str, default: str | None = None) -> str | None:
    try:
        value = st.secrets.get(name, default)
    except FileNotFoundError:
        value = None
    if value is None:
        value = os.getenv(name, default)
    return value


def main() -> None:
    if st.query_params.get("view") == "guide":
        render_product_guide()
        return

    st.title("DeskPilot")
    st.caption("Evidence-backed ticket triage for a human analyst")
    st.info(
        "Practice prototype using synthetic data. Suggestions are not actions; an analyst remains responsible for every decision."
    )

    api_key = get_config_value("OPENAI_API_KEY", "") or ""
    model = get_config_value("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    base_url = get_config_value("OPENAI_BASE_URL")
    live_mode = bool(api_key)
    with st.sidebar:
        with st.expander("Settings", expanded=False):
            st.subheader("Analysis mode")
            if live_mode:
                st.success(f"Live LLM mode · {model}")
                st.caption("The app sends ticket text and retrieved guide excerpts to the configured model endpoint.")
            else:
                st.warning("Offline demo mode")
                st.caption("Set OPENAI_API_KEY as an environment variable or Streamlit Cloud secret to enable live LLM analysis.")
            st.subheader("Knowledge sources")
            uploaded_guides = st.file_uploader(
                "Optional support guides (.md or .txt)",
                type=["md", "txt"],
                accept_multiple_files=True,
            )

        with st.expander("Product guide", expanded=False):
            st.markdown("#### How to use DeskPilot")
            st.markdown(
                "1. Upload a ticket CSV or use the built-in examples.\n"
                "2. Optionally add Markdown or text support guides in **Settings**.\n"
                "3. Select **Analyze tickets**, inspect the evidence, and export the results."
            )
            st.caption("Ticket CSVs must include ticket_id and description columns.")
            st.markdown("#### Human review and privacy")
            st.caption(
                "DeskPilot suggests; it does not take ticket or account actions. "
                "Use synthetic data only. Live mode sends ticket text and matched guide excerpts to the configured model."
            )
            st.link_button(
                "Open full product guide in new tab",
                url=f"{st.context.url}?view=guide",
                icon=":material/open_in_new:",
                width="stretch",
            )

    try:
        guides = read_uploaded_guides(uploaded_guides)
    except OSError as error:
        st.error(f"Could not read the default support guide: {error}")
        return
    if not guides:
        st.error("No support-guide sections were found. Add Markdown sections beginning with '##'.")
        return

    uploaded_tickets = st.file_uploader("Upload tickets as CSV", type=["csv"])
    try:
        if uploaded_tickets:
            tickets = pd.read_csv(uploaded_tickets, dtype=str).fillna("")
        else:
            tickets = pd.read_csv(TICKET_PATH, dtype=str).fillna("")
    except Exception as error:
        st.error(f"Could not read the ticket CSV: {error}")
        return

    required_columns = {"ticket_id", "description"}
    missing_columns = required_columns - set(tickets.columns)
    if missing_columns:
        st.error("CSV must contain these columns: ticket_id, description.")
        return
    tickets = tickets[["ticket_id", "description"]].head(50)
    if tickets.empty:
        st.warning("The CSV contains no tickets.")
        return

    st.subheader("Ticket queue")
    st.dataframe(tickets, width="stretch", hide_index=True)
    st.caption(f"{len(tickets)} tickets loaded · {len(guides)} guide sections available")

    if st.button("Analyze tickets", type="primary", width="content"):
        client = OpenAI(api_key=api_key, base_url=base_url) if live_mode else None
        results: list[dict[str, Any]] = []
        progress = st.progress(0, text="Starting analysis")
        for index, row in tickets.iterrows():
            ticket_id = str(row["ticket_id"])
            description = str(row["description"])
            evidence = retrieve_guides(description, guides)
            try:
                if client is not None:
                    suggestion = analyze_with_llm(ticket_id, description, evidence, client, model)
                else:
                    suggestion = classify_locally(description, evidence)
                status = "Review required" if suggestion["needs_human_review"] else "Ready for analyst"
                error_message = ""
            except Exception as error:
                suggestion = {
                    "category": "other",
                    "urgency": "normal",
                    "suggested_action": "Analysis failed; an analyst must review this ticket manually.",
                    "needs_human_review": True,
                    "reason": "The analysis could not be completed safely.",
                }
                status = "Analysis failed"
                error_message = str(error)
            results.append(
                {
                    "ticket_id": ticket_id,
                    "description": description,
                    **suggestion,
                    "source_guides": [guide["title"] for guide in evidence],
                    "evidence": [guide["body"] for guide in evidence],
                    "status": status,
                    "error": error_message,
                }
            )
            progress.progress((len(results) / len(tickets)), text=f"Analyzed {len(results)} of {len(tickets)}")
        st.session_state["deskpilot_results"] = results
        progress.empty()

    results = st.session_state.get("deskpilot_results", [])
    if not results:
        return

    st.subheader("Analyst review")
    result_frame = pd.DataFrame(results)
    metric_columns = st.columns(3)
    metric_columns[0].metric("Tickets analyzed", len(results))
    metric_columns[1].metric("Needs human review", sum(item["needs_human_review"] for item in results))
    metric_columns[2].metric("Security tickets", sum(item["category"] == "security" for item in results))

    display_columns = [
        "ticket_id", "category", "urgency", "status", "suggested_action", "source_guides"
    ]
    st.dataframe(result_frame[display_columns], width="stretch", hide_index=True)
    ticket_ids = [item["ticket_id"] for item in results]
    selected_id = st.selectbox("Inspect a ticket", ticket_ids)
    selected = next(item for item in results if item["ticket_id"] == selected_id)

    st.markdown(f"**Ticket:** {selected['description']}")
    info_columns = st.columns(3)
    info_columns[0].write(f"**Category**  \n{selected['category']}")
    info_columns[1].write(f"**Urgency**  \n{selected['urgency']}")
    info_columns[2].write(f"**Status**  \n{selected['status']}")
    if selected["needs_human_review"]:
        st.warning("Human review required. DeskPilot has not taken any action.")
    else:
        st.info("Suggested for analyst review. DeskPilot has not taken any action.")
    st.markdown(f"**Suggested next step:** {selected['suggested_action']}")
    st.markdown(f"**Why:** {selected['reason']}")
    if selected["error"]:
        st.error(f"Analysis error: {selected['error']}")
    with st.expander("Retrieved support-guide evidence", expanded=True):
        if selected["source_guides"]:
            for title, excerpt in zip(selected["source_guides"], selected["evidence"]):
                st.markdown(f"**{title}**")
                st.write(excerpt)
        else:
            st.write("No matching guide was found. Human review is required.")

    export_frame = result_frame[
        ["ticket_id", "category", "urgency", "suggested_action", "source_guides", "needs_human_review", "reason"]
    ].copy()
    export_frame["source_guides"] = export_frame["source_guides"].apply(lambda titles: "; ".join(titles))
    st.download_button(
        "Download review results as CSV",
        data=export_frame.to_csv(index=False).encode("utf-8"),
        file_name="deskpilot_review.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
