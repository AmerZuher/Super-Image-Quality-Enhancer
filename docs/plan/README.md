# Planning artifacts

Review pages produced while planning the rebuild. Open the HTML files in a browser; they are self-contained.

| File | What it is | Published copy |
|---|---|---|
| [blueprint.html](blueprint.html) | Plan v1: product vision, interactive UI mockups (Studio, AI Lab, Library, Flows, Forge), operation catalog, decision form | [claude.ai artifact](https://claude.ai/artifact/HE5trVkqVBFrXt41QV67oy) |
| [architecture.html](architecture.html) | Plan v2: technical architecture proposal, rendered from [../architecture.md](../architecture.md) | [claude.ai artifact](https://claude.ai/artifact/124cg3ktgoJFkMbeh6P6oj) |
| [render.py](render.py) | Regenerates `architecture.html` from `docs/architecture.md` | |

`docs/architecture.md` is the source of truth. After editing it, run `python docs/plan/render.py` (needs `pip install markdown`). Diagrams in the Markdown use Mermaid and render on GitHub.
