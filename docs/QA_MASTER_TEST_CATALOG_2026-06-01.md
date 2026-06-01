# QA Master Test Catalog 2026-06-01

Target: 180 concrete QA cases covering the original testing-parameters brief plus added security, abuse, and regression cases.

Status legend:
- `Auto`: executable in local test suites or lightweight scripts.
- `Manual`: requires packaged Electron, OS process control, large fixtures, or human UI validation.
- `Hybrid`: automation plus manual observation.

## Vault Lock And Process Ownership

1. `QA-001` Auto: Launch backend with no lock file; expect lock creation and startup progress.
2. `QA-002` Hybrid: Relaunch after stale lock from dead PID; expect reclaim and audit row.
3. `QA-003` Manual: Double-open same vault in packaged app; expect second instance to focus first window only.
4. `QA-004` Manual: Double-open different vault path; expect warning and no second writer.
5. `QA-005` Manual: Lock file references live unrelated process; expect unverifiable warning, not silent reclaim.
6. `QA-006` Manual: Denied CIM/PowerShell identity lookup; expect unverifiable status and explicit user choice.
7. `QA-007` Auto: Lock audit includes acquire and release events.
8. `QA-008` Manual: Override dialog cancellation writes user-choice audit row.
9. `QA-009` Manual: Crash before override choice writes interrupted audit row on next launch.
10. `QA-010` Manual: Override-once launch resets override flag after restart.
11. `QA-011` Manual: Lock file malformed JSON or garbage text yields safe failure path.
12. `QA-012` Manual: Lock file points to missing vault path; expect safe refusal or repair flow.

## Startup Phases And Integrity Gates

13. `QA-013` Auto: Pre-vault mode reports restricted startup and returns health/preflight routes.
14. `QA-014` Manual: Full-vault happy path writes every startup phase in order.
15. `QA-015` Manual: Corrupt SQLite causes integrity-check failure and repair screen.
16. `QA-016` Manual: Slow integrity check shows progress message before timeout.
17. `QA-017` Manual: Unknown schema migration state halts startup before private APIs open.
18. `QA-018` Auto: Missing startup status file falls back to readable defaults.
19. `QA-019` Auto: Private APIs return `409` in `pre_vault` mode.
20. `QA-020` Auto: `/health` responds before vault initialization.
21. `QA-021` Auto: `/api/v1/system/preflight/disk` responds before vault initialization.
22. `QA-022` Manual: Startup failure keeps backend private routes unavailable.
23. `QA-023` Manual: Startup repair screen shows data-dir and DB-path context.
24. `QA-024` Manual: Restart after failure refreshes startup phase state instead of stale UI.

## Scheduler And Job Lifecycle

25. `QA-025` Auto: High-priority jobs claim before low-priority jobs.
26. `QA-026` Auto: Same write-scope jobs do not run concurrently.
27. `QA-027` Auto: Dependency failure with cancel policy cancels dependent job.
28. `QA-028` Auto: Running requeue job returns to queued after restart recovery.
29. `QA-029` Auto: Unknown job type moves to manual review without killing worker loop.
30. `QA-030` Auto: Recent retriable generation blocks non-synthesis-safe jobs.
31. `QA-031` Auto: Old retriable generation does not block job claiming.
32. `QA-032` Auto: Non-cancellable job cancel route returns `409`.
33. `QA-033` Auto: Cancellable queued job cancel route returns cancelled status.
34. `QA-034` Auto: Running job contributes to queue-status runtime estimate.
35. `QA-035` Manual: Retry action on retriable generation reacquires synthesis gate before streaming.
36. `QA-036` Manual: Queue survives backend restart without duplicate simultaneous execution.

## Source Ingestion: Local Files

37. `QA-037` Auto: Text source creates one page and page-linked chunks.
38. `QA-038` Auto: Duplicate same-content ingest reuses original source by checksum.
39. `QA-039` Auto: Same file after one-byte modification creates a new source.
40. `QA-040` Auto: Unsupported `.exe` local ingest is rejected clearly.
41. `QA-041` Auto: Zero-byte `.txt` ingest is rejected clearly.
42. `QA-042` Auto: Code file ingest prefixes metadata and preserves readable code.
43. `QA-043` Auto: Media file ingest stores metadata note instead of fake transcript.
44. `QA-044` Manual: 10-page text PDF produces ten `source_pages`.
45. `QA-045` Auto: OCR fallback path for scanned PDF prefers OCRmyPDF then Tesseract render.
46. `QA-046` Manual: Image-only DOCX raises explicit no-readable-text or OCR-noted result.
47. `QA-047` Manual: 500-page PDF ingest avoids large memory spikes.
48. `QA-048` Manual: Oversized local file over safe limit is rejected without partial records.
49. `QA-049` Manual: Unicode filename survives title/path storage and reveal-in-folder action.
50. `QA-050` Probe: Windows-1252 text preserves smart quotes correctly instead of replacement characters.
51. `QA-051` Probe: Null bytes in pasted or file text are sanitized or rejected safely.
52. `QA-052` Manual: Symbolic-link edge cases do not bypass file validation.

## Source Ingestion: URL And Network

53. `QA-053` Auto: Thin SPA HTML triggers dynamic-extraction fallback when Playwright is available.
54. `QA-054` Auto: Redirect loop aborts with bounded redirect count.
55. `QA-055` Manual: `https://example.com` ingests readable text successfully.
56. `QA-056` Manual: `404` URL fails without zombie source row.
57. `QA-057` Manual: Authentication/login page is flagged instead of treated as captured content.
58. `QA-058` Manual: 50MB HTML is truncated or rejected by bounded-size rules.
59. `QA-059` Manual: Mixed-content redirects remain subject to public-URL validation.
60. `QA-060` Manual: SSRF attempt to localhost/private subnet is rejected.
61. `QA-061` Manual: Invalid certificate or TLS failure surfaces clean error.
62. `QA-062` Manual: Non-HTML text response is stored as plain text.
63. `QA-063` Manual: URL with Unicode domain/path remains normalized and safe.
64. `QA-064` Manual: Dynamic extraction absence produces explicit degraded note, not silent emptiness.

## Pasted Text And Direct Source Creation

65. `QA-065` Manual: Empty pasted text is rejected or stored with explicit zero-content state.
66. `QA-066` Manual: Very large pasted text is truncated with warning.
67. `QA-067` Manual: SQL-injection-looking text stores literally and does not mutate schema.
68. `QA-068` Probe: Text with null bytes does not corrupt SQLite or chunking.
69. `QA-069` Manual: Emoji-heavy pasted text survives roundtrip.
70. `QA-070` Manual: Repeated whitespace normalization does not erase meaningful structure unexpectedly.
71. `QA-071` Manual: Newlines are preserved enough for readable previews.
72. `QA-072` Manual: Pasted text source is immediately searchable after indexing.
73. `QA-073` Manual: Pasted text with same checksum deduplicates.
74. `QA-074` Manual: Pasted text with edited trailing punctuation becomes a new source.
75. `QA-075` Manual: Very long title validation rejects over-limit values cleanly.
76. `QA-076` Manual: Invalid cluster target for pasted text is rejected.

## Chat Attachments And Chat Ingestion

77. `QA-077` Auto: Chat attachment is ingested and linked to session/message/source.
78. `QA-078` Manual: Chat attachment with no active vault is rejected cleanly.
79. `QA-079` Manual: Duplicate same-file attachment in same chat deduplicates to one source.
80. `QA-080` Manual: Unsupported attachment type rejects before ingestion completes.
81. `QA-081` Manual: Delete chat during attachment ingest leaves no orphan user-facing source.
82. `QA-082` Manual: Attachment cluster override validates same-vault cluster ownership.
83. `QA-083` Manual: Attachment with unreadable path fails with clear per-file error.
84. `QA-084` Manual: Multiple attachments preserve per-file stored-source mapping.
85. `QA-085` Manual: Attachment ingest contributes cluster refresh-needed lifecycle events.
86. `QA-086` Manual: Attachment OCR-unavailable image stores metadata note rather than empty text.
87. `QA-087` Manual: Attachment size ceiling prevents oversized unsafe ingest.
88. `QA-088` Manual: Attachment delete after source deletion updates retrieval snapshots.

## Embeddings And Search

89. `QA-089` Auto: Missing source chunks are detected and reindex job is queued.
90. `QA-090` Auto: Stale embedding model IDs trigger reindex reconciliation.
91. `QA-091` Auto: Embedding runtime without model path reports explicit degraded state.
92. `QA-092` Auto: Embedding download failure reports missing runtime without crashing.
93. `QA-093` Manual: No embedding model configured blocks retrieval, clustering, and Bridge retrieval with explicit reason.
94. `QA-094` Manual: Hash embeddings without dev flag are refused in production mode.
95. `QA-095` Manual: Corrupted embedding model path returns load-failed status, not backend crash.
96. `QA-096` Manual: Disk-full during vector write leaves source text intact and job retryable.
97. `QA-097` Manual: Process death mid-embedding leads to restart recovery or reconciliation retry.
98. `QA-098` Manual: Mixed-model vectors do not appear in a single scored result set.
99. `QA-099` Manual: Search with partial missing vectors still returns healthy-vector results.
100. `QA-100` Manual: Search response metadata acknowledges skipped or degraded vector coverage.
101. `QA-101` Manual: Large vault reconciliation is incremental, not full scan on every launch.
102. `QA-102` Manual: Search latency target under scale stays within SLA.

## Chat Pipeline And Streaming

103. `QA-103` Auto: General greeting routes to direct answer with no citations.
104. `QA-104` Auto: Retrieval-backed answer writes generation and retrieval snapshot.
105. `QA-105` Auto: Coverage ledger counts analyzed and low-relevance sources.
106. `QA-106` Auto: Expanded analysis sets `intent = expanded_analysis` and queues job.
107. `QA-107` Auto: Expanded analysis evidence packets are persisted.
108. `QA-108` Auto: Timeline endpoint includes retriable generation items.
109. `QA-109` Auto: Startup recovery marks in-flight generations retriable.
110. `QA-110` Auto: Reserved `complete_analysis` field returns `501`.
111. `QA-111` Manual: Stream event order is `meta`, tokens, `done`.
112. `QA-112` Manual: Mid-stream network drop leaves retriable placeholder instead of silent gap.
113. `QA-113` Manual: Backend restart mid-stream produces retriable generation in timeline.
114. `QA-114` Manual: Retry on retriable generation creates new in-flight record before streaming.
115. `QA-115` Manual: Ambiguous prompt routing is logged and inspectable for tuning.
116. `QA-116` Manual: Retrieval snapshot is transactionally aligned with assistant message write.

## Deletion And Retention

117. `QA-117` Auto: Deleted source disappears from semantic search immediately.
118. `QA-118` Auto: Deleted source text, summary, path, URL, checksum are cleared immediately.
119. `QA-119` Auto: Existing citation snapshot marks deleted source as `source_deleted`.
120. `QA-120` Auto: Deleting chat session removes transcript sources and chunks.
121. `QA-121` Manual: Source delete during active ingest aborts or fully tombstones eventual writes.
122. `QA-122` Manual: Deleted sensitive content is unreachable before async cleanup completes.
123. `QA-123` Manual: Retrieval snapshot items for deleted pages/chunks preserve excerpt with deleted label.
124. `QA-124` Manual: Transcript-derived sources tied to deleted source chains are cleaned consistently.
125. `QA-125` Manual: Delete-source cleanup job is idempotent on repeated retries.
126. `QA-126` Manual: Delete-source job cancellation is forbidden for safety.
127. `QA-127` Manual: Deleting cluster does not resurrect deleted sources through FK side effects.
128. `QA-128` Manual: Deleting vault cascades safely without leaving extension/bridge artifacts.

## Bridge HTTP And MCP

129. `QA-129` Auto: Bridge context requires token when Bridge is enabled.
130. `QA-130` Auto: Bridge disabled rejects even with a previously valid token.
131. `QA-131` Auto: Bridge token rotation invalidates previous token.
132. `QA-132` Auto: Bridge settings prune deleted allowlist IDs.
133. `QA-133` Auto: Bridge redacts raw and extracted text when permission is disabled.
134. `QA-134` Auto: Bridge requires explicit allowed vault when vault is omitted and allowlist is ambiguous.
135. `QA-135` Auto: Bridge client token permissions are independent from global settings.
136. `QA-136` Auto: JSON-RPC notification `notifications/initialized` returns no response.
137. `QA-137` Auto: MCP unreachable backend maps to app error code `1005`.
138. `QA-138` Auto: MCP HTTP denial for cluster-not-allowed maps to app error code `1004`.
139. `QA-139` Probe: Error-code registry matches product-spec numeric assignments exactly.
140. `QA-140` Manual: `list_clusters` no-vault state is distinguishable from empty vault in MCP clients.

## Extension Capture

141. `QA-141` Auto: Extension status without token reports `ok = false`.
142. `QA-142` Auto: Extension capture creates source and capture record when token and vault are valid.
143. `QA-143` Auto: Extension client vault allowlist blocks unauthorized capture.
144. `QA-144` Auto: Revoked extension client no longer captures.
145. `QA-145` Manual: Extension token rotation flow is explicitly supported or rejected by design.
146. `QA-146` Manual: Extension capture of giant payload is bounded safely.
147. `QA-147` Manual: Extension capture URL field redaction is consistent in diagnostics.
148. `QA-148` Manual: Extension capture with deleted vault fails cleanly.
149. `QA-149` Manual: Disabled extension client remains listed as disabled, not silently removed.
150. `QA-150` Manual: Extension capture with unsupported source type is normalized safely.

## Token Storage And Local Auth

151. `QA-151` Auto: Token store set/get/clear roundtrip works.
152. `QA-152` Auto: Token store rejects short persisted values.
153. `QA-153` Auto: `getOrCreateToken` is stable across repeated calls.
154. `QA-154` Auto: Only `token-store.cjs` references `backend-token` path directly in Electron shell code.
155. `QA-155` Probe: Stored backend token is encrypted or protected at rest according to product requirement.
156. `QA-156` Auto: Allowed dev CORS origin receives `Access-Control-Allow-Origin`.
157. `QA-157` Auto: Unknown origin does not receive CORS allow header.
158. `QA-158` Probe: Packaged renderer dynamic loopback origin is accepted by CORS policy.
159. `QA-159` Manual: Packaged app always injects `CML_API_TOKEN` into backend environment.
160. `QA-160` Manual: Dev backend without token leaves auth middleware inactive only in dev scenario.
161. `QA-161` Manual: Token never appears in logs, diagnostics, or renderer console.
162. `QA-162` Manual: Token clear/recreate path survives app relaunch.

## Diagnostics And Redaction

163. `QA-163` Auto: Diagnostic bundle is created with manifest and summary files.
164. `QA-164` Auto: Diagnostic bundle excludes raw secret source text.
165. `QA-165` Auto: Bundle includes app/backend/schema/version metadata fields.
166. `QA-166` Auto: Local Windows-style paths are redacted in bundled logs.
167. `QA-167` Manual: Bundle rotation includes only recent logs under explicit size limit.
168. `QA-168` Manual: User home, username, and vault path are consistently anonymized.
169. `QA-169` Manual: Missing candidate log files do not break bundle creation.
170. `QA-170` Manual: Oversized logs are tail-trimmed, not fully embedded.
171. `QA-171` Manual: Bridge or API tokens in alternate log formats are redacted.
172. `QA-172` Manual: Diagnostic bundle path itself lands under vault data diagnostics directory.

## OCR Pipeline

173. `QA-173` Auto: OCR runtime status reports missing Tesseract explicitly.
174. `QA-174` Auto: OCRmyPDF path is preferred over Tesseract render fallback.
175. `QA-175` Manual: Scanned PDF with OCRmyPDF installed yields per-page text.
176. `QA-176` Manual: Scanned PDF without OCRmyPDF but with Tesseract still yields per-page text.
177. `QA-177` Manual: Image ingest without OCR runtime stores metadata note.
178. `QA-178` Manual: Corrupt image OCR failure leaves explicit extraction-failed status without crash.
179. `QA-179` Manual: OCR job appears in queue/status UI during processing.
180. `QA-180` Manual: OCR component availability details include Ghostscript and qpdf separately.

## Expert Lifecycle And Cluster Management

181. `QA-181` Auto: Hardware status includes training gate fields.
182. `QA-182` Auto: Expert retrain queues adapter job or returns hardware-unsupported.
183. `QA-183` Manual: Non-AVX2 hardware is blocked before fake training begins.
184. `QA-184` Manual: Ambiguous AVX2 detection stays `unknown` with warning path.
185. `QA-185` Manual: Unimplemented training never reports completed expert artifact as real success.
186. `QA-186` Manual: User-facing strings avoid overstating local expert capability.
187. `QA-187` Manual: Source move from cluster A to B marks both clusters refresh-needed.
188. `QA-188` Manual: Cluster merge moves sources and invalidates old cluster lifecycle state.
189. `QA-189` Manual: Empty cluster becomes archived or explicitly empty.
190. `QA-190` Manual: Concurrent suggestion acceptance on same source resolves with clean conflict semantics.

## Desktop Shell, Packaging, And Paths

191. `QA-191` Manual: Second instance same vault restores existing window and exits.
192. `QA-192` Manual: Second instance different vault shows warning and exits.
193. `QA-193` Probe: Packaged renderer uses actual backend port instead of assuming `7343`.
194. `QA-194` Manual: Packaged app still works when `7343` is occupied.
195. `QA-195` Manual: Vault picker accepts Unicode, spaces, and long paths.
196. `QA-196` Manual: Active vault config writes expected path and `.vault` directory.
197. `QA-197` Manual: User data truly lands inside selected vault `.vault` directory.
198. `QA-198` Manual: Packaged cold start reaches ready within target time and visible progress.
199. `QA-199` Manual: Simultaneous ingest and chat does not leak half-indexed content into answers.
200. `QA-200` Manual: Large-vault map, search, and timeline remain responsive under scale.
