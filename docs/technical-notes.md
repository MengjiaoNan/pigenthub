# Technical notes

[Back to the README](../README.md) · [Screenshot notes](screenshots/README.md)

This document describes the local adapters, hook integration, and implementation details behind PigentHub.

## Project layout

| File | Responsibility |
| --- | --- |
| `launcher.py`, `board_runtime.py` | Environment setup, background server lifecycle, port selection, and project identity |
| `platform_support.py` | Platform-specific paths, CLI resolution, and process options |
| `conversation_store.py` | Read-only transcript adapters, parsing cache, and unified conversation data |
| `server.py` | FastAPI routes, local request checks, and static assets |
| `workbench.html`, `assets/workbench.css`, `assets/workbench.js` | Dashboard, project navigation, conversation history, and interaction controls |
| `summaries.py` | Claude CLI integration, summary queue, and persistent cache |
| `native_links.py` | Desktop conversation links and session ID validation |
| `live_events.py`, `observer_hook.py` | Hook event storage and status correlation |
| `approval_hook.py` | User responses and queued-message handoff |
| `install_observers.py` | Hook configuration previews, merging, and backups |
| `board_settings.py` | Dashboard preferences, approval wait times, and online status |
| `tests/` | Automated tests using isolated records and test providers |

`main.py`, `render_page.py`, `list_sessions.py`, `demo_agent.py`, `claude_probe.py`, and `claude_agent.py` originate from earlier experiments. The current dashboard starts through `launcher.py` and `server.py`.

## Configuration

Set environment variables before starting PigentHub. Hook installers and transcript readers use the same agent home directories.

| Variable | Purpose |
| --- | --- |
| `CODEX_HOME` | Codex data/configuration directory; defaults to `~/.codex` |
| `CLAUDE_CONFIG_DIR` | Claude Code data/configuration directory; defaults to `~/.claude` |
| `BOARD_PYTHON` | Full path to a Python 3.10+ interpreter for the launch scripts |
| `BOARD_CODEX_CLI` | Custom Codex CLI executable path |
| `BOARD_CLAUDE_CLI` | Custom Claude Code CLI executable path |
| `BOARD_SUMMARY_MODEL` | Summary model; defaults to the Claude Code `haiku` alias |

Codex transcripts are scanned from the Codex home directory's `sessions` folder, with a separate title index. Claude Code records are read from the Claude configuration directory's `projects` folder. Parsing is cached by file size and modification time; incomplete JSON lines are skipped while files are being written.

On Windows, virtual environments use `.venv/Scripts/python.exe`; macOS and Linux use `.venv/bin/python`. Windows npm CLI shims are resolved to their Node entry point rather than invoked through `cmd.exe` with message content.

## Background lifecycle

The launcher checks the identity of an existing server before reusing it. It uses ports 8001 through 8010 and records the instance under `.board/server.json`. Stop commands validate the matching server record before requesting shutdown. The server closes its summary service during normal shutdown.

To run the server in a foreground terminal for debugging:

```bash
# macOS / Linux
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8001
```

```powershell
# Windows PowerShell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8001
```

Keep that terminal open. This starts the server directly and does not use the launcher's background process management.

## Conversation history and navigation

The conversation view initially includes up to 200 messages. Load earlier messages requests the complete local text history. Recent workflow events are bounded separately.

Key moments indexes the loaded prompts, replies, and Markdown headings in chronological order. Filtering and keyword search operate on that local outline. Loading earlier messages expands the outline; no model determines the significance of a moment.

Card expansion is preserved across the three-second refresh cycle. Opening a summary or a desktop link is a separate action from expanding the card.

## Status interpretation

- Codex adapters use turn events such as `task_started`, `task_complete`, and `turn_aborted`, correlated with the current turn ID.
- Claude Code adapters use assistant tool calls and completion evidence such as `stop_reason: end_turn`. A new user message clears a previous completed-turn state.
- A Codex turn with an explicit start remains Running until completion or interruption is recorded. After 90 seconds without activity, its description says it is waiting for an update. A quiet log does not imply completion. Claude activity inferred from transcript messages becomes unconfirmed after 90 seconds without further evidence.
- Supported hook requests add approval or question signals. New input, completion, interruption, or corresponding tool results clear relevant waiting states. Stale requests become unconfirmed after 30 minutes without further evidence.
- An approval may remain visible while the approved tool is still running, until its completion event arrives. Delayed notifications can also affect timing.
- Summary generation never determines whether an agent turn is complete.

### Context compaction

Codex `PreCompact` and `PostCompact` hooks passively record compaction events. While compaction is active, the board displays Compacting context under Running. Subsequent work, completion, interruption, or session end clears the phase. After 30 minutes without further evidence, the compaction state becomes unconfirmed. Compaction and session resume preserve unresolved approvals, which take precedence and remain under Needs you, including after the answer timer hands the request back to the agent app. A matching tool result, new prompt, completion, interruption, or session end clears the approval; requests older than 30 minutes become unconfirmed.

Compacted transcript records update progress without exposing internal compaction summaries in the conversation view. Newer activity or completion evidence takes precedence over older hook events.

## Hooks and user responses

The installer can target `codex`, `claude`, or `both`. A preview writes merged JSON files into `.board/`. Installation updates the selected user configuration files:

- Codex: `hooks.json` under the Codex home directory.
- Claude Code: `settings.json` under the Claude configuration directory.

Existing configuration is backed up under `.board/hook-backups/`. The installer replaces PigentHub's own handlers while preserving other hooks and settings. It does not set hook trust or change permission rules.

Passive observer hooks record events without producing approval decisions. Approval handlers wait for a user response while the board is online; if the board is unavailable, an error occurs, or the wait expires, they produce no response and leave handling to the agent. Some agent-specific events only provide notifications rather than an answerable request.

Codex approval hooks run before the native approval flow. While a synchronous hook waits for a board answer, the app's native prompt is not simultaneously available. Concurrent responses and immediate dismissal in both interfaces would require a shared live approval channel and request-resolution events. The current hook integration has neither; app answers are inferred from subsequent tool or turn events rather than an immediate approval-resolution acknowledgement.

On Windows, Claude handlers invoke Python directly. Codex handlers use an encoded PowerShell command to forward UTF-8 event data. On macOS and Linux, handlers use POSIX command quoting.

## Message delivery

Idle conversations are resumed through the relevant CLI using their existing session ID. The CLI updates its own local records, which the dashboard then reads.

For Running or Needs you conversations, the server requires configured delivery hooks before accepting a queued message. The same session's next supported `Stop` or `UserPromptSubmit` hook collects the outbox. Configuration alone does not prove that an already-open session has loaded or trusted the hook.

A collected message is marked as handed to a hook. This does not acknowledge that the agent has processed it or that the desktop window has displayed a new chat bubble. Hook context can be delivered differently from an ordinary user message. Concurrent continuations in the desktop app and CLI can produce diverging records; use one sending interface at a time.

## Summary generation and caching

The summary service uses an authenticated Claude Code CLI. It prefers an explicit `BOARD_CLAUDE_CLI`, then a local native installation or an executable on PATH. The default prompt requests a short English summary; changing `BOARD_SUMMARY_MODEL` changes the model, not the output language.

Replies longer than 320 characters are eligible for the summary action. Generation is disabled while the conversation is running or waiting for a response. Replies over 100,000 characters are rejected rather than silently truncated.

Only explicit Generate or Retry actions enqueue work. The cache key combines the complete reply, model, and prompt version. Results persist in `.board/summaries.sqlite3`. Requests include a reply fingerprint so the server can reject a request if the selected reply has changed.

A single worker processes summary jobs. Provider errors pause generation until an explicit retry. Browsing, automatic refreshes, and server restarts do not enqueue new summaries.

The CLI runs in a temporary directory with custom skills and tools disabled and session persistence turned off. Reply text is passed through stdin. Original transcripts remain available and are never replaced by summaries.

## Desktop links

The adapters construct `codex://threads/<id>` and `claude://resume?session=<id>` links after validating session IDs. Resolution depends on the installed app and the operating system's protocol registration. When a link cannot open, users can copy the session ID and resume through their agent.

## Local API

The server checks the request Host and requires an `x-pigenthub: 1` header for actions that change state. The launcher binds the service to loopback.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server health and instance identity |
| GET | `/api/conversations` | Board snapshot, settings, and listener state |
| GET | `/api/conversations/{id}` | Conversation details; `?full=true` includes complete local text history |
| GET | `/api/conversations/{id}/progress` | Recent turn events and bounded agent updates |
| GET | `/api/conversations/{id}/workflow` | Workflow details |
| POST | `/api/conversations/{id}/summary` | Request a summary using `reply_key` and optional `retry` |
| POST | `/api/conversations/{id}/messages` | Send or queue a message |
| POST | `/api/conversations/{id}/respond` | Submit an active request response |
| DELETE | `/api/conversations/{id}/outbox/{message_id}` | Cancel a message that is still queued |
| PUT | `/api/focus` | Save focused conversations |
| PUT | `/api/settings` | Update dashboard settings |

## Appearance

Colours are defined as CSS custom properties near the top of `assets/workbench.css`. Common settings include `--bg`, `--paper`, `--surface`, `--brand-pink`, `--primary`, `--primary-hover`, and the `--needs`, `--run`, and `--done` families. `--brand-pink` controls the Hub wordmark and pig snout; the nostrils use the page background. The standalone favicon colours are defined in `assets/pigenthub.svg`.

Edit a value, save the file, and refresh the browser. A server restart is unnecessary. Use a hard refresh if the browser retains an older stylesheet.

## Validation

The unittest suite uses temporary transcript files, simulated events, and fake summary providers. Coverage includes session parsing, turn transitions, stale states, incomplete JSON lines, subagent filtering, title updates, history preservation, summary deduplication and cache persistence, delivery handoff, and desktop link validation.

Launcher tests cover server startup, reuse, shutdown, concurrent startup, port conflicts, instance identity checks, and paths containing Unicode or quotation marks. The repository includes `.github/workflows/board-tests.yml` with macOS, Ubuntu, and Windows jobs for Python 3.10 and 3.14. A configured matrix is not evidence that all platform jobs have passed; check the actual run results.
