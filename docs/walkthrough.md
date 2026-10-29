# Five-minute walkthrough

This is a timed presentation runbook, not a recording or a claim that local model inference was measured during development. Pre-index the example and pre-generate the proposal before presenting if CPU generation exceeds the available demo time.

## Before the presentation

Start Qdrant and Ollama, download the two configured models, and run `docsync doctor`. From the DocSync source folder, initialize the examples with `uv run python scripts/init_examples.py`. Install the CLI as described in the README, change into `examples/shop_api`, and run `docsync init`, then `docsync watch`. Open a second terminal in the same repository for review commands. Open `api.py` and `docs/api.md` side by side in your editor.

The walkthrough below uses the terminal. The optional dashboard can show the same projects and proposals when it uses the same `DOCSYNC_DATA_DIR`.

## 0:00–0:40 — The problem

“Code changes quickly; documentation often lags behind. DocSync watches saved Python changes and proposes grounded documentation edits. The developer decides what gets written.”

Run `docsync config` to show local generation and open the existing API guide. Point out that the unrelated Deployment section is human-authored.

## 0:40–1:30 — A saved code change

Change `list_products(limit: int = 10)` to `list_products(limit: int = 20)` and save. Explain the three-second debounce and cached embeddings. Show progress in the watch terminal, then run `docsync status` in the second terminal. Detailed tool activity remains available through the API/dashboard.

“The changed code is available directly. RAG supplies related documentation, tests, and surrounding functions. MCP provides bounded tools for further investigation.”

## 1:30–2:30 — Evidence and review

Run `docsync proposals`, then `docsync review PROPOSAL_ID --show` with the displayed ID. Show the diff and cited source evidence. The default should change to 20; unrelated sections should remain intact. If the model fails validation, show the failure honestly and use a pre-generated reviewed example rather than claiming the output was correct.

Run `docsync review PROPOSAL_ID --edit` to demonstrate the editor and updated diff, then confirm the application. Show the resulting file plus retained human-written section. Alternatively, `docsync review PROPOSAL_ID --accept` approves the unchanged proposal directly.

## 2:30–3:15 — An unnecessary update

Replace `return {"products": list(range(limit))}` with a temporary `products` variable and the equivalent return expression. Save. The desired decision is “no update,” because public behavior is unchanged. This is a model-quality check: if a proposal is generated, reject it and record the false positive in the evaluation.

## 3:15–4:00 — Stale-write protection

Prepare another genuine default change and wait for its proposal. Before accepting, manually edit the destination guide. Accept the older proposal: the app should block it and queue regeneration. Explain why checking the destination as well as the code protects the developer’s work.

## 4:00–4:35 — Privacy and architecture

Show `docsync config`, the explicit Gemini consent option in `docsync config --help`, and the architecture diagram. Explain that local embeddings alone do not ensure privacy; generation is local too. No repository code is executed.

## 4:35–5:00 — Evidence of engineering quality

Show the test report and retrieval comparison. Explain that fixture retrieval success does not prove vector search helps on larger projects, and that factual accuracy and reviewer effort need human scoring. Finish by identifying the next experiment: real repositories on the target CPU, using the same annotated changes and model across retrieval variants.
