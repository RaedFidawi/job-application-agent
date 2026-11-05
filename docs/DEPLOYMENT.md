# Deployment

## Streamlit Community Cloud (free)

Hosts the web UI from this GitHub repo. Visitors bring their own Anthropic API key, so hosting costs you nothing.

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Repository: your fork. Branch: `main`. Main file path: `src/job_agent/web.py`.
4. Under **Advanced settings**, choose Python 3.12.
5. Click **Deploy**. `requirements.txt` installs the package and its dependencies.

> **Don't add your own `ANTHROPIC_API_KEY` as a secret** unless you intend to pay for every visitor's usage. Without it, each user enters their own key in the sidebar. The key lives only in their session and is never written to the checkpoint store.

**Limitation:** the web app keeps runs in memory, so a review in progress is lost when the app restarts or sleeps. For durability, replace `InMemorySaver` in `web.py` with `PostgresSaver` from `langgraph-checkpoint-postgres`.

## LangSmith Deployment (hosted API)

`langgraph.json` describes the graph, so it can be deployed to [LangSmith Deployment](https://docs.langchain.com/langsmith/deployments) (formerly LangGraph Platform). You get an HTTP API with durable Postgres checkpoints, background runs, streaming, and LangGraph Studio connected to production. Choose this if other applications need to call the agent.

Test the same server locally first:

```bash
pip install -e ".[dev]"
langgraph dev
```

## Tracing

Set these variables wherever the agent runs to record every node and LLM call in [LangSmith](https://smith.langchain.com):

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=job-agent
```
