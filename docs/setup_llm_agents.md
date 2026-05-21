# Setting Up LLM Agent Reasoning (ANTHROPIC_API_KEY)

By default, the SPA dashboard uses canned keyword→response pairs for agent chat.
Adding an Anthropic API key upgrades all four agents to genuine Claude reasoning.

---

## What changes with the API key

| Feature | Without key | With key |
|---|---|---|
| Dashboard chat | Keyword matching | Real Claude reasoning |
| `agent_summaries.json` | Static text | LLM-generated commentary |
| `used_llm` field | `false` | `true` |
| Commentary badge | `📋 canned` | `🤖 LLM` |

The dashboard and export pipeline work **100% without the key** — the key is strictly additive.

---

## Step 1 — Get an API key

1. Go to [console.anthropic.com](https://console.anthropic.com) → **API Keys**
2. Click **Create Key**, give it a name like `spa-agent`
3. Copy the key (starts with `sk-ant-…`)

---

## Step 2 — Add as GitHub secret

1. In your repo: **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `ANTHROPIC_API_KEY`
3. Value: paste your key

The workflow (`spa-run.yml`) already reads it:
```yaml
ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Step 3 — Local development (optional)

Create a `.env` file in the project root (already in `.gitignore`):
```
ANTHROPIC_API_KEY=sk-ant-...
```

Then load it before running:
```bash
export $(cat .env | xargs)
cd spa_core
python export_data.py --fetch
```

Or with the FastAPI server:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn spa_core.api.server:app --reload --port 8765
```

---

## Cost estimate

| Item | Value |
|---|---|
| Model | `claude-haiku-4-5-20251001` |
| Tokens per export cycle | ~600 (2 summaries × ~300 tokens) |
| Cycles per day | 6 (every 4h) |
| Cost per 1M input tokens | ~$0.80 |
| **Estimated daily cost** | **~$0.003/day** |
| **Estimated monthly cost** | **~$0.09/month** |

Dashboard chat adds a small variable cost per user question (~$0.0005 each).

Total budget: well under **$2/month** for typical usage.

---

## Model used

`claude-haiku-4-5-20251001` — Anthropic's fastest, cheapest model.
Responses are capped at 300 tokens per call (controlled in `llm_agent.py`).

To switch models, edit `LLMAgent.MODEL` in `spa_core/agents/llm_agent.py`.

---

## Files created by this feature

```
spa_core/agents/llm_agent.py      # LLMAgent class + 4 singleton instances
spa_core/agents/chat_handler.py   # Keyword routing + context injection
data/agent_summaries.json         # Written each export cycle
```

The `/api/chat` endpoint is added inline to `spa_core/api/server.py`.
