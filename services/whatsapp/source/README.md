# WhatsApp MCP Server

[![CI](https://github.com/verygoodplugins/whatsapp-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/verygoodplugins/whatsapp-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Go 1.26+](https://img.shields.io/badge/go-1.26+-00ADD8.svg)](https://go.dev/)

A Model Context Protocol (MCP) server for WhatsApp, enabling Claude to read and send WhatsApp messages.

> Originally created by [Luke Harries](https://github.com/lharries/whatsapp-mcp). Maintained by [Very Good Plugins](https://verygoodplugins.com/?utm_source=github).

<p align="center">
  <a href="https://github.com/user-attachments/assets/9475af1d-2369-4315-9ccc-823dba2c5c32"><strong>Watch the WhatsApp MCP demo video</strong></a>
</p>

<p align="center">
  <sub>Product demo generated with Remotion using simulated data.</sub>
</p>

## Features

- **Message Management**: Search and read personal WhatsApp messages (text, images, videos, documents, audio)
- **Contact Search**: Search contacts by name or phone number with `sender_display` format ("Name (phone)")
- **Send Messages**: Send text messages to individuals or groups
- **Read Receipts**: Explicitly mark selected messages as read across linked devices
- **Media Support**: Send and download images, videos, documents, and voice messages
- **Call History**: Capture incoming voice/video calls into a local SQLite table (live, 1:1 and group)
- **Webhook Integration**: Forward incoming messages to external services
- **Local Storage**: All messages stored locally in SQLite - only sent to Claude when you allow it

## Installation

> **This VPS checkout:** the instructions below describe the upstream
> standalone project, not an authorized production install or re-pair. Do not
> run them against the existing accounts, restart a bridge, change grants, or
> start a second writer without separate Owner approval. See the
> [repository installation guide](../../../docs/INSTALLATION.md) and root
> `AGENTS.md` for the local boundaries.
>
> The Python wheel includes the broker, lifecycle, native-reader and service
> modules as well as `main.py`. Installing that wheel does **not** install or
> configure the separate Go bridge, grant access, or pair an account. The
> security-updated `cryptography` dependency has no prebuilt Intel macOS wheel;
> that platform may require a Rust/OpenSSL source-build toolchain.

### Prerequisites

- Go 1.26+
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Claude Desktop or Cursor
- FFmpeg (optional, for voice message conversion)

### Quick Start

1. **Clone the repository**

   ```bash
   git clone https://github.com/verygoodplugins/whatsapp-mcp.git
   cd whatsapp-mcp
   ```

2. **Start the WhatsApp bridge**

   ```bash
   cd whatsapp-bridge
   go run .
   ```

   On first start, the bridge prints and stores a local REST API token at
   `whatsapp-bridge/store/.bridge-token`. Scan the QR code with WhatsApp on
   your phone to authenticate.

3. **Configure Claude Desktop**

   Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "whatsapp": {
         "command": "uv",
         "args": [
           "--directory",
           "/path/to/whatsapp-mcp/whatsapp-mcp-server",
           "run",
           "main.py"
         ]
       }
     }
   }
   ```

   Replace `/path/to/whatsapp-mcp` with your actual path.

4. **Restart Claude Desktop**

### Updating

Pull the latest changes, then refresh whichever components moved:

```bash
git pull
```

| You changed                                                              | What to do                                                                                                                                            |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Bridge code** (`whatsapp-bridge/*.go`) and you run `go run .`          | Nothing — `go run` recompiles each launch. Just restart the bridge.                                                                                   |
| **Bridge code** and you run a built binary                               | `cd whatsapp-bridge && go build -o whatsapp-bridge && ./whatsapp-bridge`                                                                              |
| **MCP server** (`whatsapp-mcp-server/*.py`, `pyproject.toml`, `uv.lock`) | Restart Claude Desktop / Cursor — `uv` re-resolves from the lockfile on next launch. Force a sync with `cd whatsapp-mcp-server && uv sync` if needed. |

Updates do **not** require re-pairing or deleting `whatsapp.db` — your session and message history are preserved. Re-pairing is only needed when explicitly requesting full history (see [Requesting full history](#requesting-full-history)).

For `v0.2.1` and later, restart both the bridge and MCP server after updating
so the MCP server can read the bridge token. If the two components do not share
the same checkout, set the same `WHATSAPP_BRIDGE_TOKEN` value in both
environments.

### Cursor IDE Configuration

Add to your Cursor MCP settings (`~/.cursor/mcp.json`):

```json
{
  "mcp": {
    "servers": {
      "whatsapp": {
        "command": "uv",
        "args": [
          "--directory",
          "/path/to/whatsapp-mcp/whatsapp-mcp-server",
          "run",
          "main.py"
        ]
      }
    }
  }
}
```

## Tools

Messages include `sender_display` showing "Name (phone)" format for easy identification by agents.

### Contact Operations

#### `search_contacts`

Search contacts by name or phone number.

**Parameters:**

- `query` (required): Name or phone number to search

**Natural Language Examples:**

- "Find contacts named John"
- "Search for phone number 555-1234"
- "Who has the phone number starting with +1?"

#### `get_contact`

Resolve a WhatsApp contact name from a phone number, LID, or full JID.

**Parameters:**

- `identifier` (required): Phone number, LID, or full JID (aliases: `phone_number`, `phone`)
  - Examples: `12025551234`, `184125298348272`, `12025551234@s.whatsapp.net`, `184125298348272@lid`

**Natural Language Examples:**

- "What's the name for phone number 5551234567?"
- "Look up who owns this number"
- "Who is 184125298348272@lid?"

### Message Operations

#### `list_messages`

Get messages with filters, date ranges, and sorting.

Each message includes `sender_push_name`, read from the matching
`whatsmeow_contacts.push_name` field when available (otherwise `null`). This is
separate from `sender_name`, which is a resolved display label, and
`chat_name`, which labels the conversation.

**Parameters:**

- `chat_jid` (optional): Filter by specific chat JID
- `limit` (optional): Number of messages (default 50, max 500)
- `before_date` (optional): Messages before this date (YYYY-MM-DD)
- `after_date` (optional): Messages after this date (YYYY-MM-DD)
- `sort_by` (optional): "newest" or "oldest" (default "newest")

**Natural Language Examples:**

- "Show me the last 100 messages from today"
- "Get messages from the family group chat"
- "Find messages from last week"

#### `send_message`

Send a text message to a contact or group, optionally as a quoted reply.

**Parameters:**

- `recipient` (required): Phone number or group JID
- `message` (required): Text content to send
- `quoted_message_id` (optional): ID of the message to reply to. When provided, the sent message appears as a quoted reply in WhatsApp.
- `quoted_sender_jid` (optional): Full JID of the author of the quoted message. Required for group replies so WhatsApp renders the correct attribution header.
- `quoted_content` (optional): Text content of the quoted message, used for the reply preview. Only plain text is supported.
- `mentions` (optional): List of users to @-mention, as phone numbers with country code (e.g. `["12025551234"]`) or JIDs. For each entry the message text must contain a matching `@<number>` token (e.g. `"thanks @12025551234!"`), which recipients' devices render as a highlighted, tappable mention that also notifies the user. Only meaningful in group chats.

Inbound quoted replies are stored automatically. The `quoted_message_id` field in each message returned by `list_messages` indicates which message it is replying to (or `null` for non-replies).

**Natural Language Examples:**

- "Send 'Hello!' to +1234567890"
- "Message the team group saying 'Meeting at 3pm'"
- "Reply to that message saying 'Sounds good'"

#### `mark_messages_read`

Mark one or more messages from the same chat and sender as read. This explicitly
sends WhatsApp read receipts; reading or searching messages never does so
automatically.

**Parameters:**

- `message_ids` (required): IDs of messages from the same chat and sender
- `chat_jid` (required): JID of the chat containing the messages
- `sender_jid` (required for groups): Full JID or bare phone number of the original message sender
- `timestamp` (optional): RFC 3339 read timestamp; defaults to the current time

**Natural Language Examples:**

- "Mark those messages as read"
- "Mark the last three messages from Alice in the team group as read"

#### `send_reaction`

Send (or remove) an emoji reaction to a message.

**Parameters:**

- `recipient` (required): Chat JID the message belongs to (phone JID or group JID)
- `message_id` (required): ID of the message to react to
- `emoji` (required): Reaction emoji (e.g. `"👍"`). Pass an empty string `""` to remove an existing reaction.
- `from_me` (optional, default `false`): Whether the original message was sent by the current user
- `sender_jid` (optional): Full JID of the original message sender — required for group messages when `from_me` is `false` so the correct WhatsApp key is built

Inbound reactions received from others are stored automatically as messages with `media_type = "reaction"`. The `reaction_to_message_id` field in each reaction message indicates which message was reacted to.

When webhook forwarding is enabled, inbound reactions are also posted to `WEBHOOK_URL` as typed events. Reaction removals use an empty `content`/`reactionEmoji` and `reactionRemoved: true`.

```json
{
  "eventType": "reaction",
  "sender": "15551234567",
  "chatJID": "15551234567@s.whatsapp.net",
  "isFromMe": true,
  "content": "👍",
  "messageId": "reaction-stanza-id",
  "mediaType": "reaction",
  "reactionToMessageId": "target-message-id",
  "reactionEmoji": "👍",
  "reactionRemoved": false
}
```

**Natural Language Examples:**

- "React to that message with a thumbs up"
- "Remove my reaction from the last message in the group chat"

#### `send_file`

Send a media file (image, video, document).

Successfully sent attachments retain their download metadata in local history.
Use their message ID and chat JID with `download_media` to retrieve the uploaded
bytes again while WhatsApp still serves the attachment. This also applies to
voice messages sent with `send_audio_message`. It does not backfill metadata for
attachments sent by older bridge versions or prevent WhatsApp media expiry.

**Parameters:**

- `recipient` (required): Phone number or group JID
- `file_path` (required): Path to the file
- `caption` (optional): Caption for the media

The bridge only reads files inside configured media roots. By default this is
`~/.local/share/whatsapp-mcp/outbox`; set `WHATSAPP_MEDIA_ROOTS` to allow
additional absolute directories.

For documents, recipients receive only the filename portion of `file_path`;
parent directories are not exposed.

#### `send_audio_message`

Send a voice message (automatically converts to Opus .ogg format).

**Parameters:**

- `recipient` (required): Phone number or group JID
- `file_path` (required): Path to audio file

Converted audio is sent through the same media-path confinement as
`send_file`.

#### `download_media`

Download media from a received message. Returns the **local file path**, which
only helps a client that can read the filesystem — use `view_media` otherwise.

**Parameters:**

- `message_id` (required): ID of the message with media
- `chat_jid` (required): JID of the chat containing the message

#### `view_media`

View the media of a message as an image, for clients with no filesystem access
(Claude Desktop, a claude.ai chat). Images are returned as image content;
a video returns its first frame as a still. Both are downscaled first so one
photo cannot flood the context. Audio is rejected with a pointer to its
transcript.

Uses FFmpeg when available (already an optional dependency); without it, images
below 4 MB are returned unchanged and anything else reports what is missing.

**Parameters:**

- `message_id` (required): ID of the message with media
- `chat_jid` (required): JID of the chat containing the message
- `max_dimension` (optional): longest edge in pixels, default `1024`

`max_dimension` must be an integer from `1` to `2048`. Invalid values are
rejected before the server downloads or renders any media.

#### `transcribe_audio`

Transcribe a voice note with whisper.cpp (the default) or an OpenAI-compatible
endpoint and return its text. The transcript is also written into the message's
empty `content` field, so afterwards it is readable through `list_messages`
by any client — including one with no filesystem access — without transcribing
again. whisper.cpp runs entirely on this machine; the HTTP provider sends audio
to the endpoint you configure. Use a loopback URL to keep transcription local.

A stored transcript is returned immediately; a fresh one took about 2 s for a
30-second note with `large-v3-turbo` on an M-series Mac. Transcripts are
prefixed with `[transcript (whisper <model>)]` or
`[transcript (openai_compatible <model>)]` so they cannot be mistaken for
text a human typed, and a real message is never overwritten.

**Requirements:** [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
(`whisper-cli` on `PATH`), FFmpeg, and `WHISPER_MODEL` pointing at a model
file. Optionally `WHISPER_LANGUAGE` (default `auto`).

To reuse an existing service, such as a local Parakeet server, configure:

```env
WHATSAPP_TRANSCRIPTION_PROVIDER=openai_compatible
WHATSAPP_TRANSCRIPTION_URL=http://127.0.0.1:8178/v1/audio/transcriptions
WHATSAPP_TRANSCRIPTION_MODEL=parakeet
```

`WHATSAPP_TRANSCRIPTION_PROVIDER` defaults to `whisper_cpp`. For
`openai_compatible`, URL and MODEL are required. URL is the **full endpoint**;
no path is appended. Optional `WHATSAPP_TRANSCRIPTION_API_KEY` supplies a bearer
token, and `WHATSAPP_TRANSCRIPTION_LANGUAGE` supplies a language code (`auto`
by default, omitted from the HTTP request). This provider uploads the original
audio using multipart `file`, `model`, and `response_format=json`; the server
must decode it (including WhatsApp Opus/OGG) and return `{"text": "..."}`.
It requires no local whisper.cpp, model file, or FFmpeg. Remote URLs send audio
off the machine; redirects, environment proxies, `.netrc` credentials, and
automatic provider fallbacks are disabled.
HTTP connections time out after 10 seconds, HTTP reads and Whisper inference
after 300 seconds, and local FFmpeg decoding after 60 seconds.

Stored transcripts are reused across provider changes unless `force=true`.
Cache reads and writes use both message ID and chat JID.

**Parameters:**

- `message_id` (required): ID of the message with the voice note
- `chat_jid` (required): JID of the chat containing the message
- `force` (optional): transcribe again even when a transcript is stored

### Chat Operations

All chat tools (`list_chats`, `get_chat`, `get_direct_chat_by_contact`,
`get_contact_chats`) return the same chat shape:

```jsonc
{
  "jid": "1234567890@s.whatsapp.net",
  "name": "Alice",
  "is_group": false,
  "last_message_time": "2024-01-15T10:30:00+00:00",
  "last_message": "hello world",       // null when include_last_message=false
  "last_sender": "1234567890",         // null when include_last_message=false
  "last_is_from_me": false,
  "last_read_time": "2024-01-15T09:00:00+00:00", // how far the chat is read
  "unread": true                       // last message is inbound and unread
}
```

#### Read state (`last_read_time` / `unread`)

`last_read_time` is the bridge's read marker for the chat, fed by read
receipts from your own devices and backfilled from history sync. `unread` is
derived from it: true when the chat's last message is inbound and newer than
the marker. This distinguishes a genuinely unread chat from one whose last
message merely happens to be inbound but was already read on the phone.

Caveats:

- **The marker only moves forward.** Marking an already-read chat as *unread*
  again on the phone is not reflected.
- **No marker means no read was ever reported** — for a chat with an inbound
  last message, `unread` then falls back to the old heuristic and reports
  true. Stores written by a bridge older than the `chats.last_read_time`
  column report `last_read_time: null` and behave the same way.
- **`unread` is a chat-level flag, not an unread count.** WhatsApp's unread
  counter is not persisted.

#### `list_chats`

List all chats with metadata.

**Parameters:**

- `limit` (optional): Number of chats (default 50, max 200)

#### `get_chat`

Get specific chat metadata by JID.

**Parameters:**

- `jid` (required): Chat JID

#### `get_direct_chat_by_contact`

Find a direct message chat with a contact.

**Parameters:**

- `phone` (required): Phone number of the contact

#### `get_contact_chats`

List all chats involving a specific contact.

**Parameters:**

- `phone` (required): Phone number of the contact

#### `get_last_interaction`

Get the last message exchanged with a contact.

**Parameters:**

- `phone` (required): Phone number of the contact

#### `get_message_context`

Get messages around a specific message for context.

**Parameters:**

- `message_id` (required): ID of the target message
- `chat_jid` (required): JID of the chat
- `before` (optional): Number of messages before (default 5)
- `after` (optional): Number of messages after (default 5)

## Configuration

Copy `.env.example` to `.env` and configure as needed:

| Variable               | Default                                  | Description                                  |
| ---------------------- | ---------------------------------------- | -------------------------------------------- |
| `WHATSAPP_BRIDGE_PORT` | `8080`                                   | Port for Go bridge REST API                  |
| `WEBHOOK_URL`          | `http://localhost:8769/whatsapp/webhook` | Webhook for incoming messages                |
| `WEBHOOK_ENABLED`      | `true`                                   | Set to `false` to disable outbound webhooks  |
| `WHATSAPP_AUTO_DOWNLOAD_MEDIA` | `true` | Automatically download incoming media, including webhook image bytes. `false` keeps webhook metadata/text without `mediaBase64` and leaves downloads to `/api/download` (`download_media`); delayed downloads may fail after media expires. Status messages are stored but never auto-downloaded or forwarded |
| `FORWARD_SELF`         | `true`                                   | Forward messages sent by self                |
| `WHATSAPP_DB_PATH`     | `../whatsapp-bridge/store/messages.db`   | Path to SQLite database                      |
| `WHATSMEOW_DB_PATH`    | `../whatsapp-bridge/store/whatsapp.db`   | whatsmeow DB used for LID ↔ phone resolution |
| `WHATSAPP_API_URL`     | `http://localhost:8080/api`              | Go bridge REST API URL                       |
| `WHATSAPP_BRIDGE_TOKEN` | generated next to `WHATSMEOW_DB_PATH` as `.bridge-token` | Bearer token for bridge REST calls; also signed onto outbound webhook POSTs |
| `WHATSAPP_MEDIA_ROOTS` | `~/.local/share/whatsapp-mcp/outbox`     | Path-list of directories allowed for outbound media files |
| `WHATSAPP_DEVICE_NAME` | `whatsmeow` (whatsmeow default)          | Label shown for this connection under WhatsApp > Linked Devices. Set to a recognisable name. Applies at pair time only (re-pair to change) |
| `WHATSAPP_MCP_TRANSPORT` | `stdio`                                | MCP transport to serve clients: `stdio`, `http`, or `sse` |
| `WHATSAPP_MCP_HOST`    | `127.0.0.1`                              | Bind address for the `http`/`sse` transports |
| `WHATSAPP_MCP_PORT`    | `8000`                                   | Port for the `http`/`sse` transports |
| `WHATSAPP_PARENT_WATCHDOG_S` | `30`                              | Stdio parent-liveness poll interval (seconds); exits on parent reparent only |

### MCP transport (stdio vs http/sse)

By default the server speaks MCP over **stdio**, which is what local clients
like Claude Desktop and Cursor launch. To serve the server over the network
instead, set `WHATSAPP_MCP_TRANSPORT`:

```bash
# Streamable HTTP (current spec transport for remote MCP), endpoint at /mcp
WHATSAPP_MCP_TRANSPORT=http WHATSAPP_MCP_PORT=8000 uv run main.py

# Legacy Server-Sent Events transport (deprecated in the MCP spec), endpoint at /sse
WHATSAPP_MCP_TRANSPORT=sse uv run main.py
```

`http` is an alias for the spec's `streamable-http` transport and is the
recommended choice for remote connections; `sse` is kept for older clients.

> **Security:** `WHATSAPP_MCP_HOST` defaults to `127.0.0.1`, so the HTTP/SSE
> server is reachable only from the local machine. The server has no built-in
> authentication, and the underlying bridge can read and send WhatsApp messages
> on your account. Only bind to a non-loopback address (e.g. `0.0.0.0`) if you
> place an authenticating reverse proxy or tunnel in front of it.

### Bridge authentication and media paths

The bridge requires bearer-token authentication for every `/api/*` request and
accepts only exact loopback Host headers for its configured port. This protects
the local REST API from other local processes and browser DNS-rebinding attacks.

On first start, the bridge generates a 256-bit token, writes it to
`.bridge-token` in the active bridge store directory with owner-only
permissions, and prints a setup banner. The MCP server reads
`WHATSAPP_BRIDGE_TOKEN` first, then falls back to `.bridge-token` in the same
directory as `WHATSMEOW_DB_PATH`. For split deployments, containers, or process
managers that do not share the store directory, set the same
`WHATSAPP_BRIDGE_TOKEN` value for both the bridge and MCP server.

The bridge also signs its **outbound** webhook POSTs (to `WEBHOOK_URL`) with this
same token, sent as an `X-Bridge-Token: <token>` header — a dedicated header
rather than `Authorization`, so it never collides with a receiver's own
Authorization-based auth (e.g. HTTP Basic auth embedded in `WEBHOOK_URL` as
`http://user:pass@host/...`, which `net/http` applies automatically as long as
the bridge doesn't set its own `Authorization` header). The header is attached only when a token is configured **and** `WEBHOOK_URL` was
explicitly set — never to the built-in local default. The bridge token also
authorizes `/api/*` calls like sending messages, and nothing has vetted the
implicit default address, so it must never be handed to whatever process
happens to be listening there. Upgrades that predate the token rollout, or
that never set `WEBHOOK_URL`, keep working unchanged. The webhook client also
never follows redirects, so a misconfigured or malicious endpoint can't
redirect the bridge into leaking the token to a different host. If your
webhook receiver enforces the token, set its copy to this exact value: e.g.
the AutoHub hub's `WHATSAPP_BRIDGE_TOKEN` must equal this bridge's token (from
`.bridge-token` or its own env) — the hub accepts it via `X-Bridge-Token` or
`Authorization: Bearer`. The bridge always sends the token it has; the hub
rejects unauthenticated forwards only once its `WHATSAPP_BRIDGE_TOKEN` is set
to the matching value.

Outbound `media_path` values are confined to `WHATSAPP_MEDIA_ROOTS`. The default
outbox is `~/.local/share/whatsapp-mcp/outbox`, created on bridge startup. Move
files there before calling `send_file` or `send_audio_message`, or set
`WHATSAPP_MEDIA_ROOTS` to a colon-separated list of absolute directories.

### Where runtime data is stored

The bridge keeps its runtime state in `store/`, resolved **relative to its
working directory**. `WHATSAPP_DB_PATH` and `WHATSMEOW_DB_PATH` configure the
MCP server's reads; they do not change the bridge's store location. That
store contains:

| Path | Contents |
| --- | --- |
| `whatsapp.db` | whatsmeow session state, including linked-device credentials |
| `messages.db` | locally synced chat and message history |
| `<chat_jid>/` | downloaded images, voice notes, documents, and other media |
| `.bridge-token` | the generated REST API bearer token, unless supplied through the environment |

The application does not encrypt these files at rest. Anyone who can read
`whatsapp.db` can obtain the linked-device credentials. Moving the store does
not automatically tighten permissions on existing files; check the destination's
access permissions as part of the move. An encrypted volume adds protection
when the machine or a backup is lost.

> **Cloud-synced folders:** a checkout inside Google Drive, Dropbox, iCloud
> Drive, or OneDrive puts the default store within that service's sync scope.
> Keep the checkout or its runtime store outside synced folders. Relocating
> prevents future sync of that store; it does not remove copies or version
> history already uploaded to a provider.

#### Relocate an existing installation

1. **Stop the bridge and every MCP server before copying or moving any files.**
   Quit clients that launch the stdio server (such as Claude Desktop or Cursor),
   stop any standalone HTTP/SSE MCP server, and disable automatic restarts while
   migrating. The macOS jobs only manage the bridge and its monitor, so stopping
   them does not stop MCP clients. If installed, unload both jobs:

   ```bash
   launchctl bootout "gui/$(id -u)/com.whatsapp-mcp.bridge-monitor"
   launchctl bootout "gui/$(id -u)/com.whatsapp-mcp.bridge"
   ```

   For a manually started bridge, stop it in its terminal. Confirm all bridge
   and MCP server processes have exited. Never copy live SQLite databases.

2. Build the binary and move the **entire existing store**, including hidden
   files and any SQLite `-wal`, `-shm`, or journal files, to an unsynced directory.
   Replace the checkout path below, and use the same terminal for later examples.
   If you already run the bridge from another working directory, use that
   directory's `store/` as the source instead.

   ```bash
   repo_dir="/absolute/path/to/whatsapp-mcp"
   runtime_dir="$HOME/.local/share/whatsapp-mcp/runtime"
   (
     set -eu
     cd "$repo_dir/whatsapp-bridge"
     go build -o whatsapp-bridge .
     mkdir -p "$runtime_dir"
     chmod 700 "$runtime_dir"
     if [ -e "$runtime_dir/store" ] || [ -L "$runtime_dir/store" ]; then
       echo "Destination store already exists; stop and inspect it before migrating." >&2
       exit 1
     fi
     mv "$repo_dir/whatsapp-bridge/store" "$runtime_dir/store"
   )
   ```

   Continue only if the move succeeds. Do not merge two stores or start with an
   empty store to relocate an existing session: that creates a new session and
   loses access to the existing local history.

3. In **every MCP client or server configuration**, set both database paths to
   the moved files, using absolute paths (JSON does not expand `$HOME` or `~`):

   ```json
   "env": {
     "WHATSAPP_DB_PATH": "/Users/you/.local/share/whatsapp-mcp/runtime/store/messages.db",
     "WHATSMEOW_DB_PATH": "/Users/you/.local/share/whatsapp-mcp/runtime/store/whatsapp.db"
   }
   ```

   The MCP server reads `.bridge-token` beside `WHATSMEOW_DB_PATH` when
   `WHATSAPP_BRIDGE_TOKEN` is unset. An explicit token takes precedence: preserve
   the same value in the bridge, MCP clients, and any authenticated webhook
   receiver. Keep token values private.

4. Choose how to restart the bridge, then restart the MCP servers and clients
   with their updated configuration:

   **Manual:** launch the built binary from the new runtime directory:

   ```bash
   cd "$runtime_dir"
   "$repo_dir/whatsapp-bridge/whatsapp-bridge"
   ```

   **macOS launchd:** before reloading either job, edit
   `~/Library/Application Support/whatsapp-mcp/launchd.env` to set
   `WHATSAPP_BRIDGE_DIR` to the absolute runtime directory. Keep
   `WHATSAPP_BRIDGE_BINARY` pointing to the built binary in the checkout.
   The runner explicitly executes `cd "$WHATSAPP_BRIDGE_DIR"`; changing only
   the plist's `WorkingDirectory` does not relocate the store. Update that
   plist value too so both directory settings agree:

   ```bash
   /usr/libexec/PlistBuddy -c "Set :WorkingDirectory $runtime_dir" \
     "$HOME/Library/LaunchAgents/com.whatsapp-mcp.bridge.plist"
   ```

   Recent installers also capture `WHATSAPP_BRIDGE_TOKEN` in `launchd.env`,
   which both the runner and monitor source. For a generated file token, ensure
   that cached value matches the moved `store/.bridge-token`; update a stale
   cached value privately before restarting. For an explicitly configured
   token, retain the same override in all consumers. Changing
   `WHATSAPP_BRIDGE_DIR` alone does not update the cached token. Keep
   `launchd.env` owner-readable/writable only (`chmod 600`).

   ```bash
   launchctl bootstrap "gui/$(id -u)" \
     "$HOME/Library/LaunchAgents/com.whatsapp-mcp.bridge.plist"
   launchctl bootstrap "gui/$(id -u)" \
     "$HOME/Library/LaunchAgents/com.whatsapp-mcp.bridge-monitor.plist"
   ```

   Check that the bridge reconnects with the existing session and that the MCP
   client can read known history. An unexpected QR pairing prompt or empty
   history is a reason to stop and recheck paths before proceeding.

**Installer caveat:** rerunning `scripts/install-launchd-macos.sh` rewrites
`launchd.env` and both plists, restores the checkout's bridge directory, and
starts the jobs immediately. It does not preserve this custom runtime location.
After a reinstall, stop both jobs again and reapply the directory and token
settings above before restarting them. Review any newly created checkout store;
do not replace the relocated store with it.

**Fresh manual installation:** only when there is no session or history to
preserve, omit the `mv` step, create the runtime directory, and launch the built
binary there. Pair the new device, then point the MCP server at the new databases
and token as above. This is separate from migrating an existing installation.

### Run automatically on macOS

macOS users can install optional per-user `launchd` jobs that start the Go
bridge at login and monitor it every 60 seconds for API health, disconnects, and
QR relink signals. The installer does not require `sudo` and does not install or
start the MCP server.

```bash
scripts/install-launchd-macos.sh
```

The installer builds `whatsapp-bridge/whatsapp-bridge` with `go build` when Go is
available, writes generated support files to
`~/Library/Application Support/whatsapp-mcp/`, writes LaunchAgents to
`~/Library/LaunchAgents/`, and writes logs to `~/Library/Logs/whatsapp-mcp/`.
It safely reloads only these labels:

- `com.whatsapp-mcp.bridge`
- `com.whatsapp-mcp.bridge-monitor`

To customize the launchd environment, export values before running the installer.
Re-run the installer after changing them.

```bash
export WHATSAPP_BRIDGE_PORT=8080
export WEBHOOK_URL=http://localhost:8769/whatsapp/webhook
export FORWARD_SELF=false
export WHATSAPP_MEDIA_ROOTS="$HOME/.local/share/whatsapp-mcp/outbox"
scripts/install-launchd-macos.sh
```

Verify the jobs and inspect logs:

```bash
launchctl print gui/$(id -u)/com.whatsapp-mcp.bridge
launchctl print gui/$(id -u)/com.whatsapp-mcp.bridge-monitor
tail -n 100 ~/Library/Logs/whatsapp-mcp/bridge.err.log
tail -n 100 ~/Library/Logs/whatsapp-mcp/monitor.err.log
```

The monitor sends a macOS notification once per failure type until recovery. It
alerts when the bridge LaunchAgent is unloaded, the token is missing, the health
endpoint is unreachable, WhatsApp is disconnected, or recent logs indicate that
QR relinking is needed.

If `store/.bridge-token` lives inside a macOS TCC-protected location (for example
`~/Documents` or `~/Desktop`), the sandboxed monitor can be denied read access to
it. The installer avoids this by copying the resolved token into the mode-`600`
`launchd.env` so the monitor reads it from the environment; if you ever see the
monitor exit without alerting, re-run the installer, or set `WHATSAPP_BRIDGE_TOKEN`
explicitly before running it.

Uninstall the generated LaunchAgents and support files with:

```bash
scripts/uninstall-launchd-macos.sh
```

Uninstall preserves `whatsapp-bridge/store/`, including WhatsApp session DBs,
message DBs, media, and `.bridge-token`. Logs are left in
`~/Library/Logs/whatsapp-mcp/` for manual cleanup.

### CLI flags (Go bridge)

| Flag                  | Default | Description                                                                                                                                                                                                                                                       |
| --------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--full-history-pair` | `false` | Request full history at pair time. Only takes effect on a fresh pair (no existing `whatsapp.db`); no-op for already-paired sessions. The phone ultimately decides the actual history window sent — see [Requesting full history](#requesting-full-history) below. |

### Requesting full history

whatsmeow's default pairing asks for "recent sync" — roughly the last 3 months, with the exact window decided by the phone. If you want to pull more history at pair time:

```bash
# Stop the bridge
launchctl bootout gui/$UID/com.whatsapp-mcp.bridge    # or however you manage it

# Back up, then remove the auth session (keeps messages.db intact)
cp whatsapp-bridge/store/whatsapp.db{,.bak}
rm whatsapp-bridge/store/whatsapp.db

# Re-pair with the flag
cd whatsapp-bridge
./whatsapp-bridge --full-history-pair
# Scan the QR with WhatsApp → Settings → Linked Devices → Link a Device
# Wait for "History sync complete" in the logs (can take 10-30 minutes)
# Ctrl+C when sync has quiesced, then restart under your normal process manager
```

Caveats:

- **The phone decides the actual cap.** The flag requests up to 10 years / 100 GB, but WhatsApp's iOS primary device enforces its own retention policy. iPad companion is documented at ~1 year max; other linked devices appear to follow similar logic.
- **Only effective on a fresh pair.** With `whatsapp.db` already present, no new pair handshake fires and the flag is a no-op.
- **Messages the phone has deleted are not recoverable** — auto-expire, low-storage cleanup, and manual delete all leave no trace for the phone to share.

### Requesting history for a single chat (on-demand)

`--full-history-pair` only applies to a fresh pair, so recovering a gap in one
chat otherwise means deleting `whatsapp.db` and re-syncing everything. To ask
the phone for older messages in a single chat *without* re-pairing:

```bash
curl -X POST http://127.0.0.1:8080/api/history \
  -H "Authorization: Bearer $(cat whatsapp-bridge/store/.bridge-token)" \
  -H "Content-Type: application/json" \
  -d '{"chat_jid": "1234567890@s.whatsapp.net", "count": 50}'
```

The request is anchored on the **oldest message already stored** for that chat,
so the phone returns messages from before it. Call it repeatedly to page
further back. Results arrive asynchronously through the normal history-sync
handler and land in `messages.db` — typically within a few seconds.

| Field | Required | Description |
| --------- | -------- | ------------------------------------------------------ |
| `chat_jid` | yes | Chat to backfill (`...@s.whatsapp.net` or `...@g.us`) |
| `count` | no | Messages to request; default `50`, capped at `500` |

Caveats:

- **The phone decides how much it returns**, exactly as with pair-time sync, so
  `count` is a request rather than a guarantee.
- **At least one message for the chat must already be stored**, since it is used
  as the anchor. Chats with no local messages return `404`; send or receive one
  message first.
- Messages the phone has deleted are not recoverable, as above.

## Call History

The bridge captures incoming WhatsApp voice and video calls live into a
dedicated `calls` table in `messages.db`. When a 1:1 call arrives
(`CallOffer`) or a group call is announced (`CallOfferNotice`), a row is
inserted with `result='in_progress'`. Subsequent `CallAccept` /
`CallReject` / `CallTerminate` events update the row — final result becomes
`answered`, `rejected`, `missed`, or `ended` depending on the event
sequence. See the state-machine comment above `StoreCallOffer` in `main.go`
for the exact transitions.

### Schema

```sql
CREATE TABLE calls (
    call_id TEXT,
    chat_jid TEXT,          -- group JID for group calls, call creator JID for 1:1
    from_jid TEXT,          -- JID of whoever started the call
    timestamp TIMESTAMP,    -- call start time
    is_from_me BOOLEAN,
    call_type TEXT,         -- 'voice' or 'video'
    is_group BOOLEAN,
    result TEXT,            -- 'in_progress' | 'answered' | 'ended' |
                            --   'missed' | 'rejected'
    duration_sec INTEGER,   -- computed when the call terminates
    ended_at TIMESTAMP,
    reason TEXT,            -- terminate reason string from whatsmeow
    PRIMARY KEY (call_id, chat_jid)
);
```

### Caveats

- **Outbound calls are not captured.** WhatsApp's primary device handles
  calls it initiates without notifying linked devices, so the bridge never
  sees an event for them.
- **Call results only reflect what the bridge saw.** If the bridge is
  offline when a call happens, the events are lost.
- **1:1 calls default to `call_type='voice'`.** `CallOffer` events don't
  expose media type directly (it's buried in the binary call data). Group
  calls via `CallOfferNotice` include a `Media` field and are recorded
  accurately as voice or video.

## Architecture

```mermaid
flowchart TB
    subgraph Clients["AI Clients"]
        CD[Claude Desktop]
        CU[Cursor IDE]
        CC[Claude Code]
    end

    subgraph MCP["MCP Layer"]
        PY[Python MCP Server<br/>FastMCP]
    end

    subgraph Bridge["WhatsApp Bridge"]
        GO[Go Bridge<br/>whatsmeow]
        DB[(SQLite<br/>messages.db)]
        WH[Webhook Handler]
    end

    subgraph External["External Services"]
        WA[WhatsApp Web API]
        EXT[External Webhook<br/>Receiver]
    end

    CD & CU & CC -->|MCP Protocol| PY
    PY -->|REST API| GO
    PY -->|Read| DB
    GO -->|Store| DB
    GO <-->|WebSocket| WA
    GO -->|Forward Messages| WH
    WH -->|POST| EXT
```

### Component Details

```mermaid
flowchart LR
    subgraph GoAPI["Go Bridge REST API"]
        direction TB
        SEND["/api/send"]
        READ["/api/mark-read"]
        DOWN["/api/download"]
        REACT["/api/react"]
        TYPE["/api/typing"]
        HIST["/api/history"]
        HEALTH["/api/health"]
    end

    subgraph MCPTools["MCP Tools (15 total)"]
        direction TB
        CONT["Contact Tools<br/>search_contacts, get_contact"]
        MSG["Message Tools<br/>list_messages, send_message, etc."]
        CHAT["Chat Tools<br/>list_chats, get_chat, etc."]
        MEDIA["Media Tools<br/>send_file, download_media, etc."]
    end

    MCPTools -->|HTTP Requests| GoAPI
```

### Data Flow

```mermaid
sequenceDiagram
    participant User as User
    participant Claude as Claude Desktop
    participant MCP as Python MCP Server
    participant Bridge as Go Bridge
    participant WA as WhatsApp

    User->>Claude: "Send 'Hello' to Mom"
    Claude->>MCP: send_message(recipient, message)
    MCP->>Bridge: POST /api/send
    Bridge->>WA: Send via WebSocket
    WA-->>Bridge: Delivery confirmation
    Bridge-->>MCP: Success response
    MCP-->>Claude: Message sent
    Claude-->>User: "Message sent to Mom"
```

### Incoming Message Flow

```mermaid
sequenceDiagram
    participant WA as WhatsApp
    participant Bridge as Go Bridge
    participant DB as SQLite
    participant WH as Webhook
    participant EXT as External Service

    WA->>Bridge: New message
    Bridge->>DB: Store message
    Bridge->>Bridge: Auto-download media
    Bridge->>WH: Forward to webhook
    WH->>EXT: POST with message data
    Note over EXT: Process incoming message
```

## Development

### Running Tests

```bash
cd whatsapp-mcp-server
uv pip install -e ".[dev]"
uv run pytest -v
```

### Linting

```bash
# Python
cd whatsapp-mcp-server
uv run ruff check .
uv run ruff format .

# Go
cd whatsapp-bridge
golangci-lint run
```

### Building

```bash
# Go bridge
cd whatsapp-bridge
go build -o whatsapp-bridge

# Run the binary
./whatsapp-bridge

# During development (avoids stale binaries)
go run .
```

### Releasing (Maintainers)

Releases use Release Please automation; maintainer steps and fallback procedures
are documented in [docs/RELEASING.md](docs/RELEASING.md).

## Troubleshooting

### Authentication Issues

- **Pairing fails with `Client outdated` or HTTP 405**: Update to the latest
  release and rebuild the bridge. WhatsApp periodically raises the minimum
  supported linked-device client version, which can make older whatsmeow builds
  fail before pairing completes.
- **QR Code Not Displaying**: Restart the bridge. Check terminal QR code support.
- **Phone says "check your connection" after scanning**: WhatsApp answers a scan
  with a `companion_reg_refresh` notification, whatsmeow rotates the pairing
  secret, and the bridge prints a **new** QR code marked `QR code refreshed`.
  Scan that one — the earlier code is dead at that point. Needs a whatsmeow
  build from 2026-09-15 or later; older ones never emit the rotated code.
- **Device Limit Reached**: Remove a linked device from WhatsApp Settings > Linked Devices.
- **No Messages Loading**: Initial sync can take several minutes for large chat histories.
- **Out of Sync**: Back up `whatsapp-bridge/store`, then move
  `whatsapp-bridge/store/whatsapp.db` aside and re-authenticate. Keep
  `messages.db` unless you intentionally want to discard local message history.
- **Bridge returns 401 Unauthorized**: Restart the bridge so it creates
  `.bridge-token` next to `WHATSMEOW_DB_PATH`, then restart the MCP server. If
  the MCP server cannot read that file, set `WHATSAPP_BRIDGE_TOKEN` to the same
  value in both environments.
- **Bridge returns 403 Forbidden for Host**: Use `WHATSAPP_API_URL` with
  `http://127.0.0.1:<port>/api`, `http://localhost:<port>/api`, or
  `http://[::1]:<port>/api`; custom hostnames and missing ports are rejected.
- **Bridge returns 403 Forbidden for media_path**: Move the file into
  `~/.local/share/whatsapp-mcp/outbox` or add its absolute parent directory to
  `WHATSAPP_MEDIA_ROOTS`.

### App State / LTHash Conflicts

Some WhatsApp account state is managed by whatsmeow in
`whatsapp-bridge/store/whatsapp.db`. If the bridge reports errors like:

```text
SendAppState failed: server returned error updating app state (regular_low):
<error code="409" text="conflict"/>
failed to verify patch v12345: mismatching LTHash
```

then WhatsApp's app-state patch chain for the linked device is out of sync.
This usually affects operations that write chat settings such as archive,
mute, or pin state. Incoming and outgoing messages may still work because
message storage lives separately in `messages.db`.

Known manual resync attempts such as `FetchAppState(..., fullSync=true)` may
still fail on this upstream app-state error class. The practical recovery path
is to reset the whatsmeow session and re-pair:

```bash
# Stop the bridge first.
launchctl bootout gui/$UID/com.whatsapp-mcp.bridge    # or however you manage it

# Back up the whole runtime store.
cp -a whatsapp-bridge/store whatsapp-bridge/store.bak.$(date +%Y%m%d%H%M%S)

# Reset only the whatsmeow session/app-state DB.
mv whatsapp-bridge/store/whatsapp.db whatsapp-bridge/store/whatsapp.db.lthash.bak

# Restart the bridge and scan the new QR code.
cd whatsapp-bridge
./whatsapp-bridge    # or `go run .` during development
```

Do not remove `whatsapp-bridge/store/messages.db` for this recovery unless you
also want to delete the local message archive.

### Windows

Windows requires CGO for go-sqlite3. Install [MSYS2](https://www.msys2.org/) and enable CGO:

```bash
go env -w CGO_ENABLED=1
go run .
```

## Security Notice

> **Caution**: As with many MCP servers, this is subject to [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). Prompt injection could lead to private data exfiltration. Use with awareness.

On Unix-like systems, newly created bridge `store/` and per-chat media
directories request owner-only permissions (`0700`), and newly downloaded media
files request `0600`. This is local filesystem defense-in-depth; it does not
encrypt data or protect it from privileged users, backups, or sync services.
Existing directories and files retain their permissions: the bridge does not
recursively change an existing store tree.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Credits & History

This project is a maintained fork of [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp), originally created by [Luke Harries](https://github.com/lharries).

**Why we forked:** The original repository hasn't been updated since April 2025. We needed continued maintenance, bug fixes, and new features for production use.

**Highlights since the fork:**

- `/api/typing`, `/api/health`, and webhook forwarding (with reply context + image media)
- Auto-download of incoming media with collision-safe filenames
- `get_contact` tool, `sender_display` field, and LID ↔ phone resolution via the whatsmeow store
- Live capture of incoming voice/video calls into a `calls` table
- `--full-history-pair` flag to request extended history at pair time
- Resilience: recovers from `StreamReplaced` session conflicts; pinned `anyio` to dodge a cancel-scope regression
- CI/CD with GitHub Actions, Release Please for automated versioning, and Dependabot

The full release-by-release list lives in [CHANGELOG.md](CHANGELOG.md).

**Recent contributors** (huge thanks):

- [@edmenendez](https://github.com/edmenendez) — call capture (#39), full-history flag (#37), caption surfacing (#42), media filename collisions (#40), download race fix (#41), LID matching (#43), contact resolution via whatsmeow store (#30)
- [@davidsimoes](https://github.com/davidsimoes) — `StreamReplaced` recovery (#27)
- [@davidggphy](https://github.com/davidggphy) — LID → phone JID consistency (#12)
- [@maikol-solis](https://github.com/maikol-solis) — bridge run command fix (#23)
- [@DeetBot](https://github.com/DeetBot) — `anyio` cancel-scope pin (#44)

And to Luke for creating the original project. See [CONTRIBUTING.md](CONTRIBUTING.md) if you'd like to join in.

## Links

- [Very Good Plugins](https://verygoodplugins.com/?utm_source=github)
- [MCP Specification](https://modelcontextprotocol.io/)
- [whatsmeow](https://github.com/tulir/whatsmeow) - WhatsApp Web API library for Go
- [FastMCP](https://github.com/jlowin/fastmcp) - Fast Model Context Protocol implementation

### Isolated account service qualification

The local Gate C image retains upstream features and adds independently enforced,
account-scoped capabilities. Production startup requires `WHATSAPP_AUTH_POLICY`
(private JSON consumers with id, account, token_sha256 and capabilities),
`WHATSAPP_ACCOUNT_ALIAS`, and `WHATSAPP_MCP_SOCKET` (private Unix endpoint).
`service --wait-unpaired` co-locates the bridge and authenticated stdio broker,
without Docker privileges for consumers. The host `mcp-client.py` relay accepts
only an operator-configured socket and private scoped token file. MCP consumers
never receive the master bridge token. Policy changes revoke capabilities on the
next operation. `--offline` is for disposable qualification only; fresh pairing
requires an explicitly approved private `--pairing-socket`.

Scoped read permissions: messages.read, contacts.read, media.read, media.download,
audio.transcribe, calls.read. Separate write permissions: messages.send,
media.send, reactions.send, receipts.write, typing.send, history.request.
Webhook configuration remains administrator-controlled. calls.respond is not
implemented. No live automation worker is enabled. Legacy standalone behavior
remains available in source; the secured image requires explicit policy.

The image uses `/runtime/store/{whatsapp.db,messages.db}` and confines outbound
media to `WHATSAPP_MEDIA_ROOTS` (default `/runtime/outbox`). Content logging,
webhooks and automatic media download default off. Do not copy live SQLite files
blindly; coordinate stopped-writer backup of the complete account store.

### Private stdio consumer shutdown

The private broker closes child stdin before escalation: EOF grace 2 seconds, cooperative SIGTERM 2 seconds, then SIGKILL/reap 2 seconds. Only the peer worker owns child teardown; broker shutdown wakes peers and allows up to 10 seconds for workers. The secured POSIX stdio runner uses cancellable pipe reads with the pinned MCP transport and cancels its owning AnyIO scope on SIGINT/SIGTERM. A long synchronous tool can require bounded escalation; interrupted read replies are not guaranteed. No bridge/session owner is restarted by consumer closure.

Python diagnostics are sanitized at standard handler emission, including newly attached handlers; the stdio event-loop and unhandled/thread exception boundaries emit fixed categories. Broker child stderr is contained as bounded severity-only records. Arbitrary custom handler overrides/direct writes outside the broker are outside this assurance. Normal tool results are not diagnostic logs. Unexpected consumer failure retains ERROR/nonzero status; forced termination is separately observable.

Broker admission configuration: `MAX_MCP_CLIENTS` defaults to `8` when unset; set `4` for the restricted offline-qualified envelope. Explicit values must be ASCII integers 1–8; invalid/empty settings fail before socket creation with sanitized diagnostics. Capacity is reserved before authentication and released only after consumer cleanup; pending authentication can temporarily occupy a slot. Excess connections close immediately without a consumer or token. This bounds sessions only: one outstanding bounded read per client remains an operating restriction, not an enforced request or response-byte limit.


## WhatsApp MCP ব্যবহার সহায়িকা: অনুমতি ও পরীক্ষার অবস্থা

এই অংশটি স্থানীয় VPS deployment-এর **১১ অক্টোবর ২০২৬ (Asia/Dhaka)** অডিটের snapshot; upstream-এর সব installation-এর default নয়। বর্তমান অনুমতির চূড়ান্ত উৎস সংশ্লিষ্ট account-এর private consumer policy। পরবর্তী policy পরিবর্তনে এই snapshot পুরোনো হতে পারে।

### অবস্থার অর্থ

- **বাস্তবায়িত:** tool registration ও কাজ করার কোড আছে। এটি বাস্তব WhatsApp-এ সম্পূর্ণ সফলতার প্রমাণ নয়।
- **সচল/অনুমোদিত:** নির্দিষ্ট consumer-এর policy-তে প্রয়োজনীয় সব capability আছে; সে টুলটি চালানোর অনুমতি পায়। সংযোগ, ডেটা বা dependency না থাকলে কাজ তবুও ব্যর্থ হতে পারে।
- **বন্ধ:** সেই consumer প্রয়োজনীয় capability পায়নি; secured MCP-তে টুল লুকানো থাকে এবং সরাসরি invocation-ও প্রত্যাখ্যাত হয়। কোড মুছে দেওয়া হয়নি।
- **পরীক্ষিত:** কী পরীক্ষা হয়েছে তা আলাদা করে বলতে হবে—কোড/fixture পরীক্ষা, tool listing, permission denial এবং বাস্তব ফলাফল একই প্রমাণ নয়।

`wa-01` ও `wa-02` service audit-এ চলমান পাওয়া গেছে। দুই account-এর owner-reader-এর grants: `messages.read`, `contacts.read`, `media.read`, `media.download`, `calls.read`। `wa-03`-এর reader policy আছে, কিন্তু live service সক্রিয় নয়। **নিচের সচল/বন্ধ অবস্থা wa-01/wa-02 owner-reader-এর জন্য। Hermes-এর জন্য consumer/credential/MCP সংযোগ provision করা হয়নি; সে এই owner-reader অনুমতি স্বয়ংক্রিয়ভাবে পায় না।**

### ১৭টি টুল: ব্যবহার, অনুমতি ও যা পরীক্ষা করতে হবে

সব ১৭টি টুল বাস্তবায়িত। “বাস্তব পরীক্ষা বাকি” মানে অকার্যকর প্রমাণিত নয়; সেই ফলাফলের পর্যাপ্ত live প্রমাণ নেই। পূর্বের qualification evidence পর্যালোচনা করা হয়েছে; এই documentation update-এ live tool execution বা নতুন unit test চালানো হয়নি।

| টুল | সাধারণ ব্যবহার | প্রয়োজনীয় capability | বর্তমান owner-reader অবস্থা | পরীক্ষার প্রমাণ ও বাকি যাচাই |
| --- | --- | --- | --- | --- |
| `search_contacts` | `query` দিয়ে নাম/ফোন খোঁজা | `contacts.read` | সচল | বাস্তব contact retrieval হয়েছে; বাংলা নাম, partial phone ও no-match case আরও যাচাই করা দরকার। |
| `get_contact` | `identifier` দিয়ে ফোন, LID বা পূর্ণ JID resolve | `contacts.read` | সচল | resolution-এর কোড পরীক্ষা আছে; বাস্তব phone/LID/JID একই ব্যক্তিকে resolve করে কি না পৃথকভাবে যাচাই বাকি। |
| `list_messages` | chat, sender, query, date range, pagination ও sorting দিয়ে মেসেজ পড়া | `messages.read` + `contacts.read` | সচল | বাস্তব message retrieval হয়েছে; সব filter/date boundary/sort/context combination live যাচাই হয়নি। |
| `send_message` | ব্যক্তিগত বা group recipient-কে text/quoted reply/mention পাঠানো | `messages.send` | বন্ধ | registration ও unauthorized denial যাচাই; বাস্তব send/delivery/quoted reply/group mention পরীক্ষা বাকি। |
| `mark_messages_read` | একই chat ও sender-এর message IDs-এ read receipt পাঠানো | `receipts.write` | বন্ধ | denial যাচাই; বাস্তব receipt ও read-state পরিবর্তন পরীক্ষা বাকি। এটি বাহ্যিক পরিবর্তন করে। |
| `send_reaction` | নির্দিষ্ট message-এ emoji যোগ বা `emoji=""` দিয়ে সরানো | `reactions.send` | বন্ধ | denial যাচাই; বাস্তব reaction যোগ/সরানো এবং group sender mapping পরীক্ষা বাকি। |
| `send_file` | অনুমোদিত local path থেকে image/video/document ও caption পাঠানো | `media.send` | বন্ধ | media path/permission/caption পরীক্ষা আছে; বাস্তব send, MIME ও recipient-side caption যাচাই বাকি। |
| `send_audio_message` | local audio-কে voice note হিসেবে পাঠানো | `media.send` | বন্ধ | real FFmpeg Opus `.ogg` conversion পাস; WhatsApp send ও recipient playback পরীক্ষা বাকি। |
| `download_media` | message ID + chat JID দিয়ে media নামিয়ে local path পাওয়া | `media.download` | সচল | অনুমতি ও implementation আছে; বাস্তব image/video/audio download, expired media ও failure case যাচাই বাকি। এটি স্থানীয় ফাইল লেখে। |
| `view_media` | image দেখা বা video-এর প্রথম frame preview | `media.read` + `media.download` | সচল | preview/tool কোড পরীক্ষা আছে; বাস্তব message থেকে পূর্ণ download-to-preview যাচাই বাকি। অডিও playback বা পুরো video playback নয়। |
| `transcribe_audio` | voice/audio message থেকে transcript তৈরি | `audio.transcribe` + `media.download` | বন্ধ | implementation/provider পরীক্ষা আছে; live provider/model, বাংলা voice note ও transcript persistence যাচাই বাকি। |
| `list_chats` | chat name/JID search, pagination, last activity/unread দেখা | `messages.read` | সচল | বাস্তব chat retrieval হয়েছে; সব sorting/paging এবং phone read-state correspondence যাচাই বাকি। |
| `get_chat` | `chat_jid` দিয়ে একটি chat-এর metadata | `messages.read` | সচল | বাস্তবায়িত ও catalog-এ অনুমোদিত; প্রত্যেক field-এর পৃথক live যাচাই বাকি। |
| `get_direct_chat_by_contact` | `sender_phone_number` দিয়ে direct chat খোঁজা | `messages.read` | সচল | বাস্তবায়িত; known contact/no-chat ও phone/LID correspondence live যাচাই বাকি। |
| `get_contact_chats` | contact `jid` জড়িত stored chats খোঁজা | `messages.read` + `contacts.read` | সচল | বাস্তবায়িত; direct/group ফল ও pagination live যাচাই বাকি। পূর্ণ WhatsApp group membership inventory ধরে নেওয়া যাবে না। |
| `get_last_interaction` | contact `jid`-এর সর্বশেষ stored message পাওয়া | `messages.read` + `contacts.read` | সচল | বাস্তবায়িত; timestamp/order ও missing-contact case live যাচাই বাকি। |
| `get_message_context` | message ID ও chat JID দিয়ে আশপাশের মেসেজ পাওয়া | `messages.read` + `contacts.read` | সচল | tool পরীক্ষা আছে; বাস্তব before/after window, ordering ও boundary case যাচাই বাকি। |

Owner-reader-এর ১২টি exposed tool-এর মধ্যে উপরোক্ত ১১টি এবং অতিরিক্ত `list_calls` আছে। তালিকার বাইরের `set_typing` ও `request_history` বর্তমান reader-এর জন্য বন্ধ। tool count-কে ১৭টি tool-এর সব কাজের live পরীক্ষার প্রমাণ হিসেবে ব্যবহার করবেন না।

### পড়ার টুল ব্যবহার করার ধাপ

1. `search_contacts` দিয়ে contact খুঁজুন; প্রয়োজনে `get_contact` দিয়ে identity নিশ্চিত করুন। নাম একই হলে শুধু নামের ওপর নির্ভর করবেন না।
2. `list_chats` বা `get_direct_chat_by_contact` থেকে প্রকৃত chat JID নিন। Direct JID সাধারণত `…@s.whatsapp.net`, group JID `…@g.us`; `…@lid`-ও থাকতে পারে। ফোন ও LID নিজে অনুমান করে বিনিময় করবেন না।
3. `list_messages` ছোট `limit` দিয়ে চালান; বড় ফলের জন্য `page` ব্যবহার করুন। সময়ের প্রশ্নে timezone ও সংরক্ষিত timestamp যাচাই করুন। `include_context=false` দিয়ে প্রথম ফল ছোট রাখা যায়।
4. প্রয়োজন হলে ফেরত পাওয়া message ID দিয়ে `get_message_context`, `download_media` বা `view_media` ব্যবহার করুন। অন্য chat-এর ID মিশিয়ে দেবেন না।

উদাহরণগুলো MCP tool arguments; shell command নয়। placeholder-এর জায়গায় অনুমোদিত account-এর retrieval থেকে পাওয়া মান বসাতে হবে:

```json
{"query": "যোগাযোগের নাম"}
```

উপরের arguments `search_contacts`-এর জন্য। `list_messages`-এর ছোট নমুনা:

```json
{"chat_jid": "<retrieved-chat-jid>", "limit": 5, "page": 0, "sort_by": "newest", "include_context": false}
```

`download_media`-এর arguments:

```json
{"message_id": "<retrieved-message-id>", "chat_jid": "<retrieved-chat-jid>"}
```

`download_media`-এর local path client-এর filesystem-এ নাও পাওয়া যেতে পারে; ছবি দেখার জন্য `view_media` ব্যবহার করুন। Voice note-এর জন্য `transcribe_audio` দরকার। পড়ার tool `messages.db`-এর stored projection পড়ে; phone history sync যতটুকু দিয়েছে ততটুকুই দেখা যায়। কোনো ফল না পাওয়া মানে WhatsApp-এ কখনো কথোপকথন হয়নি—এমন সিদ্ধান্ত নয়।

### বন্ধ টুল সচল করার প্রশাসনিক ব্যবস্থা

এই ধাপগুলো নির্দেশনা; documentation update কোনো grant, credential, service বা pairing পরিবর্তন করে না।

1. **consumer ও account ঠিক করুন।** Hermes হলে owner-reader token ধার না দিয়ে নিজস্ব consumer ID এবং পৃথক scoped token দিন। account policy-এর host path: `/etc/vps/services/whatsapp/wa-01-consumer-policy.json` বা সংশ্লিষ্ট `wa-02`/`wa-03` file; secured service-এ এটি `/run/secrets/consumer-policy.json` হিসেবে mounted।
2. **অনুমোদিত capability দিন।** বিদ্যমান `consumers` array-তে consumer entry রাখুন: `id`, `account`, private token-এর `token_sha256` এবং নির্বাচিত `capabilities`। অন্য consumer entry অক্ষত রাখুন। token বা তার বাস্তব hash README, chat, Git বা সাধারণ log-এ লিখবেন না। শুধু নতুন credential তৈরি করলে client-side private token file-এ সেই আসল token দিতে হবে।
3. **নির্ভুল permission যাচাই করুন।** `messages.send` text send; `receipts.write` read receipt; `reactions.send` reaction; `media.send` file ও voice send দুটো; `audio.transcribe` + `media.download` transcription। পুরোনো read grant রাখতে চাইলে সেগুলোও entry-তে থাকবে।
4. **private file ও mount বজায় রাখুন।** file ownership/read access service-এর জন্য উপযুক্ত রাখুন; public বা group-writable policy/token নয়। existing bind mount একই updated policy দেখছে কি না যাচাই করুন—atomic file replacement-এ mounted পুরোনো inode থেকে যেতে পারে। update strategy অনুযায়ী controlled remount/restart প্রয়োজন হতে পারে; policy change হলেই সর্বদা restart লাগে—এমন নয়।
5. **client সংযুক্ত করুন।** scoped token file, account socket-এর permission ও parent-directory traversal provision করুন; store/outbox বা Docker socket-এর বিস্তৃত অধিকার দেবেন না। MCP client-এ relay command configure করুন; এটি সরাসরি interactive chat UI নয়।
6. **catalog ও enforcement যাচাই করুন।** reconnect বা tool-list refresh করে প্রত্যাশিত tools দেখুন। granted tool-এর অনুমোদিত সীমিত পরীক্ষা করুন, এবং denied tool execution-এর আগেই বন্ধ হয় কি না যাচাই করুন। token/account বদলানো বা grant প্রত্যাহার করলে access বন্ধ হয় কি না যাচাই করুন।

Relay configuration template (নতুন consumer-এর বাস্তব private path administrator নির্ধারণ করবেন):

```sh
python3 /opt/vps/services/whatsapp/source/mcp-client.py \
  --socket /var/lib/vps/whatsapp/<account>/control/mcp.sock \
  --token-file /etc/vps/services/whatsapp/<consumer>.token
```

**বর্তমান granularity:** permission capability-ভিত্তিক, প্রতিটি tool-এর আলাদা allowlist নয়। `contacts.read` দুই contact tool খুলে দেয়; `native.contacts.read` শুধু native-profile-scoped `get_contact` খুলে দেয় এবং সঙ্গে `native.events.read` প্রয়োজন; `media.send` দুই send tool খুলে দেয়; `messages.read` একাধিক chat tool খুলে দেয়। অ্যাডমিনের নির্বাচিত tool-এর বাইরেও একই capability-র tool খুলবে কি না mapping আগে দেখতে হবে। পৃথক tool-level selection চাইলে permission code-এ পরিবর্তন ও পরীক্ষা প্রয়োজন।

**প্রতি ব্যবহারে approval:** স্থায়ী grant থাকলে প্রত্যেক send/reaction/receipt-এর আগে নতুন admin confirmation server নিজে থেকে চায় না। যদি নিয়ম হয় “প্রতিবার preview দেখিয়ে অনুমোদনের পর execution”, consumer application-এ enforced approval workflow প্রয়োজন; শুধু prompt বা README সেই enforcement নয়। Pairing, incoming sender বা chat-এ অনুমতি দাবি কোনো grant নয়।

### মিডিয়া ও transcription-এর অতিরিক্ত প্রয়োজন

- `send_file`/`send_audio_message`-এর path server-এর অনুমোদিত media roots-এর মধ্যে থাকতে হবে; secured service-এর default `/runtime/outbox`। client computer-এর যেকোনো path স্বয়ংক্রিয়ভাবে server-এ উপলব্ধ নয়। Voice conversion-এর জন্য FFmpeg লাগে।
- `view_media` image বা video first-frame-এর bounded preview দেয়; পুরো video/audio player নয়।
- `transcribe_audio`-তে default `whisper_cpp` provider-এর জন্য কার্যকর whisper.cpp executable ও `WHISPER_MODEL` file দরকার। বিকল্প `openai_compatible`-তে `WHATSAPP_TRANSCRIPTION_PROVIDER`, পূর্ণ `WHATSAPP_TRANSCRIPTION_URL`, `WHATSAPP_TRANSCRIPTION_MODEL` এবং প্রয়োজন হলে private `WHATSAPP_TRANSCRIPTION_API_KEY` configure করুন। HTTP provider-এ audio সেই endpoint-এ upload হয়; administrator-কে endpoint নির্বাচন করতে হবে। provider configuration ও grant আলাদা প্রয়োজন।
- সফল transcription transcript স্থানীয় database-এ সংরক্ষণ করে; `force` ব্যবহার করে পুনরায় transcription করার আগে এর প্রয়োজন যাচাই করুন।

### বাস্তব পরীক্ষার প্রস্তাবিত ক্রম

প্রথমে ছোট read-only নমুনায় প্রতিটি সচল tool-এর বাস্তব ফল, identity, sorting, date boundary ও context যাচাই করুন। তারপর নির্দিষ্ট অনুমোদিত image/video/audio message দিয়ে download/preview পরীক্ষা করুন; expired/unavailable media-র ব্যর্থতাও নথিভুক্ত করুন।

বন্ধ send/receipt/reaction tool-এর live পরীক্ষা শুধু অনুমোদিত পরীক্ষার contact/group ও নির্দিষ্ট action-এ করুন। text ও media send-এর recipient-side ফল, voice playback, reaction যোগ/সরানো এবং read receipt যাচাই করুন। ব্যর্থ send-এর পরে recipient-side ফল না দেখে অন্ধভাবে retry করলে duplicate হতে পারে। পরীক্ষার জন্য প্রয়োজনের চেয়ে বেশি grant দেবেন না; অস্থায়ী grant শেষে প্রত্যাহার ও denial যাচাই করুন।

Transcription-এর জন্য অনুমোদিত voice note ও configured provider দিয়ে বাংলা/অন্যান্য প্রয়োজনীয় ভাষা, ব্যর্থতার handling এবং transcript persistence যাচাই করুন। Hermes provision হলে তার নিজস্ব credential দিয়ে account isolation, allowed/denied tool behavior এবং প্রয়োজনীয় per-action approval workflow আলাদাভাবে পরীক্ষা করুন। এখনো কোনো Hermes live integration acceptance হয়নি।

একই সময়ে সর্বোচ্চ চারটি consumer session-এর বর্তমান সীমা আছে; পঞ্চমটি প্রত্যাখ্যাত হয়। প্রতি client-এ একটি করে ছোট sequential read বর্তমান operating restriction; arbitrary request/result size বা একাধিক in-flight call-এর budget সম্পূর্ণ enforced নয়। unrestricted media load, বড় history/context ও দীর্ঘমেয়াদি stability এই bounded qualification থেকে প্রমাণিত নয়।

### প্রমাণ ও পরবর্তী update

- [Capability mapping ও enforcement](whatsapp-mcp-server/capabilities.py)
- [Tool signatures ও আচরণ](whatsapp-mcp-server/main.py)
- [Offline acceptance: registration, denial, revocation, FFmpeg conversion](../qualification/mcp-cap4-20261011/acceptance.json)
- [WA-01 live acceptance: tool filtering ও unauthorized denial](../qualification/wa01-cap4-live-20261011/acceptance.json)
- [WA-02 live acceptance: tool filtering ও unauthorized denial](../qualification/wa02-cap4-live-20261011/acceptance.json)
- [আগের বাস্তব contact/chat/message retrieval](../qualification/gate-e2-results.json)
- [Deployment ও অনুমতির ধারাবাহিক নথি](../../../whatsapp-mcp-plan.md)

নতুন grant বা live পরীক্ষার পর এই অংশের তারিখ, account/consumer scope, ফল এবং evidence link আপডেট করুন। test fixture PASS-কে live delivery PASS হিসেবে লিখবেন না; policy-তে অনুমতি থাকা এবং বাস্তব কাজ সফল হওয়া আলাদা তথ্য।

AL-RIFA’I workflow source update (15 October 2026): stored history permits only
three exact wa-01 group JIDs in addition to direct peers, and still requires the
current native principal's exact chat/content/participant scope. Unlisted group
participants have no body/hash projection. No group grants are activated here.
`ALRIFAI_MCP_SOCKET_ACL=uid10001` applies a named rw ACL before listen, only for
`WHATSAPP_MCP_SOCKET=/runtime/control/app-broker/mcp.sock`. Use an independently
provisioned socket-only directory mounted into the app; parent/store/call paths
are not exposed. This source fix and candidate image require separate activation.
