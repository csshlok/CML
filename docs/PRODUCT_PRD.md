# Context Management Layer PRD

## 1. Product Summary

The Context Management Layer is a local desktop AI workspace for general second-brain users. Users collect files, links, notes, screenshots, documents, and chat transcripts into a local vault. The app converts this material into context clusters, trains a small local expert for each cluster, and uses those experts to feed focused context and intermediate reasoning into a larger synthesis model.

The product should feel approachable and visual like Mindly, navigable like Obsidian, and centered around chat. The main user value is not generic file search. It is turning scattered personal material into living context clusters that can answer, write, and reason in the style and knowledge boundaries of the user's own data.

## 2. Product Goals

- Let users drop mixed personal material into a local vault and have it organized into meaningful clusters.
- Create one compulsory local expert per cluster.
- Route user prompts to relevant cluster experts.
- Use cluster expert outputs as structured context for a larger final model.
- Keep all user files, prompts, vectors, and trained expert artifacts local by default.
- Make the experience usable by non-technical second-brain users.

## 3. Non-Goals For V1

- Full-device silent scanning.
- Cloud sync.
- Team collaboration.
- Mobile apps.
- Browser-only web app.
- Multi-user accounts.
- Marketplace/plugins.
- Perfect autonomous clustering with no user correction.

## 4. Target User

Primary user: a general second-brain user who stores assignments, research, links, personal notes, chat exports, screenshots, PDFs, documents, and references across many places.

The user is not expected to understand embeddings, LoRA, vector databases, or model routing. They should understand clusters as "spaces of related context" and experts as "local AI helpers trained on that space."

## 5. Core Concept

The app has three core objects:

- **Vault**: A local workspace containing imported or referenced user material.
- **Cluster**: A group of related items, such as "X Assignment", "Y Assignment", "Startup Ideas", or "Psychology Notes".
- **Cluster Expert**: A small local model/adaptor trained on one cluster and used to produce context, style guidance, source-grounded notes, and draft reasoning.

The final user-facing response is produced by a larger synthesis model that receives outputs from one or more cluster experts.

## 6. Example User Flow

1. User opens the desktop app.
2. User creates or selects a vault.
3. User drops 5 documents for X Assignment and 3 links for Y Assignment.
4. The app extracts text, screenshots, metadata, and link content.
5. The app suggests two clusters: "X Assignment" and "Y Assignment".
6. User confirms or renames the clusters.
7. The app creates a local expert for each cluster.
8. The app indexes all material for retrieval and begins local expert training.
9. User asks: "I want the style of X assignment for this question."
10. The router selects X Assignment.
11. X cluster expert produces style guidance, relevant facts, and source-grounded context.
12. The larger synthesis model writes the final answer using X's style.

## 7. V1 Scope

### 7.1 Vault Mode

V1 uses explicit vault mode. The user chooses folders or drops files into the app. The app must not scan the entire machine without explicit selection.

Supported input types for V1:

- PDF
- DOCX
- TXT
- Markdown
- Plain pasted text
- URLs
- HTML pages from URLs
- Screenshots/images with OCR
- Chat transcripts as TXT, MD, JSON, or exported HTML where practical

### 7.2 Ingestion

The app must:

- Preserve the original item.
- Extract text.
- Generate metadata.
- Chunk long text.
- Create embeddings.
- Store chunks in a local vector index.
- Generate item summary.
- Suggest tags.
- Detect probable cluster membership.

### 7.3 Clustering

The app must support:

- Automatic suggested clusters based on semantic similarity.
- Manual cluster creation.
- Manual item-to-cluster assignment.
- Cluster rename.
- Cluster merge.
- Cluster split, at least by moving selected items to a new cluster.
- Cluster description.
- Cluster color/icon.

V1 clustering should prioritize user trust over automation. The app should show cluster suggestions and let the user confirm.

### 7.4 Compulsory Cluster Experts

Every cluster must have a local expert lifecycle.

Expert states:

- `initializing`: cluster exists, expert setup has started.
- `bootstrapping`: enough indexed context exists for retrieval-backed expert behavior, but fine-tuning is not complete.
- `training`: local fine-tuning is running.
- `ready`: trained expert is available.
- `stale`: new cluster data exists since the last training run.
- `failed`: training failed; previous expert remains usable if available.

Important V1 behavior:

- A cluster is allowed to answer during `bootstrapping` using retrieval-backed context assembly.
- The product must still create and train the local expert as part of the cluster lifecycle.
- Fine-tuning must happen locally.
- Failed training must not destroy the previous working expert.

### 7.5 Cluster Expert Responsibilities

A cluster expert should produce structured intermediate output, not necessarily the final user answer.

Required expert output:

```json
{
  "cluster_id": "string",
  "cluster_name": "string",
  "confidence": 0.0,
  "relevant_facts": [],
  "style_guidance": [],
  "source_grounding": [],
  "draft_reasoning": "",
  "warnings": []
}
```

The synthesis model uses this output to generate the final response.

### 7.6 Prompt Routing

The router must:

- Embed the user prompt.
- Compare it against cluster centroids and cluster summaries.
- Select one primary cluster.
- Optionally select supporting clusters.
- Let the user override routing.
- Learn from user overrides.

Prompt examples:

- "Use the style of X assignment."
- "Answer this from my Y research."
- "Compare this with my startup notes."
- "Which of my clusters does this belong to?"

### 7.7 Final Synthesis Model

The synthesis model receives:

- User prompt.
- Selected cluster expert outputs.
- Retrieved source snippets.
- User-selected style or output constraints.
- Citations/source references where available.

The final answer must make it clear when it is using local context.

### 7.8 Context Bridge For External LLMs

The app should expose the local context layer to other LLM tools. This lets a user keep their vault, clusters, source retrieval, and local experts in this app while using an external LLM interface such as Claude terminal, Claude Desktop, local agents, IDE assistants, or other MCP-compatible tools.

The product should not depend on fragile app-specific workarounds. It should expose clean local interfaces that other tools can call.

Required bridge interfaces:

- **MCP server** for agent-compatible clients.
- **Local HTTP API** for developer tools and custom scripts.
- **CLI command** for terminal workflows.
- **Clipboard/export helper** for simple manual use.

Required bridge capabilities:

- List available clusters.
- Search the vault.
- Search within a cluster.
- Retrieve context for a query.
- Retrieve a cluster style profile.
- Ask a cluster expert for structured intermediate output.
- Build a ready-to-paste context prompt for another LLM.
- Return citations/source references with retrieved context.

Example tools:

- `list_clusters`
- `search_vault`
- `search_cluster`
- `get_cluster_context`
- `get_style_profile`
- `ask_cluster_expert`
- `build_prompt_context`

Example use case:

1. User has a Claude terminal session open.
2. User asks Claude to use the local context layer for "X Assignment".
3. Claude calls the app's local MCP tool.
4. The app retrieves X Assignment sources, style profile, and cluster expert output.
5. Claude uses that returned context to answer the user's prompt.

The bridge must respect local-first privacy. External clients should receive only the specific context requested by the user or allowed by bridge permissions.

## 8. Functional Requirements

### 8.1 Vault Management

- Create vault.
- Open vault.
- Add files.
- Add folders.
- Add pasted text.
- Add URL.
- Remove item from vault.
- Re-index item.
- View item source and extracted text.

### 8.2 Cluster Management

- List clusters.
- View cluster contents.
- Create cluster.
- Rename cluster.
- Merge clusters.
- Move item between clusters.
- Show cluster expert status.
- Trigger expert retraining.
- Reset expert.

### 8.3 Chat

- Chat is the primary interaction surface.
- User can ask globally or within a selected cluster.
- App shows selected cluster routing before or during answer generation.
- User can switch cluster manually.
- Responses should cite local sources when using retrieved documents.
- Chat history is stored locally.
- Chat turns can become training examples after user acceptance or by policy.

### 8.4 Expert Training

- Each cluster has its own local expert artifact.
- Training uses cluster documents, extracted summaries, user prompts, accepted answers, and optionally generated QA pairs.
- Training should run in the background.
- The app must avoid training while generation is active if hardware resources are constrained.
- Expert versions must be retained.
- The app must roll back on failed or low-quality training runs.

### 8.5 Search

- Global semantic search across vault.
- Cluster-scoped semantic search.
- Keyword search.
- Source filters by type, date, cluster, tag.

### 8.6 Privacy

- All user data is local by default.
- The app must disclose when any optional remote model or remote content fetch is used.
- Local files must not be uploaded without explicit user consent.
- Vault storage location must be visible in settings.

### 8.7 External LLM Integration

- Run an optional local context bridge service.
- Support MCP as the preferred integration path.
- Provide a documented local HTTP API.
- Provide a CLI for context retrieval.
- Let users enable or disable external access.
- Let users restrict bridge access by vault, cluster, or source type.
- Log recent external context requests locally.
- Show which external client requested context when detectable.
- Never expose raw files unless the user explicitly allows it.

## 9. Technical Direction

Recommended desktop stack:

- Desktop shell: Tauri preferred, Electron acceptable if Python bundling or system integration becomes easier.
- UI: React + TypeScript.
- Local service: Python + FastAPI or local IPC server.
- Metadata: SQLite.
- Vector storage: LanceDB or another embedded local vector database.
- Embeddings: local sentence-transformer model.
- OCR: local OCR engine.
- PDF extraction: PyMuPDF.
- DOCX extraction: python-docx or equivalent.
- Local inference: llama.cpp/Ollama abstraction.
- Fine-tuning: local LoRA/QLoRA pipeline where hardware permits.

## 10. Data Model

Core tables/entities:

- `Vault`
- `SourceItem`
- `ExtractedChunk`
- `Cluster`
- `ClusterMembership`
- `ClusterExpert`
- `ExpertVersion`
- `ChatSession`
- `ChatMessage`
- `TrainingExample`
- `TrainingRun`

Each source item should track:

- original path or imported file path
- source type
- extraction status
- checksum
- extracted text
- summary
- tags
- cluster memberships
- embedding/index status

Each cluster expert should track:

- cluster id
- model/adaptor path
- status
- version
- last trained at
- training data count
- quality checks
- rollback version

## 11. MVP Acceptance Criteria

V1 is successful when:

- User can create a vault.
- User can drop at least 100 mixed items.
- App extracts and indexes them locally.
- App suggests clusters.
- User can confirm, rename, merge, and move items between clusters.
- Each cluster creates a local expert lifecycle record.
- Each cluster can begin local expert training.
- User can ask a chat question against one cluster.
- User can ask a global question and have the router select a cluster.
- Final answer uses cluster expert context and cites source material.
- User can see whether an expert is bootstrapping, training, ready, stale, or failed.
- User can enable the local Context Bridge.
- An external MCP-compatible client can list clusters and request context for a query.
- A terminal user can retrieve context through the CLI and paste or pipe it into another LLM.

## 12. Risks

- Local fine-tuning may be slow or unreliable on low-end machines.
- Users may expect immediate expert readiness after dropping files.
- OCR and document parsing quality may vary.
- Automatic clustering may create confusing groups.
- Continuous training on unreviewed data may degrade expert quality.
- Bundling Python, models, and desktop UI may increase installer complexity.

## 13. Mitigations

- Use retrieval-backed bootstrapping while fine-tuning runs.
- Show clear expert status.
- Keep previous expert versions.
- Require enough data before deeper fine-tuning.
- Use user-approved chat turns as higher-quality training examples.
- Make manual cluster correction easy.
- Start with vault mode, not full-device scan.

## 14. Open Decisions

- Tauri vs Electron.
- Default local model runtime.
- Minimum supported hardware.
- Whether the synthesis model must be local in V1.
- Whether fine-tuning is true per-cluster LoRA in V1 or an initial distilled local expert artifact with LoRA following shortly after.
- Exact supported chat transcript formats.
- Whether links are stored as snapshots, live references, or both.
- Which MCP clients are officially supported first.
- Default bridge permission model.
- Whether the bridge is enabled during onboarding or only from settings.
