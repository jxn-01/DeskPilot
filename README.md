# DeskPilot Practice Prototype

DeskPilot is a practice project for an AI Friday event. It helps service desk analysts triage synthetic employee support tickets by suggesting a category, urgency, evidence-backed next step, and whether a human must review the ticket.

**[Open the rendered product and technical guide](https://jxn-01.github.io/DeskPilot/README.html)** · [Launch the live app](https://deskpilot123.streamlit.app/)

## Files

- `sample_tickets.csv`: synthetic input tickets for the demo
- `expected_results.csv`: separate answer key for evaluating outputs; do not upload this file to the app
- `support_guides.md`: fictional source material for retrieval
- `prototype_rules.md`: categories, urgency, escalation rules, and output requirements
- `app.py`: Streamlit prototype
- `requirements.txt`: Python dependencies

## Run on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Without an API key, the app runs in offline demo mode using simple keyword rules. To use a compatible LLM endpoint, set `OPENAI_API_KEY`; optionally set `OPENAI_MODEL` and `OPENAI_BASE_URL` in the local PowerShell session before starting Streamlit. Never put a real key in the source files or sample data.

The first version uses lightweight keyword matching to retrieve guide sections and a single LLM call per ticket when live mode is enabled. It does not yet use LangChain, vector embeddings, PDF extraction, or connect to a real ticketing system. The workflow includes separate triage, evidence retrieval, and safety-review steps, with a human responsible for decisions.

## Deploy to Streamlit Community Cloud

1. Push this project to a GitHub repository. Include `app.py`, `requirements.txt`, and the synthetic CSV and Markdown files. Do not commit `.venv`, `.env`, API keys, or real support tickets.
2. Sign in to Streamlit Community Cloud, choose **Create app**, and select the repository, branch, and `app.py` as the main file.
3. Deploy. The app starts in offline demo mode if no API key is configured.
4. To enable live LLM analysis, open the deployed app's **Settings > Secrets** and add:

```toml
OPENAI_API_KEY = "your-key"
OPENAI_MODEL = "gpt-4o-mini"
# Optional for a compatible enterprise endpoint:
# OPENAI_BASE_URL = "https://your-approved-endpoint/v1"
```

The app reads Cloud secrets directly; local runs can continue using environment variables. The deployed demo has no authentication, so use synthetic data only and treat anyone with the app URL as able to access it.

## Safety boundary

This is a demonstration only. Use synthetic data. DeskPilot must not perform actions on accounts, devices, permissions, or tickets. A human analyst makes every operational decision.
