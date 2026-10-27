package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"math/rand"
	"mime"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/mdp/qrterminal"

	"bytes"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/proto/waCompanionReg"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

// Whether to forward messages sent by self via webhook.
// Defaults to true. Override with env FORWARD_SELF=false.
var forwardSelfMessages = getEnvBool("FORWARD_SELF", true)

// autoDownloadMediaEnabled reports whether incoming media is downloaded
// automatically, including images for webhooks. A false value leaves media to
// on-demand /api/download calls. Read per call so tests can toggle it.
func autoDownloadMediaEnabled() bool {
	return getEnvBool("WHATSAPP_AUTO_DOWNLOAD_MEDIA", true)
}

// CLI flag: request a full history sync at pair time.
// Only meaningful on a fresh pair (whatsapp.db deleted). See the usage block
// near NewClient for the full rationale and caveats.
var fullHistoryPairFlag = flag.Bool("full-history-pair", false,
	"Request full history at pair time (only effective when re-pairing; no-op for existing sessions)")

const whatsmeowDBPath = "store/whatsapp.db"

var nativeMessageJIDPattern = regexp.MustCompile(`^[A-Za-z0-9_.:+-]{1,160}@(s\.whatsapp\.net|lid|g\.us)$`)

// getEnvBool reads a boolean env var with a default.
// Accepts: 1/true/yes/on and 0/false/no/off (case-insensitive)
func getEnvBool(key string, def bool) bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv(key)))
	if v == "" {
		return def
	}
	switch v {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return def
	}
}

// resolveDeviceName returns the operator-configured linked-device label from
// WHATSAPP_DEVICE_NAME, trimmed of surrounding whitespace. An empty or unset
// value returns "", which callers treat as "keep the whatsmeow default".
func resolveDeviceName() string {
	return strings.TrimSpace(os.Getenv("WHATSAPP_DEVICE_NAME"))
}

// Message represents a chat message for our client
type Message struct {
	Time                time.Time
	Sender              string
	Content             string
	IsFromMe            bool
	MediaType           string
	Filename            string
	OriginalSenderJID   string
	OriginalChatJID     string
	GroupParticipantJID string
	ResolvedSenderJID   string
	ResolvedChatJID     string
	IdentityState       string
	ChatIdentityState   string
}

type IdentityState string

const (
	IdentityResolved   IdentityState = "RESOLVED"
	IdentityUnresolved IdentityState = "UNRESOLVED"
	IdentityAmbiguous  IdentityState = "AMBIGUOUS"
)

type ResolvedIdentity struct {
	OriginalJID string
	LID         string
	PN          string
	ResolvedJID string
	State       IdentityState
}

type MessageIdentity struct {
	OriginalSenderJID   string
	OriginalChatJID     string
	GroupParticipantJID string
	ResolvedSenderJID   string
	ResolvedChatJID     string
	State               IdentityState
	ChatState           IdentityState
}

// Database handler for storing message history
type MessageStore struct {
	db   *sql.DB
	waDB *sql.DB // whatsmeow's DB for contact name resolution fallback
}

type ChatEphemeralSettings struct {
	Expiration       uint32
	SettingTimestamp int64
}

func ensureOwnerOnlyDirectory(path string) error {
	return os.MkdirAll(path, 0o700)
}

func writeOwnerOnlyFile(path string, data []byte) error {
	return os.WriteFile(path, data, 0o600)
}

func validateStorePathComponent(name, value string) error {
	if value == "" || value == "." || value == ".." || filepath.IsAbs(value) ||
		filepath.Base(value) != value || strings.ContainsAny(value, `/\\`) {
		return fmt.Errorf("invalid %s for media store path", name)
	}
	return nil
}

func pathWithin(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel)
}

func mediaDownloadStorePaths(chatJID, mediaType, messageID string, timestamp time.Time) (string, string, string, error) {
	chatComponent := strings.ReplaceAll(chatJID, ":", "_")
	if err := validateStorePathComponent("chat JID", chatComponent); err != nil {
		return "", "", "", err
	}
	if err := validateStorePathComponent("message ID", messageID); err != nil {
		return "", "", "", err
	}
	if err := validateStorePathComponent("media type", mediaType); err != nil {
		return "", "", "", err
	}
	// Recheck locality at the filesystem boundary. The checks above enforce the
	// stricter single-component contract, while IsLocal also rejects paths that
	// would escape a relative store path after cleaning.
	if !filepath.IsLocal(chatComponent) {
		return "", "", "", fmt.Errorf("invalid chat JID for media store path")
	}
	if !filepath.IsLocal(messageID) {
		return "", "", "", fmt.Errorf("invalid message ID for media store path")
	}
	if !filepath.IsLocal(mediaType) {
		return "", "", "", fmt.Errorf("invalid media type for media store path")
	}

	var ext string
	switch mediaType {
	case "image":
		ext = ".jpg"
	case "video":
		ext = ".mp4"
	case "audio":
		ext = ".ogg"
	case "sticker":
		ext = ".webp"
	}
	filename := fmt.Sprintf("%s_%s_%s%s", mediaType, timestamp.Format("20060102_150405"), messageID, ext)

	storeRoot, err := filepath.Abs("store")
	if err != nil {
		return "", "", "", fmt.Errorf("resolve media store path: %w", err)
	}
	chatDir := filepath.Join(storeRoot, chatComponent)
	localPath := filepath.Join(chatDir, filename)
	if !pathWithin(storeRoot, chatDir) || !pathWithin(storeRoot, localPath) {
		return "", "", "", errors.New("media store path escapes store directory")
	}

	return chatDir, localPath, filename, nil
}

// Initialize message store
func NewMessageStore() (*MessageStore, error) {
	// Create directory for database if it doesn't exist. Owner-only (0700):
	// this holds session keys and full message history, so it shouldn't be
	// group/other readable.
	if err := ensureOwnerOnlyDirectory("store"); err != nil {
		return nil, fmt.Errorf("failed to create store directory: %v", err)
	}

	// Open SQLite database for messages
	db, err := sql.Open("sqlite3", "file:store/messages.db?_foreign_keys=on")
	if err != nil {
		return nil, fmt.Errorf("failed to open message database: %v", err)
	}

	// Create tables if they don't exist
	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS chats (
			jid TEXT PRIMARY KEY,
			name TEXT,
			last_message_time TIMESTAMP,
			ephemeral_expiration INTEGER NOT NULL DEFAULT 0,
			ephemeral_setting_timestamp INTEGER NOT NULL DEFAULT 0
		);
		
		CREATE TABLE IF NOT EXISTS messages (
			id TEXT,
			chat_jid TEXT,
			sender TEXT,
			content TEXT,
			timestamp TIMESTAMP,
			is_from_me BOOLEAN,
			media_type TEXT,
			filename TEXT,
			url TEXT,
			media_key BLOB,
			file_sha256 BLOB,
			file_enc_sha256 BLOB,
			file_length INTEGER,
			deleted_at TIMESTAMP,
			PRIMARY KEY (id, chat_jid),
			FOREIGN KEY (chat_jid) REFERENCES chats(jid)
		);

		CREATE TABLE IF NOT EXISTS calls (
			call_id TEXT,
			chat_jid TEXT,
			from_jid TEXT,
			timestamp TIMESTAMP,
			is_from_me BOOLEAN,
			call_type TEXT,
			is_group BOOLEAN,
			result TEXT,
			duration_sec INTEGER,
			ended_at TIMESTAMP,
			reason TEXT,
			PRIMARY KEY (call_id, chat_jid)
		);

		CREATE INDEX IF NOT EXISTS idx_calls_chat ON calls(chat_jid);
		CREATE INDEX IF NOT EXISTS idx_calls_timestamp ON calls(timestamp);
		CREATE INDEX IF NOT EXISTS idx_messages_chat_jid ON messages(chat_jid);
	`)
	if err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("failed to create tables: %v", err)
	}

	// Open whatsmeow's database read-only for contact name resolution fallback.
	// Missing DBs are expected on first run and should not create a new file.
	waDB, err := openWhatsmeowContactsDB(whatsmeowDBPath)
	if err != nil {
		fmt.Println("Warning: could not open whatsmeow database for contact resolution")
	}

	if err := ensureMessageStoreSchema(db); err != nil {
		_ = db.Close()
		if waDB != nil {
			_ = waDB.Close()
		}
		return nil, err
	}

	return &MessageStore{db: db, waDB: waDB}, nil
}

func openWhatsmeowContactsDB(path string) (*sql.DB, error) {
	if _, err := os.Stat(path); err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	db, err := sql.Open("sqlite3", fmt.Sprintf("file:%s?mode=ro", path))
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		_ = db.Close()
		return nil, err
	}
	return db, nil
}

func ensureMessageStoreSchema(db *sql.DB) error {
	if err := ensureColumn(db, "chats", "ephemeral_expiration", "INTEGER NOT NULL DEFAULT 0"); err != nil {
		return fmt.Errorf("failed to ensure chats.ephemeral_expiration column: %w", err)
	}
	if err := ensureColumn(db, "chats", "ephemeral_setting_timestamp", "INTEGER NOT NULL DEFAULT 0"); err != nil {
		return fmt.Errorf("failed to ensure chats.ephemeral_setting_timestamp column: %w", err)
	}
	if err := ensureColumn(db, "chats", "last_read_time", "TIMESTAMP"); err != nil {
		return fmt.Errorf("failed to ensure chats.last_read_time column: %w", err)
	}
	if err := ensureColumn(db, "messages", "deleted_at", "TIMESTAMP"); err != nil {
		return fmt.Errorf("failed to ensure messages.deleted_at column: %w", err)
	}
	if err := ensureColumn(db, "messages", "quoted_message_id", "TEXT"); err != nil {
		return fmt.Errorf("failed to ensure messages.quoted_message_id column: %w", err)
	}
	for _, column := range []struct {
		name string
		spec string
	}{
		{"original_sender_jid", "TEXT"},
		{"original_chat_jid", "TEXT"},
		{"group_participant_jid", "TEXT"},
		{"resolved_sender_jid", "TEXT"},
		{"resolved_chat_jid", "TEXT"},
		{"identity_state", "TEXT"},
		{"chat_identity_state", "TEXT"},
	} {
		if err := ensureColumn(db, "messages", column.name, column.spec); err != nil {
			return fmt.Errorf("failed to ensure messages.%s column: %w", column.name, err)
		}
	}
	return nil
}

func ensureColumn(db *sql.DB, tableName, columnName, columnSpec string) error {
	rows, err := db.Query(fmt.Sprintf("PRAGMA table_info(%s)", tableName))
	if err != nil {
		return err
	}

	exists := false
	for rows.Next() {
		var cid int
		var name string
		var colType string
		var notNull int
		var dfltValue sql.NullString
		var pk int
		if err := rows.Scan(&cid, &name, &colType, &notNull, &dfltValue, &pk); err != nil {
			_ = rows.Close()
			return err
		}
		if name == columnName {
			exists = true
		}
	}
	if err := rows.Err(); err != nil {
		_ = rows.Close()
		return err
	}
	// Close before ALTER: SQLite holds a read lock while rows are open,
	// which would make the schema change fail with "database is locked".
	if err := rows.Close(); err != nil {
		return err
	}
	if exists {
		return nil
	}

	_, err = db.Exec(fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", tableName, columnName, columnSpec))
	return err
}

// MigrateLegacyLIDChatsToPhoneJIDs is retained for compatibility with older
// callers. Legacy chat rewriting is intentionally disabled because it merges
// identities and can delete original chat/message provenance.
func (store *MessageStore) MigrateLegacyLIDChatsToPhoneJIDs(whatsappDBPath string, logger waLog.Logger) error {
	logger.Infof("Skipping legacy LID chat rewrite; original chat identities are preserved")
	return nil
}

// MigrateLegacyLIDSendersToPhones is retained for compatibility with older
// callers. Sender rewriting is intentionally disabled to preserve provenance.
func (store *MessageStore) MigrateLegacyLIDSendersToPhones(whatsappDBPath string, logger waLog.Logger) error {
	logger.Infof("Skipping legacy LID sender rewrite; original sender identities are preserved")
	return nil
}

// Close the database connections
func (store *MessageStore) Close() error {
	var waErr error
	if store.waDB != nil {
		waErr = store.waDB.Close()
	}
	if err := store.db.Close(); err != nil {
		return err
	}
	return waErr
}

// Store a chat in the database. An empty `name` preserves any existing
// resolved contact/group name on the row — outbound-message persistence
// doesn't have a friendly name available at send time and must not clobber
// names set by inbound handling or history sync. last_message_time is
// merged monotonically so out-of-order delivery (history sync, backfill)
// can't move it backwards.
func (store *MessageStore) StoreChat(jid, name string, lastMessageTime time.Time) error {
	_, err := store.db.Exec(
		`INSERT INTO chats (jid, name, last_message_time)
		VALUES (?, ?, ?)
		ON CONFLICT(jid) DO UPDATE SET
			name = CASE WHEN excluded.name = '' THEN chats.name ELSE excluded.name END,
			last_message_time = CASE
				WHEN chats.last_message_time IS NULL THEN excluded.last_message_time
				WHEN excluded.last_message_time IS NULL THEN chats.last_message_time
				WHEN excluded.last_message_time > chats.last_message_time THEN excluded.last_message_time
				ELSE chats.last_message_time
			END`,
		jid, name, lastMessageTime,
	)
	return err
}

// UpdateChatEphemeralSettings records the chat's disappearing-message timer.
// Writes are gated on settingTimestamp so that low-information events don't
// clobber authoritative ones:
//
//   - settingTimestamp == 0: skip entirely. Sparse history-sync chunks and
//     plain (non-ephemeral) messages deliver records with no ephemeral fields,
//     and we must not interpret that absence as "the user turned it off".
//   - settingTimestamp older than the stored one: skip. Out-of-order delivery
//     (replays, late history-sync chunks, old messages flowing in) would
//     otherwise downgrade newer state to older state.
func (store *MessageStore) UpdateChatEphemeralSettings(jid string, expiration uint32, settingTimestamp int64) error {
	if settingTimestamp == 0 {
		return nil
	}
	// INSERT only the ephemeral columns; leave name/last_message_time NULL
	// so a `GroupInfo` event firing before any StoreChat call doesn't
	// fabricate placeholder metadata (raw JID as name, year-0001 timestamp)
	// that would leak into list_chats output.
	_, err := store.db.Exec(
		`INSERT INTO chats (jid, ephemeral_expiration, ephemeral_setting_timestamp)
		VALUES (?, ?, ?)
		ON CONFLICT(jid) DO UPDATE SET
			ephemeral_expiration = excluded.ephemeral_expiration,
			ephemeral_setting_timestamp = excluded.ephemeral_setting_timestamp
		WHERE excluded.ephemeral_setting_timestamp >= chats.ephemeral_setting_timestamp`,
		jid, expiration, settingTimestamp,
	)
	return err
}

// MarkChatRead records that we read the chat up to readAt. The marker merges
// monotonically — out-of-order receipts and history-sync backfill can never
// move it backwards and un-read a chat. Like UpdateChatEphemeralSettings it
// inserts only its own column, leaving name/last_message_time NULL so a receipt
// arriving before any StoreChat call doesn't fabricate placeholder metadata.
func (store *MessageStore) MarkChatRead(jid string, readAt time.Time) error {
	_, err := store.db.Exec(
		`INSERT INTO chats (jid, last_read_time)
		VALUES (?, ?)
		ON CONFLICT(jid) DO UPDATE SET
			last_read_time = CASE
				WHEN chats.last_read_time IS NULL THEN excluded.last_read_time
				WHEN excluded.last_read_time IS NULL THEN chats.last_read_time
				WHEN excluded.last_read_time > chats.last_read_time THEN excluded.last_read_time
				ELSE chats.last_read_time
			END`,
		jid, readAt,
	)
	return err
}

func (store *MessageStore) GetChatEphemeralSettings(jid string) (ChatEphemeralSettings, error) {
	var settings ChatEphemeralSettings
	err := store.db.QueryRow(
		"SELECT ephemeral_expiration, ephemeral_setting_timestamp FROM chats WHERE jid = ?",
		jid,
	).Scan(&settings.Expiration, &settings.SettingTimestamp)
	if err != nil {
		return ChatEphemeralSettings{}, err
	}
	return settings, nil
}

// GetMessageIsFromMe resolves the origin of a stored message for a quoted
// reply. The boolean pointer distinguishes a known false value from a quote
// that is absent from the local store.
func (store *MessageStore) GetMessageIsFromMe(id, chatJID string) (*bool, error) {
	var isFromMe bool
	err := store.db.QueryRow(
		"SELECT is_from_me FROM messages WHERE id = ? AND chat_jid = ?",
		id, chatJID,
	).Scan(&isFromMe)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &isFromMe, nil
}

// bareSenderUser normalizes a phone/LID or full JID to the bare user part
// stored in messages.sender.
func bareSenderUser(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, '@'); i >= 0 {
		return s[:i]
	}
	return s
}

// ValidateInboundMarkRead checks that every message ID exists in chatJID, is
// inbound, and belongs to the expected sender before we send a read receipt.
// senderHint may be bare or a full JID; when empty (DM), the chat user is used.
func (store *MessageStore) ValidateInboundMarkRead(chatJID, senderHint string, ids []string) error {
	expected := bareSenderUser(senderHint)
	if expected == "" {
		if jid, err := types.ParseJID(chatJID); err == nil {
			expected = jid.User
		}
	}
	if expected == "" {
		return fmt.Errorf("could not determine expected sender for chat %q", chatJID)
	}

	for _, id := range ids {
		var sender string
		var isFromMe bool
		err := store.db.QueryRow(
			`SELECT sender, is_from_me FROM messages WHERE id = ? AND chat_jid = ?`,
			id, chatJID,
		).Scan(&sender, &isFromMe)
		if errors.Is(err, sql.ErrNoRows) {
			return fmt.Errorf("message %q not found in chat %q", id, chatJID)
		}
		if err != nil {
			return err
		}
		if isFromMe {
			return fmt.Errorf("message %q is outbound; only inbound messages can be marked read", id)
		}
		if bareSenderUser(sender) != expected {
			return fmt.Errorf("message %q sender %q does not match %q", id, sender, expected)
		}
	}
	return nil
}

// MaxMessageTimestamp returns the latest stored timestamp among the given
// message IDs in chatJID. ok is false when none of the IDs are present.
func (store *MessageStore) MaxMessageTimestamp(chatJID string, ids []string) (time.Time, bool, error) {
	if len(ids) == 0 {
		return time.Time{}, false, nil
	}
	placeholders := make([]string, len(ids))
	args := make([]any, 0, 1+len(ids))
	args = append(args, chatJID)
	for i, id := range ids {
		placeholders[i] = "?"
		args = append(args, id)
	}
	var raw any
	err := store.db.QueryRow(
		`SELECT MAX(timestamp) FROM messages WHERE chat_jid = ? AND id IN (`+strings.Join(placeholders, ",")+`)`,
		args...,
	).Scan(&raw)
	if err != nil {
		return time.Time{}, false, err
	}
	if raw == nil {
		return time.Time{}, false, nil
	}
	ts := anchorTime(raw)
	if ts.IsZero() {
		return time.Time{}, false, fmt.Errorf("unparseable message timestamp %v", raw)
	}
	return ts, true, nil
}

// Store a message in the database
func (store *MessageStore) StoreMessage(id, chatJID, sender, content string, timestamp time.Time, isFromMe bool,
	mediaType, filename, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64,
	quotedMessageId string) error {
	return store.StoreMessageWithIdentity(
		id, chatJID, sender, content, timestamp, isFromMe, mediaType, filename, url,
		mediaKey, fileSHA256, fileEncSHA256, fileLength, quotedMessageId, MessageIdentity{},
	)
}

func nullableIdentity(value string) interface{} {
	if value == "" {
		return nil
	}
	return value
}

func (store *MessageStore) StoreMessageWithIdentity(id, chatJID, sender, content string, timestamp time.Time, isFromMe bool,
	mediaType, filename, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64,
	quotedMessageId string, identity MessageIdentity) error {
	return storeMessageWithIdentity(
		store.db, id, chatJID, sender, content, timestamp, isFromMe,
		mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength,
		quotedMessageId, identity,
	)
}

type messageStoreExecutor interface {
	Exec(query string, args ...any) (sql.Result, error)
}

func storeMessageWithIdentity(executor messageStoreExecutor, id, chatJID, sender, content string, timestamp time.Time, isFromMe bool,
	mediaType, filename, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64,
	quotedMessageId string, identity MessageIdentity) error {
	// Only store if there's actual content or media
	if content == "" && mediaType == "" {
		return nil
	}
	if identity.State == "" {
		identity.State = IdentityAmbiguous
	}
	if identity.ChatState == "" {
		identity.ChatState = IdentityUnresolved
	}

	// Store empty quoted_message_id as SQL NULL so the column is null for
	// plain messages (no ContextInfo). This makes the ON CONFLICT merge
	// straightforward: COALESCE prefers the new non-null value over a
	// kept null, and ignores an incoming null so it cannot clobber a
	// previously-stored ID.
	var qmid interface{}
	if quotedMessageId != "" {
		qmid = quotedMessageId
	}

	_, err := executor.Exec(
		`INSERT INTO messages
		(id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length, quoted_message_id,
		 original_sender_jid, original_chat_jid, group_participant_jid, resolved_sender_jid, resolved_chat_jid,
		 identity_state, chat_identity_state)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(id, chat_jid) DO UPDATE SET
			sender = excluded.sender,
			content = CASE
				WHEN excluded.media_type = 'audio' AND excluded.content = ''
					AND messages.media_type = 'audio' AND messages.content LIKE '[transcript (%'
				THEN messages.content
				ELSE excluded.content
			END,
			timestamp = excluded.timestamp,
			is_from_me = excluded.is_from_me,
			media_type = excluded.media_type,
			filename = excluded.filename,
			url = excluded.url,
			media_key = excluded.media_key,
			file_sha256 = excluded.file_sha256,
			file_enc_sha256 = excluded.file_enc_sha256,
			file_length = excluded.file_length,
			quoted_message_id = COALESCE(excluded.quoted_message_id, messages.quoted_message_id),
			original_sender_jid = COALESCE(messages.original_sender_jid, excluded.original_sender_jid),
			original_chat_jid = COALESCE(messages.original_chat_jid, excluded.original_chat_jid),
			group_participant_jid = COALESCE(messages.group_participant_jid, excluded.group_participant_jid),
			resolved_sender_jid = COALESCE(messages.resolved_sender_jid, excluded.resolved_sender_jid),
			resolved_chat_jid = COALESCE(messages.resolved_chat_jid, excluded.resolved_chat_jid),
			identity_state = CASE
				WHEN messages.identity_state = 'AMBIGUOUS' OR excluded.identity_state = 'AMBIGUOUS' THEN 'AMBIGUOUS'
				WHEN messages.original_sender_jid IS NOT NULL AND excluded.original_sender_jid IS NOT NULL
					AND messages.original_sender_jid <> excluded.original_sender_jid THEN 'AMBIGUOUS'
				WHEN messages.original_chat_jid IS NOT NULL AND excluded.original_chat_jid IS NOT NULL
					AND messages.original_chat_jid <> excluded.original_chat_jid THEN 'AMBIGUOUS'
				WHEN messages.resolved_sender_jid IS NOT NULL AND excluded.resolved_sender_jid IS NOT NULL
					AND messages.resolved_sender_jid <> excluded.resolved_sender_jid THEN 'AMBIGUOUS'
				WHEN excluded.identity_state = 'RESOLVED' THEN 'RESOLVED'
				ELSE messages.identity_state
			END,
			chat_identity_state = CASE
				WHEN messages.chat_identity_state = 'AMBIGUOUS' OR excluded.chat_identity_state = 'AMBIGUOUS' THEN 'AMBIGUOUS'
				WHEN messages.original_chat_jid IS NOT NULL AND excluded.original_chat_jid IS NOT NULL
					AND messages.original_chat_jid <> excluded.original_chat_jid THEN 'AMBIGUOUS'
				WHEN messages.resolved_chat_jid IS NOT NULL AND excluded.resolved_chat_jid IS NOT NULL
					AND messages.resolved_chat_jid <> excluded.resolved_chat_jid THEN 'AMBIGUOUS'
				WHEN excluded.chat_identity_state = 'RESOLVED' THEN 'RESOLVED'
				ELSE messages.chat_identity_state
			END`,
		id, chatJID, sender, content, timestamp, isFromMe, mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength, qmid,
		nullableIdentity(identity.OriginalSenderJID), nullableIdentity(identity.OriginalChatJID),
		nullableIdentity(identity.GroupParticipantJID), nullableIdentity(identity.ResolvedSenderJID),
		nullableIdentity(identity.ResolvedChatJID), identity.State, identity.ChatState,
	)
	return err
}

func (store *MessageStore) StoreLiveMessageWithIdentity(id, chatJID, sender, content string, timestamp time.Time, isFromMe bool,
	mediaType, filename, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64,
	quotedMessageId string, identity MessageIdentity, origin string) error {
	if os.Getenv("WHATSAPP_ACCOUNT_ALIAS") != "wa-01" {
		return store.StoreMessageWithIdentity(
			id, chatJID, sender, content, timestamp, isFromMe,
			mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength,
			quotedMessageId, identity,
		)
	}
	if content == "" && mediaType == "" {
		return nil
	}
	// The native event stream covers person and group chats only. Other chats
	// (status broadcasts, newsletters, broadcast lists) are still stored as
	// messages; they simply have no native event, exactly as before the writer
	// existed. Without this the writer would reject them and roll the message
	// back, silently losing the row.
	if !nativeMessageJIDPattern.MatchString(chatJID) {
		return store.StoreMessageWithIdentity(
			id, chatJID, sender, content, timestamp, isFromMe,
			mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength,
			quotedMessageId, identity,
		)
	}
	tx, err := store.db.Begin()
	if err != nil {
		return fmt.Errorf("begin live message transaction: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := storeMessageWithIdentity(
		tx, id, chatJID, sender, content, timestamp, isFromMe,
		mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength,
		quotedMessageId, identity,
	); err != nil {
		return err
	}
	if err := appendNativeMessageEvent(tx, id, chatJID, content, timestamp, isFromMe, mediaType, filename, identity, origin); err != nil {
		return err
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit live message and native event: %w", err)
	}
	return nil
}

func appendNativeMessageEvent(tx *sql.Tx, messageID, chatJID, content string, timestamp time.Time, isFromMe bool,
	mediaType, filename string, identity MessageIdentity, origin string) error {
	if origin != "live" && origin != "api_send_result" {
		return fmt.Errorf("native event origin is invalid")
	}
	if messageID == "" || len(messageID) > 200 || !nativeMessageJIDPattern.MatchString(chatJID) ||
		!nativeMessageJIDPattern.MatchString(identity.OriginalSenderJID) || timestamp.IsZero() {
		return fmt.Errorf("native event identity is invalid")
	}

	var accountID, streamID, identityState string
	var schemaVersion int
	if err := tx.QueryRow(
		`SELECT account_id, stream_id, identity_state, schema_version
		 FROM native_stream WHERE singleton = 1`,
	).Scan(&accountID, &streamID, &identityState, &schemaVersion); err != nil {
		return fmt.Errorf("native stream binding unavailable: %w", err)
	}
	if accountID != "wa-01" || identityState != "verified_native" || schemaVersion != 1 || streamID == "" {
		return fmt.Errorf("native stream binding is not verified for WA-01")
	}

	direction := "incoming"
	if isFromMe {
		direction = "outgoing"
	}
	kind := "message"
	if mediaType == "reaction" {
		kind = "reaction"
	}

	payloadHash := []byte(nil)
	payloadJSON := []byte(nil)
	if kind == "message" {
		payloadJSON, _ = json.Marshal(map[string]any{
			"message": map[string]any{
				"fields": []map[string]string{{"value": content}},
			},
		})
		sum := sha256.Sum256(payloadJSON)
		payloadHash = sum[:]
	}
	mediaKinds := map[string]string{
		"image": "imageMessage", "video": "videoMessage", "audio": "audioMessage",
		"document": "documentMessage", "sticker": "stickerMessage",
	}
	media := []map[string]any{}
	if protocolKind, ok := mediaKinds[mediaType]; ok {
		media = append(media, map[string]any{
			"kind": map[string]any{"state": "present", "value": protocolKind},
		})
	}
	eventHeader := map[string]any{
		"scope":   map[string]string{"accountId": accountID},
		"account": map[string]string{"streamId": streamID},
		"event": map[string]any{
			"chatJid":   map[string]string{"state": "present", "value": chatJID},
			"senderJid": map[string]string{"state": "present", "value": identity.OriginalSenderJID},
			"direction": map[string]string{"state": "present", "value": direction},
		},
		"flags": map[string]any{
			"forwarded": map[string]any{"state": "present", "value": false},
		},
		"relations": map[string]any{},
		"target":    map[string]any{},
		"media":     media,
	}
	if identity.GroupParticipantJID != "" {
		eventHeader["event"].(map[string]any)["participantJid"] = map[string]string{
			"state": "present", "value": identity.GroupParticipantJID,
		}
	}
	if kind == "message" {
		eventHeader["content"] = map[string]any{
			"text": map[string]any{
				"state": "present",
				"value": map[string]string{"ref": "/message/fields/0/value"},
			},
		}
	}
	if kind == "reaction" {
		eventHeader["target"] = map[string]any{
			"messageId": map[string]string{"state": "present", "value": filename},
		}
	}
	headerJSON, err := json.Marshal(eventHeader)
	if err != nil {
		return fmt.Errorf("marshal native event header: %w", err)
	}
	envelopeHash := sha256.Sum256(headerJSON)
	semanticJSON, err := json.Marshal([]string{
		streamID, chatJID, identity.OriginalSenderJID, messageID, direction,
		timestamp.UTC().Format(time.RFC3339Nano), kind, hex.EncodeToString(payloadHash),
	})
	if err != nil {
		return fmt.Errorf("marshal native event identity: %w", err)
	}
	semanticHash := sha256.Sum256(semanticJSON)
	eventKeyJSON, err := json.Marshal([]string{streamID, chatJID, messageID, kind})
	if err != nil {
		return fmt.Errorf("marshal native event key: %w", err)
	}
	eventKeyHash := sha256.Sum256(eventKeyJSON)
	eventKey := hex.EncodeToString(eventKeyHash[:])
	sourceTime := timestamp.UTC().Format(time.RFC3339Nano)
	ingestedAt := time.Now().UTC().Format(time.RFC3339Nano)

	var existingSequence int64
	err = tx.QueryRow(
		`SELECT event_seq FROM native_events
		 WHERE stream_id = ? AND original_chat_jid = ? AND message_id = ? AND kind = ?
		 ORDER BY event_seq DESC LIMIT 1`,
		streamID, chatJID, messageID, kind,
	).Scan(&existingSequence)
	if err == nil {
		return nil
	}
	if err != sql.ErrNoRows {
		return fmt.Errorf("check existing native event: %w", err)
	}

	if len(payloadHash) > 0 {
		if _, err := tx.Exec(
			`INSERT INTO native_payloads (payload_hash, representation_version, evidence_blob, created_at)
			 VALUES (?, 1, ?, ?)
			 ON CONFLICT(payload_hash) DO NOTHING`,
			payloadHash, payloadJSON, ingestedAt,
		); err != nil {
			return fmt.Errorf("store native event payload: %w", err)
		}
	}
	result, err := tx.Exec(
		`INSERT INTO native_events
		 (stream_id, event_key, occurrence_key, native_event_id, message_id,
		  original_chat_jid, original_sender_jid, kind, origin, source_time,
		  ingested_at, semantic_hash, payload_hash, envelope_hash, prior_event_seq, header_json)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
		 ON CONFLICT(stream_id, event_key) DO NOTHING`,
		streamID, eventKey, eventKey, messageID, messageID, chatJID,
		identity.OriginalSenderJID, kind, origin, sourceTime, ingestedAt,
		semanticHash[:], nullableBytes(payloadHash), envelopeHash[:], string(headerJSON),
	)
	if err != nil {
		return fmt.Errorf("append native message event: %w", err)
	}
	inserted, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("check native event insert: %w", err)
	}
	if inserted == 0 {
		return nil
	}
	eventSeq, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("read native event sequence: %w", err)
	}
	projectionJSON, err := json.Marshal(map[string]string{
		"id": messageID, "chat": chatJID, "source": "live-native-event",
	})
	if err != nil {
		return fmt.Errorf("marshal native event projection state: %w", err)
	}
	if _, err := tx.Exec(
		`INSERT INTO native_projection_state
		 (event_seq, status, attempt_count, last_error_code, next_retry_at, updated_at, projection_json)
		 VALUES (?, 'not_applicable', 0, NULL, NULL, ?, ?)`,
		eventSeq, ingestedAt, string(projectionJSON),
	); err != nil {
		return fmt.Errorf("store native event projection state: %w", err)
	}
	return nil
}

func nullableBytes(value []byte) any {
	if len(value) == 0 {
		return nil
	}
	return value
}

// MarkMessageDeleted records a "delete for everyone" event by stamping
// deleted_at on the target row. Content is preserved on purpose — the
// local DB is an archive, and the value is in knowing the message was
// retracted, not in erasing what was said.
//
// First-revoke-wins: once deleted_at is set, a later REVOKE does not
// overwrite it. Calling this for a message that does not exist (e.g.
// the bridge missed the original) is a silent no-op, not an error.
func (store *MessageStore) MarkMessageDeleted(messageID, chatJID string, deletedAt time.Time) error {
	_, err := store.db.Exec(
		`UPDATE messages SET deleted_at = ?
		 WHERE id = ? AND chat_jid = ? AND deleted_at IS NULL`,
		deletedAt, messageID, chatJID,
	)
	return err
}

// Get messages from a chat
func (store *MessageStore) GetMessages(chatJID string, limit int) ([]Message, error) {
	rows, err := store.db.Query(
		"SELECT sender, content, timestamp, is_from_me, media_type, filename, original_sender_jid, original_chat_jid, group_participant_jid, resolved_sender_jid, resolved_chat_jid, identity_state, chat_identity_state FROM messages WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?",
		chatJID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()

	var messages []Message
	for rows.Next() {
		var msg Message
		var timestamp time.Time
		var originalSender, originalChat, participant, resolvedSender, resolvedChat, identityState, chatIdentityState sql.NullString
		err := rows.Scan(
			&msg.Sender, &msg.Content, &timestamp, &msg.IsFromMe, &msg.MediaType, &msg.Filename,
			&originalSender, &originalChat, &participant, &resolvedSender, &resolvedChat, &identityState, &chatIdentityState,
		)
		if err != nil {
			return nil, err
		}
		msg.Time = timestamp
		msg.OriginalSenderJID = originalSender.String
		msg.OriginalChatJID = originalChat.String
		msg.GroupParticipantJID = participant.String
		msg.ResolvedSenderJID = resolvedSender.String
		msg.ResolvedChatJID = resolvedChat.String
		msg.IdentityState = identityState.String
		msg.ChatIdentityState = chatIdentityState.String
		messages = append(messages, msg)
	}

	return messages, nil
}

// Call storage methods.
//
// WhatsApp calls arrive as a sequence of events: Offer/OfferNotice → Accept →
// Terminate (or Reject → Terminate). We model each call as a single row keyed
// by (call_id, chat_jid), upserted as events arrive. The `result` column
// tracks the call's final state as the event sequence plays out.
//
// State machine:
//   Offer/OfferNotice → result = "in_progress"
//   Accept            → result = "answered"
//   Reject            → result = "rejected"
//   Terminate         → if result == "in_progress" → "missed"
//                       if result == "answered"    → "ended"
//                       otherwise preserve existing (rejected stays rejected)

// StoreCallOffer inserts a new call row when an offer event arrives. Uses
// INSERT OR IGNORE so duplicate offer events (rare but possible) don't clobber
// a call already in a later lifecycle state.
func (store *MessageStore) StoreCallOffer(callID, chatJID, fromJID string, timestamp time.Time, isFromMe bool, callType string, isGroup bool) error {
	_, err := store.db.Exec(
		`INSERT OR IGNORE INTO calls
		 (call_id, chat_jid, from_jid, timestamp, is_from_me, call_type, is_group, result)
		 VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress')`,
		callID, chatJID, fromJID, timestamp, isFromMe, callType, isGroup,
	)
	return err
}

// MarkCallAnswered records that the offer was accepted.
func (store *MessageStore) MarkCallAnswered(callID, chatJID string) error {
	_, err := store.db.Exec(
		`UPDATE calls SET result = 'answered'
		 WHERE call_id = ? AND chat_jid = ? AND result = 'in_progress'`,
		callID, chatJID,
	)
	return err
}

// MarkCallRejected records that the call was explicitly rejected.
func (store *MessageStore) MarkCallRejected(callID, chatJID string) error {
	_, err := store.db.Exec(
		`UPDATE calls SET result = 'rejected'
		 WHERE call_id = ? AND chat_jid = ? AND result = 'in_progress'`,
		callID, chatJID,
	)
	return err
}

// MarkCallTerminated records the end of a call, computing duration from the
// offer timestamp. Infers final result when the call was still in_progress
// (meaning no accept was seen → the call was missed).
func (store *MessageStore) MarkCallTerminated(callID, chatJID, reason string, endedAt time.Time) error {
	// ROUND before CAST: julianday() arithmetic produces a float and CAST truncates
	// toward zero, so a 90-second call would otherwise record as 89.
	_, err := store.db.Exec(
		`UPDATE calls SET
			ended_at = ?,
			duration_sec = CAST(ROUND((julianday(?) - julianday(timestamp)) * 86400) AS INTEGER),
			reason = ?,
			result = CASE result
				WHEN 'in_progress' THEN 'missed'
				WHEN 'answered'    THEN 'ended'
				ELSE result
			END
		 WHERE call_id = ? AND chat_jid = ?`,
		endedAt, endedAt, reason, callID, chatJID,
	)
	return err
}

// Get all chats
func (store *MessageStore) GetChats() (map[string]time.Time, error) {
	rows, err := store.db.Query("SELECT jid, last_message_time FROM chats ORDER BY last_message_time DESC")
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()

	chats := make(map[string]time.Time)
	for rows.Next() {
		var jid string
		// last_message_time can be NULL — UpdateChatEphemeralSettings can
		// create a chat row from a GroupInfo / ephemeral-setting event
		// before any message has landed for that chat.
		var lastMessageTime sql.NullTime
		err := rows.Scan(&jid, &lastMessageTime)
		if err != nil {
			return nil, err
		}
		if lastMessageTime.Valid {
			chats[jid] = lastMessageTime.Time
		} else {
			chats[jid] = time.Time{}
		}
	}

	return chats, nil
}

// Extract text content from a message
func extractTextContent(msg *waProto.Message) string {
	if msg == nil {
		return ""
	}

	// Try to get text content
	if text := msg.GetConversation(); text != "" {
		return text
	} else if extendedText := msg.GetExtendedTextMessage(); extendedText != nil {
		return extendedText.GetText()
	}

	// Captions on media messages — surface them as searchable content
	// alongside the media itself. Audio messages don't carry captions.
	if img := msg.GetImageMessage(); img != nil {
		return img.GetCaption()
	}
	if vid := msg.GetVideoMessage(); vid != nil {
		return vid.GetCaption()
	}
	if doc := msg.GetDocumentMessage(); doc != nil {
		return doc.GetCaption()
	}

	// WhatsApp Business templates arrive hydrated — body lives in
	// HydratedTemplate.HydratedContentText. Without this branch every
	// template-sent message (e.g. WABA Connect Hrms_* notifications)
	// returns "" and the row is silently skipped at the storage gate.
	if tpl := msg.GetTemplateMessage(); tpl != nil {
		if h := tpl.GetHydratedTemplate(); h != nil {
			if t := h.GetHydratedContentText(); t != "" {
				return t
			}
		}
	}
	if btn := msg.GetButtonsMessage(); btn != nil {
		if t := btn.GetContentText(); t != "" {
			return t
		}
		if t := btn.GetText(); t != "" {
			return t
		}
	}
	if ia := msg.GetInteractiveMessage(); ia != nil {
		if body := ia.GetBody(); body != nil {
			if t := body.GetText(); t != "" {
				return t
			}
		}
	}
	if lst := msg.GetListMessage(); lst != nil {
		if t := lst.GetDescription(); t != "" {
			return t
		}
	}
	if br := msg.GetButtonsResponseMessage(); br != nil {
		if t := br.GetSelectedDisplayText(); t != "" {
			return t
		}
	}
	if tbr := msg.GetTemplateButtonReplyMessage(); tbr != nil {
		if t := tbr.GetSelectedDisplayText(); t != "" {
			return t
		}
	}

	return ""
}

// SendMessageResponse represents the response for the send message API
type SendMessageResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

// SendMessageRequest represents the request body for the send message API
type SendMessageRequest struct {
	Recipient       string `json:"recipient"`
	Message         string `json:"message"`
	MediaPath       string `json:"media_path,omitempty"`
	QuotedMessageID string `json:"quoted_message_id,omitempty"`
	QuotedSenderJID string `json:"quoted_sender_jid,omitempty"`
	QuotedContent   string `json:"quoted_content,omitempty"`
	// Mentions lists users to @-mention (phone numbers or JIDs). The message
	// text must contain a matching "@<number>" token for each entry, or the
	// mention won't render on recipients' devices.
	Mentions []string `json:"mentions,omitempty"`
}

// MarkReadRequest is the request body for the /api/mark-read endpoint.
type MarkReadRequest struct {
	MessageIDs []string `json:"message_ids"`
	ChatJID    string   `json:"chat_jid"`
	SenderJID  string   `json:"sender_jid,omitempty"`
	Timestamp  string   `json:"timestamp,omitempty"`
}

// ReactRequest is the request body for the /api/react endpoint.
type ReactRequest struct {
	Recipient string  `json:"recipient"`  // chat JID
	MessageID string  `json:"message_id"` // ID of the message being reacted to
	FromMe    bool    `json:"from_me"`    // whether the reacted-to message was sent by us
	SenderJID string  `json:"sender_jid"` // full JID of the reacted-to message's sender
	Emoji     *string `json:"emoji"`      // reaction emoji; empty string removes the reaction
}

// classifyMediaPath maps a file extension to (whatsmeow upload type, MIME
// type, persist-side category). Single source of truth for the upload path
// (which needs the whatsmeow.MediaType + MIME) and the SQLite persist path
// (which stores the short category string).
func classifyMediaPath(mediaPath string) (whatsmeow.MediaType, string, string) {
	ext := strings.ToLower(strings.TrimPrefix(filepath.Ext(mediaPath), "."))
	switch ext {
	case "jpg", "jpeg":
		return whatsmeow.MediaImage, "image/jpeg", "image"
	case "png":
		return whatsmeow.MediaImage, "image/png", "image"
	case "gif":
		return whatsmeow.MediaImage, "image/gif", "image"
	case "webp":
		return whatsmeow.MediaImage, "image/webp", "image"
	case "ogg":
		return whatsmeow.MediaAudio, "audio/ogg; codecs=opus", "audio"
	case "mp4":
		return whatsmeow.MediaVideo, "video/mp4", "video"
	case "avi":
		return whatsmeow.MediaVideo, "video/avi", "video"
	case "mov":
		return whatsmeow.MediaVideo, "video/quicktime", "video"
	default:
		if m := mime.TypeByExtension("." + ext); m != "" {
			return whatsmeow.MediaDocument, m, "document"
		}
		return whatsmeow.MediaDocument, "application/octet-stream", "document"
	}
}

// outboundMediaRow derives the columns sendWhatsAppMessage persists for an
// outbound message: the media category (via classifyMediaPath, so it can't
// drift from the upload-side classification), the filename, and the upload
// metadata downloadMedia needs to redownload it later. Returns zero values
// for a plain text message (mediaPath == ""). Split out as its own function
// so it's unit-testable without a live whatsmeow.Client.
func outboundMediaRow(mediaPath string, upload whatsmeow.UploadResponse) (mediaType, filename, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64) {
	if mediaPath == "" {
		return "", "", "", nil, nil, nil, 0
	}
	_, _, mediaType = classifyMediaPath(mediaPath)
	filename = filepath.Base(mediaPath)
	return mediaType, filename, upload.URL, upload.MediaKey, upload.FileSHA256, upload.FileEncSHA256, upload.FileLength
}

func buildDisappearingMode() *waProto.DisappearingMode {
	return &waProto.DisappearingMode{
		Initiator: waProto.DisappearingMode_CHANGED_IN_CHAT.Enum(),
		Trigger:   waProto.DisappearingMode_CHAT_SETTING.Enum(),
	}
}

func mergeEphemeralContextInfo(existing *waProto.ContextInfo, settings ChatEphemeralSettings) *waProto.ContextInfo {
	if existing == nil {
		existing = &waProto.ContextInfo{}
	}
	existing.Expiration = proto.Uint32(settings.Expiration)
	existing.EphemeralSettingTimestamp = proto.Int64(settings.SettingTimestamp)
	existing.DisappearingMode = buildDisappearingMode()
	return existing
}

func applyChatEphemeralSettings(msg *waProto.Message, settings ChatEphemeralSettings) {
	if msg == nil || settings.Expiration == 0 || settings.SettingTimestamp == 0 {
		return
	}

	switch {
	case msg.ExtendedTextMessage != nil:
		msg.ExtendedTextMessage.ContextInfo = mergeEphemeralContextInfo(msg.ExtendedTextMessage.GetContextInfo(), settings)
	case msg.ImageMessage != nil:
		msg.ImageMessage.ContextInfo = mergeEphemeralContextInfo(msg.ImageMessage.GetContextInfo(), settings)
	case msg.AudioMessage != nil:
		msg.AudioMessage.ContextInfo = mergeEphemeralContextInfo(msg.AudioMessage.GetContextInfo(), settings)
	case msg.VideoMessage != nil:
		msg.VideoMessage.ContextInfo = mergeEphemeralContextInfo(msg.VideoMessage.GetContextInfo(), settings)
	case msg.DocumentMessage != nil:
		msg.DocumentMessage.ContextInfo = mergeEphemeralContextInfo(msg.DocumentMessage.GetContextInfo(), settings)
	case msg.Conversation != nil:
		text := msg.GetConversation()
		msg.Conversation = nil
		msg.ExtendedTextMessage = &waProto.ExtendedTextMessage{
			Text:        proto.String(text),
			ContextInfo: mergeEphemeralContextInfo(nil, settings),
		}
	}
}

// extractChatEphemeralFromMessage reads the chat's ephemeral state off an
// inbound message's ContextInfo. Every regular message in an ephemeral chat
// stamps Expiration / EphemeralSettingTimestamp on the sub-message's
// ContextInfo, which lets the bridge backfill chats whose disappearing state
// was set before the bridge ever saw an EPHEMERAL_SETTING toggle or a
// fresh history sync. Returns the zero ChatEphemeralSettings when no
// ContextInfo is present (e.g. plain Conversation, ProtocolMessage).
func extractChatEphemeralFromMessage(msg *waProto.Message) ChatEphemeralSettings {
	if msg == nil {
		return ChatEphemeralSettings{}
	}
	var ctx *waProto.ContextInfo
	switch {
	case msg.ExtendedTextMessage != nil:
		ctx = msg.ExtendedTextMessage.GetContextInfo()
	case msg.ImageMessage != nil:
		ctx = msg.ImageMessage.GetContextInfo()
	case msg.AudioMessage != nil:
		ctx = msg.AudioMessage.GetContextInfo()
	case msg.VideoMessage != nil:
		ctx = msg.VideoMessage.GetContextInfo()
	case msg.DocumentMessage != nil:
		ctx = msg.DocumentMessage.GetContextInfo()
	case msg.StickerMessage != nil:
		ctx = msg.StickerMessage.GetContextInfo()
	}
	if ctx == nil {
		return ChatEphemeralSettings{}
	}
	return ChatEphemeralSettings{
		Expiration:       ctx.GetExpiration(),
		SettingTimestamp: ctx.GetEphemeralSettingTimestamp(),
	}
}

func updateChatEphemeralSettingsFromProtocolMessage(messageStore *MessageStore, chatJID string, msg *waProto.Message, eventTimestamp int64, logger waLog.Logger) {
	if msg == nil || msg.GetProtocolMessage() == nil {
		return
	}

	protoMsg := msg.GetProtocolMessage()
	if protoMsg.GetType() != waProto.ProtocolMessage_EPHEMERAL_SETTING {
		return
	}

	expiration := protoMsg.GetEphemeralExpiration()
	settingTimestamp := protoMsg.GetEphemeralSettingTimestamp()
	// Fall back to the carrier event's timestamp rather than time.Now() so a
	// late-arriving older event doesn't get stamped "newer than" subsequent
	// updates and then block them via the monotonic WHERE clause in
	// UpdateChatEphemeralSettings.
	if settingTimestamp == 0 {
		settingTimestamp = eventTimestamp
	}

	if err := messageStore.UpdateChatEphemeralSettings(chatJID, expiration, settingTimestamp); err != nil {
		logger.Warnf("Failed to update ephemeral settings")
	}
}

// handleMessageRevoke records a "delete for everyone" event by stamping
// deleted_at on the target message row. The original content is kept on
// purpose so the local archive can still surface what was retracted.
//
// chatJID is the already-LID-normalised chat from the carrier event;
// using it (rather than Key.RemoteJID, which may carry the raw @lid
// form) keeps the UPDATE aligned with how StoreMessage wrote the row.
func handleMessageRevoke(messageStore *MessageStore, msg *waProto.Message, chatJID string, eventTimestamp int64, logger waLog.Logger) {
	if msg == nil || msg.GetProtocolMessage() == nil {
		return
	}
	protoMsg := msg.GetProtocolMessage()
	if protoMsg.GetType() != waProto.ProtocolMessage_REVOKE {
		return
	}
	key := protoMsg.GetKey()
	if key == nil {
		return
	}
	targetID := key.GetID()
	if targetID == "" {
		return
	}
	deletedAt := time.Unix(eventTimestamp, 0)
	if err := messageStore.MarkMessageDeleted(targetID, chatJID, deletedAt); err != nil {
		logger.Warnf("Failed to mark message deleted")
	}
}

// resolveRecipientJID parses a phone number or JID string and resolves PN -> LID
// for personal chats before sending.
func resolveRecipientJID(client *whatsmeow.Client, recipient string) (types.JID, error) {
	var recipientJID types.JID
	var err error

	if strings.Contains(recipient, "@") {
		recipientJID, err = types.ParseJID(recipient)
		if err != nil {
			return types.JID{}, fmt.Errorf("Error parsing JID: %v", err)
		}
	} else {
		recipientJID = types.JID{
			User:   recipient,
			Server: "s.whatsapp.net", // For personal chats
		}
	}

	// For personal chats, resolve phone number JID to LID (Linked Identity).
	// WhatsApp is migrating to LID-based addressing; messages sent to the
	// phone JID silently fail for migrated contacts.
	if recipientJID.Server == types.DefaultUserServer {
		ctx := context.Background()
		lid, lidErr := client.Store.LIDs.GetLIDForPN(ctx, recipientJID)
		if lidErr == nil && !lid.IsEmpty() {
			fmt.Println("Resolved recipient to LID (cache)")
			recipientJID = lid
		} else {
			// Cache miss or cache error — ask the WhatsApp server.
			if lidErr != nil {
				fmt.Println("Warning: LID cache lookup failed; falling back to server")
			}
			info, infoErr := client.GetUserInfo(ctx, []types.JID{recipientJID})
			if infoErr != nil {
				fmt.Println("Warning: server LID lookup failed")
			} else if userInfo, ok := info[recipientJID]; ok && !userInfo.LID.IsEmpty() {
				fmt.Println("Resolved recipient to LID (server)")
				recipientJID = userInfo.LID
			}
		}
	}

	return recipientJID, nil
}

// resolveMentionJIDs maps mention entries (phone numbers or JIDs) to the JID
// strings WhatsApp expects in ContextInfo.MentionedJID. Phone-number entries
// contribute both the phone JID and, when known, its LID form so the mention
// renders regardless of the group's addressing mode.
func resolveMentionJIDs(client *whatsmeow.Client, mentions []string) []string {
	var resolved []string
	for _, mention := range mentions {
		var jid types.JID
		if strings.Contains(mention, "@") {
			parsed, err := types.ParseJID(mention)
			if err != nil {
				fmt.Println("Warning: skipping unparseable mention")
				continue
			}
			jid = parsed
		} else {
			jid = types.JID{User: mention, Server: types.DefaultUserServer}
		}
		resolved = append(resolved, jid.String())
		if jid.Server == types.DefaultUserServer {
			if lid, err := client.Store.LIDs.GetLIDForPN(context.Background(), jid); err == nil && !lid.IsEmpty() {
				resolved = append(resolved, lid.String())
			}
		}
	}
	return resolved
}

// Function to send a WhatsApp message
func sendWhatsAppMessage(client *whatsmeow.Client, messageStore *MessageStore, recipient string, message string, mediaPath string, quotedMsgID string, quotedSenderJID string, quotedContent string, mentions []string) (bool, string) {
	if !client.IsConnected() {
		return false, "Not connected to WhatsApp"
	}

	mentionedJIDs := resolveMentionJIDs(client, mentions)

	var settingsLookupJID types.JID
	var err error

	if strings.Contains(recipient, "@") {
		settingsLookupJID, err = types.ParseJID(recipient)
		if err != nil {
			return false, fmt.Sprintf("Error parsing JID: %v", err)
		}
	} else {
		settingsLookupJID = types.JID{
			User:   recipient,
			Server: "s.whatsapp.net", // For personal chats
		}
	}

	// Capture pre-LID-resolution JID for SQLite storage.
	// handleMessage uses resolveLIDChat to map LID→phone for incoming events;
	// for outbound we keep the pre-resolution form so the chat stays unified
	// under @s.whatsapp.net (matches what list_chats / list_messages expect).
	storageJID := settingsLookupJID

	recipientJID, err := resolveRecipientJID(client, recipient)
	if err != nil {
		return false, err.Error()
	}

	msg := &waProto.Message{}

	// Populated below when mediaPath != "", then reused both to build the
	// outgoing proto and to persist media metadata further down.
	var upload whatsmeow.UploadResponse

	// Check if we have media to send
	if mediaPath != "" {
		// Read media file
		mediaData, err := os.ReadFile(mediaPath)
		if err != nil {
			return false, fmt.Sprintf("Error reading media file: %v", err)
		}

		mediaType, mimeType, _ := classifyMediaPath(mediaPath)

		// Upload media to WhatsApp servers
		upload, err = client.Upload(context.Background(), mediaData, mediaType)
		if err != nil {
			return false, fmt.Sprintf("Error uploading media: %v", err)
		}

		// Don't log the struct itself — UploadResponse carries the MediaKey
		// and a signed CDN URL with authentication query parameters.
		fmt.Printf("Media uploaded (%d bytes)\n", upload.FileLength)

		// downloadMedia reconstructs DirectPath from the stored URL instead
		// of persisting it directly (no column for it). extractDirectPathFromURL
		// keeps the URL's query string on purpose (the CDN auth tokens); strip
		// it from both sides before comparing so this only fires on an actual
		// mismatch, not the query string that's expected to differ.
		derivedPath, _, _ := strings.Cut(extractDirectPathFromURL(upload.URL), "?")
		directPath, _, _ := strings.Cut(upload.DirectPath, "?")
		if derivedPath != directPath {
			fmt.Printf("Warning: upload path does not match derived download path; redownload of this attachment may fail\n")
		}

		// Create the appropriate message type based on media type
		switch mediaType {
		case whatsmeow.MediaImage:
			msg.ImageMessage = &waProto.ImageMessage{
				Caption:       proto.String(message),
				Mimetype:      proto.String(mimeType),
				URL:           &upload.URL,
				DirectPath:    &upload.DirectPath,
				MediaKey:      upload.MediaKey,
				FileEncSHA256: upload.FileEncSHA256,
				FileSHA256:    upload.FileSHA256,
				FileLength:    &upload.FileLength,
			}
		case whatsmeow.MediaAudio:
			// Handle ogg audio files
			var seconds uint32 = 30 // Default fallback
			var waveform []byte = nil

			// Try to analyze the ogg file
			if strings.Contains(mimeType, "ogg") {
				analyzedSeconds, analyzedWaveform, err := analyzeOggOpus(mediaData)
				if err == nil {
					seconds = analyzedSeconds
					waveform = analyzedWaveform
				} else {
					return false, fmt.Sprintf("Failed to analyze Ogg Opus file: %v", err)
				}
			} else {
				fmt.Printf("Not an Ogg Opus file: %s\n", mimeType)
			}

			msg.AudioMessage = &waProto.AudioMessage{
				Mimetype:      proto.String(mimeType),
				URL:           &upload.URL,
				DirectPath:    &upload.DirectPath,
				MediaKey:      upload.MediaKey,
				FileEncSHA256: upload.FileEncSHA256,
				FileSHA256:    upload.FileSHA256,
				FileLength:    &upload.FileLength,
				Seconds:       proto.Uint32(seconds),
				PTT:           proto.Bool(true),
				Waveform:      waveform,
			}
		case whatsmeow.MediaVideo:
			msg.VideoMessage = &waProto.VideoMessage{
				Caption:       proto.String(message),
				Mimetype:      proto.String(mimeType),
				URL:           &upload.URL,
				DirectPath:    &upload.DirectPath,
				MediaKey:      upload.MediaKey,
				FileEncSHA256: upload.FileEncSHA256,
				FileSHA256:    upload.FileSHA256,
				FileLength:    &upload.FileLength,
			}
		case whatsmeow.MediaDocument:
			msg.DocumentMessage = &waProto.DocumentMessage{
				// outboundFileName, not a manual split on "/": the document
				// filename travels to the recipient, and on Windows the path
				// is already backslash-normalised, so the naive split leaks
				// the whole absolute path. See media_path.go.
				Title:         proto.String(outboundFileName(mediaPath)),
				FileName:      proto.String(outboundFileName(mediaPath)),
				Caption:       proto.String(message),
				Mimetype:      proto.String(mimeType),
				URL:           &upload.URL,
				DirectPath:    &upload.DirectPath,
				MediaKey:      upload.MediaKey,
				FileEncSHA256: upload.FileEncSHA256,
				FileSHA256:    upload.FileSHA256,
				FileLength:    &upload.FileLength,
			}
		default:
			// Unreachable today (classifyMediaPath only returns the four
			// types above), but fail loudly rather than send an empty proto
			// while still persisting media metadata for it.
			return false, fmt.Sprintf("Unsupported media type for %s", mediaPath)
		}
	} else if quotedMsgID != "" || len(mentionedJIDs) > 0 {
		// Quoted reply and/or mentions: use ExtendedTextMessage so we can
		// attach ContextInfo. Only text quoting is supported; quoting media
		// messages is not exposed because the quoted preview on the
		// recipient's device requires the original media's key/URL, which is
		// not available to the API caller.
		ctx := &waProto.ContextInfo{}
		if quotedMsgID != "" {
			ctx.StanzaID = proto.String(quotedMsgID)
			ctx.Participant = proto.String(quotedSenderJID)
			ctx.QuotedMessage = &waProto.Message{Conversation: proto.String(quotedContent)}
		}
		ctx.MentionedJID = mentionedJIDs
		msg.ExtendedTextMessage = &waProto.ExtendedTextMessage{
			Text:        proto.String(message),
			ContextInfo: ctx,
		}
	} else {
		msg.Conversation = proto.String(message)
	}

	// Mentions in media captions live on the media message's own ContextInfo.
	if len(mentionedJIDs) > 0 {
		switch {
		case msg.ImageMessage != nil:
			msg.ImageMessage.ContextInfo = &waProto.ContextInfo{MentionedJID: mentionedJIDs}
		case msg.VideoMessage != nil:
			msg.VideoMessage.ContextInfo = &waProto.ContextInfo{MentionedJID: mentionedJIDs}
		case msg.DocumentMessage != nil:
			msg.DocumentMessage.ContextInfo = &waProto.ContextInfo{MentionedJID: mentionedJIDs}
		}
	}

	// Normalize @lid recipients to phone JID before the lookup. Chats are
	// persisted under @s.whatsapp.net (handleMessage normalizes via
	// resolveLIDChat); without this step, an API caller passing an @lid
	// recipient would silently miss the disappearing-message settings row.
	settings, err := messageStore.GetChatEphemeralSettings(resolveUserJID(client, settingsLookupJID, types.EmptyJID).String())
	if err != nil && err != sql.ErrNoRows {
		return false, fmt.Sprintf("Error loading chat settings: %v", err)
	}
	if err == nil {
		applyChatEphemeralSettings(msg, settings)
	}

	// Send message
	resp, err := client.SendMessage(context.Background(), recipientJID, msg)

	if err != nil {
		return false, fmt.Sprintf("Error sending message: %v", err)
	}

	// whatsmeow does not re-emit events.Message for messages this client
	// itself just sent, so without an explicit StoreMessage call here
	// list_messages / get_last_interaction never see our own outbound
	// traffic until WhatsApp's multi-device sync echoes them back.
	if messageStore != nil && client.Store != nil && client.Store.ID != nil {
		// Keep the existing normalized chat key for compatibility, while
		// retaining the caller-supplied JID and verified identity separately.
		persistJID := resolveUserJID(client, storageJID, types.EmptyJID)
		chatJID := persistJID.String()
		senderUser := client.Store.ID.User
		originalSenderJID := client.Store.ID.ToNonAD()
		senderIdentity := resolveIdentityJID(client, originalSenderJID, types.EmptyJID)
		messageIdentity := MessageIdentity{
			OriginalSenderJID: originalSenderJID.String(),
			OriginalChatJID:   storageJID.ToNonAD().String(),
			ResolvedSenderJID: senderIdentity.ResolvedJID,
			State:             senderIdentity.State,
			ChatState:         IdentityUnresolved,
		}
		if storageJID.Server == types.DefaultUserServer || storageJID.Server == types.HiddenUserServer {
			chatIdentity := resolveIdentityJID(client, storageJID, types.EmptyJID)
			messageIdentity.ResolvedChatJID = chatIdentity.ResolvedJID
			messageIdentity.ChatState = chatIdentity.State
		}
		if storageJID.Server == types.GroupServer {
			messageIdentity.GroupParticipantJID = originalSenderJID.String()
		}
		timestamp := resp.Timestamp
		if timestamp.IsZero() {
			timestamp = time.Now()
		}

		mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := outboundMediaRow(mediaPath, upload)

		// Pass empty name so StoreChat preserves any existing resolved
		// contact/group name; we don't have one available here and
		// must not clobber names from inbound handling or history sync.
		if chatErr := messageStore.StoreChat(chatJID, "", timestamp); chatErr != nil {
			fmt.Println("Warning: failed to store outbound chat metadata")
		}
		if storeErr := messageStore.StoreLiveMessageWithIdentity(
			resp.ID, chatJID, senderUser, message, timestamp, true,
			mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength, quotedMsgID,
			messageIdentity, "api_send_result",
		); storeErr != nil {
			fmt.Println("Warning: failed to persist outbound message")
		}
	}

	return true, fmt.Sprintf("Message sent to %s", recipient)
}

// Extract quoted message info from ContextInfo
func extractQuotedMessageInfo(msg *waProto.Message) (quotedMessageId string, quotedSender string, quotedContent string) {
	if msg == nil {
		return "", "", ""
	}

	var contextInfo *waProto.ContextInfo

	// Check all message types that can have ContextInfo
	if extText := msg.GetExtendedTextMessage(); extText != nil {
		contextInfo = extText.GetContextInfo()
	} else if img := msg.GetImageMessage(); img != nil {
		contextInfo = img.GetContextInfo()
	} else if vid := msg.GetVideoMessage(); vid != nil {
		contextInfo = vid.GetContextInfo()
	} else if doc := msg.GetDocumentMessage(); doc != nil {
		contextInfo = doc.GetContextInfo()
	} else if aud := msg.GetAudioMessage(); aud != nil {
		contextInfo = aud.GetContextInfo()
	}

	if contextInfo == nil {
		return "", "", ""
	}

	// Extract quoted message ID (StanzaID)
	if contextInfo.StanzaID != nil {
		quotedMessageId = *contextInfo.StanzaID
	}

	// Extract quoted sender (Participant)
	if contextInfo.Participant != nil {
		quotedSender = *contextInfo.Participant
	}

	// Extract quoted message content
	if quotedMsg := contextInfo.QuotedMessage; quotedMsg != nil {
		quotedContent = extractTextContent(quotedMsg)
	}

	return quotedMessageId, quotedSender, quotedContent
}

// extractMentionedJIDs returns native WhatsApp mention targets from ContextInfo.
func extractMentionedJIDs(msg *waProto.Message) []string {
	if msg == nil {
		return nil
	}

	var contextInfo *waProto.ContextInfo
	if extText := msg.GetExtendedTextMessage(); extText != nil {
		contextInfo = extText.GetContextInfo()
	} else if img := msg.GetImageMessage(); img != nil {
		contextInfo = img.GetContextInfo()
	} else if vid := msg.GetVideoMessage(); vid != nil {
		contextInfo = vid.GetContextInfo()
	} else if doc := msg.GetDocumentMessage(); doc != nil {
		contextInfo = doc.GetContextInfo()
	} else if aud := msg.GetAudioMessage(); aud != nil {
		contextInfo = aud.GetContextInfo()
	}

	if contextInfo == nil || len(contextInfo.MentionedJID) == 0 {
		return nil
	}

	return append([]string(nil), contextInfo.MentionedJID...)
}

// Extract media info from a message. Filenames embed the message ID so that
// two messages arriving in the same second do not collide on a single file.
func extractMediaInfo(msg *waProto.Message, msgTimestamp time.Time, msgID string) (mediaType string, filename string, url string, mediaKey []byte, fileSHA256 []byte, fileEncSHA256 []byte, fileLength uint64) {
	if msg == nil {
		return "", "", "", nil, nil, nil, 0
	}

	// Use message timestamp for filename, fallback to current time if zero
	ts := msgTimestamp
	if ts.IsZero() {
		ts = time.Now()
	}
	tsStr := ts.Format("20060102_150405")
	suffix := tsStr
	if msgID != "" {
		suffix = tsStr + "_" + msgID
	}

	// Check for image message
	if img := msg.GetImageMessage(); img != nil {
		return "image", "image_" + suffix + ".jpg",
			img.GetURL(), img.GetMediaKey(), img.GetFileSHA256(), img.GetFileEncSHA256(), img.GetFileLength()
	}

	// Check for video message
	if vid := msg.GetVideoMessage(); vid != nil {
		return "video", "video_" + suffix + ".mp4",
			vid.GetURL(), vid.GetMediaKey(), vid.GetFileSHA256(), vid.GetFileEncSHA256(), vid.GetFileLength()
	}

	// Check for audio message
	if aud := msg.GetAudioMessage(); aud != nil {
		return "audio", "audio_" + suffix + ".ogg",
			aud.GetURL(), aud.GetMediaKey(), aud.GetFileSHA256(), aud.GetFileEncSHA256(), aud.GetFileLength()
	}

	// Check for document message
	if doc := msg.GetDocumentMessage(); doc != nil {
		filename := doc.GetFileName()
		if filename == "" {
			filename = "document_" + suffix
		}
		return "document", filename,
			doc.GetURL(), doc.GetMediaKey(), doc.GetFileSHA256(), doc.GetFileEncSHA256(), doc.GetFileLength()
	}

	// Sticker message: WebP image, no caption, same URL+MediaKey+SHA shape as other media.
	// On the wire stickers surface as type="media" with an <enc mediatype="sticker"> payload, e.g.:
	//   <message id="..." type="media">
	//     <enc mediatype="sticker" type="msg" v="2"><!-- 660 bytes --></enc>
	//   </message>
	if stk := msg.GetStickerMessage(); stk != nil {
		return "sticker", "sticker_" + suffix + ".webp",
			stk.GetURL(), stk.GetMediaKey(), stk.GetFileSHA256(), stk.GetFileEncSHA256(), stk.GetFileLength()
	}

	return "", "", "", nil, nil, nil, 0
}

func resolveIdentityJID(client *whatsmeow.Client, jid, alternate types.JID) ResolvedIdentity {
	original := jid.ToNonAD()
	resolution := ResolvedIdentity{
		OriginalJID: original.String(),
		State:       IdentityUnresolved,
	}

	switch original.Server {
	case types.DefaultUserServer:
		if original.User == "" {
			resolution.State = IdentityAmbiguous
			return resolution
		}
		resolution.PN = original.User
		resolution.ResolvedJID = original.String()
		resolution.State = IdentityResolved
		return resolution
	case types.HiddenUserServer:
		if original.User == "" {
			resolution.State = IdentityAmbiguous
			return resolution
		}
		resolution.LID = original.User
	default:
		resolution.State = IdentityAmbiguous
		return resolution
	}

	var altPN, mappedPN types.JID
	if !alternate.IsEmpty() && alternate.Server == types.DefaultUserServer && alternate.User != "" {
		altPN = alternate.ToNonAD()
	}
	if client != nil && client.Store != nil && client.Store.LIDs != nil {
		if pn, err := client.Store.LIDs.GetPNForLID(context.Background(), original); err == nil &&
			!pn.IsEmpty() && pn.Server == types.DefaultUserServer && pn.User != "" {
			mappedPN = pn.ToNonAD()
		}
	}
	if !altPN.IsEmpty() && !mappedPN.IsEmpty() && altPN != mappedPN {
		fmt.Println("LID identity resolution conflict (message alternate and LID store)")
		resolution.State = IdentityAmbiguous
		return resolution
	}
	verifiedPN := mappedPN
	if verifiedPN.IsEmpty() {
		verifiedPN = altPN
	}
	if !verifiedPN.IsEmpty() {
		if !mappedPN.IsEmpty() {
			fmt.Println("Resolved identity from LID store")
		} else {
			fmt.Println("Resolved identity from message alternate")
		}
		resolution.PN = verifiedPN.User
		resolution.ResolvedJID = verifiedPN.String()
		resolution.State = IdentityResolved
	}
	return resolution
}

// resolveLIDChat returns a protocol-verified PN alias when available. Message
// persistence must still retain the original chat JID separately.
func resolveLIDChat(client *whatsmeow.Client, chat, senderAlt, recipientAlt types.JID, isFromMe bool) types.JID {
	if chat.Server != types.HiddenUserServer {
		return chat.ToNonAD()
	}
	alternate := senderAlt
	if isFromMe {
		alternate = recipientAlt
	}
	identity := resolveIdentityJID(client, chat, alternate)
	if identity.State != IdentityResolved {
		fmt.Println("Could not resolve LID chat identity")
		return chat.ToNonAD()
	}
	resolved, err := types.ParseJID(identity.ResolvedJID)
	if err != nil {
		fmt.Println("Could not resolve LID chat identity")
		return chat.ToNonAD()
	}
	fmt.Println("Resolved LID chat identity")
	return resolved
}

// isSelfReadReceipt reports whether a receipt means WE read the chat (on this
// or another device), as opposed to another user reading our outgoing message.
// A DM self-read arrives as read-self; a group self-read arrives as a plain
// read whose participant is us (IsFromMe). See types.ReceiptType docs.
func isSelfReadReceipt(receipt *events.Receipt) bool {
	return receipt.Type == types.ReceiptTypeReadSelf ||
		(receipt.Type == types.ReceiptTypeRead && receipt.IsFromMe)
}

// resolveUserJID resolves a single user JID (sender or participant) to its
// phone-based equivalent. Unlike resolveLIDChat it takes a single hint alt
// JID (either SenderAlt for the peer in a DM or the user's own phone JID
// for outgoing messages) so it can never accidentally substitute the
// recipient's identity for the sender's. Falls back to the whatsmeow
// LID-PN store, then returns the original JID if no mapping is known.
func resolveUserJID(client *whatsmeow.Client, j, alt types.JID) types.JID {
	identity := resolveIdentityJID(client, j, alt)
	if identity.State != IdentityResolved {
		return j.ToNonAD()
	}
	resolved, err := types.ParseJID(identity.ResolvedJID)
	if err != nil {
		return j.ToNonAD()
	}
	return resolved
}

// senderAltForMessage returns the best phone-JID hint for the sender of a
// message: SenderAlt for incoming, the user's own phone JID for outgoing.
// Falls through to EmptyJID if no hint is available, in which case
// resolveUserJID will fall back to the LID store.
func senderAltForMessage(client *whatsmeow.Client, info types.MessageInfo) types.JID {
	if info.IsFromMe {
		if client != nil && client.Store != nil && client.Store.ID != nil {
			return client.Store.ID.ToNonAD()
		}
		return types.EmptyJID
	}
	if !info.SenderAlt.IsEmpty() && info.SenderAlt.Server == types.DefaultUserServer {
		return info.SenderAlt.ToNonAD()
	}
	return types.EmptyJID
}

// Handle regular incoming messages with media support
// origMsgTime remembers the true send-time of messages that first arrived
// undecryptable (e.g. after an offline gap, when our session lacked the sender
// key). WhatsApp re-sends such messages after a retry receipt, but the re-sent
// copy carries a fresh `t` (the resend time) rather than the original send time.
// The first (undecryptable) delivery *does* carry the original `t`, so we cache
// it here and reuse it when the decrypted retry finally lands — otherwise those
// messages get stored with reconnect-time and corrupt recency ordering.
var (
	origMsgTimeMu sync.Mutex
	origMsgTime   = make(map[string]time.Time)
)

// rememberOriginalTimestamp records the earliest timestamp seen for a message ID.
// A resend's `t` is always >= the original, so the earliest is the true one.
func rememberOriginalTimestamp(id string, ts time.Time) {
	if id == "" || ts.IsZero() {
		return
	}
	origMsgTimeMu.Lock()
	defer origMsgTimeMu.Unlock()
	if existing, ok := origMsgTime[id]; !ok || ts.Before(existing) {
		origMsgTime[id] = ts
	}
	// Soft cap so a burst of never-retried undecryptable messages can't grow this
	// map unbounded. Entries are normally consumed on successful decrypt.
	if len(origMsgTime) > 5000 {
		for k := range origMsgTime {
			delete(origMsgTime, k)
			if len(origMsgTime) <= 4000 {
				break
			}
		}
	}
}

// takeOriginalTimestamp returns and removes the cached original timestamp for id.
func takeOriginalTimestamp(id string) (time.Time, bool) {
	origMsgTimeMu.Lock()
	defer origMsgTimeMu.Unlock()
	ts, ok := origMsgTime[id]
	if ok {
		delete(origMsgTime, id)
	}
	return ts, ok
}

func handleMessage(client *whatsmeow.Client, messageStore *MessageStore, msg *events.Message, logger waLog.Logger) {
	// Resolve aliases for lookups without changing the original chat key.
	resolvedChat := resolveLIDChat(client, msg.Info.Chat, msg.Info.SenderAlt, msg.Info.RecipientAlt, msg.Info.IsFromMe)
	originalChatJID := msg.Info.Chat.ToNonAD().String()
	chatJID := originalChatJID
	chatIdentity := ResolvedIdentity{OriginalJID: originalChatJID, State: IdentityUnresolved}
	if msg.Info.Chat.Server == types.DefaultUserServer || msg.Info.Chat.Server == types.HiddenUserServer {
		chatAlternate := msg.Info.SenderAlt
		if msg.Info.IsFromMe {
			chatAlternate = msg.Info.RecipientAlt
		}
		chatIdentity = resolveIdentityJID(client, msg.Info.Chat, chatAlternate)
	}
	originalSenderJID := msg.Info.Sender.ToNonAD().String()
	senderIdentity := resolveIdentityJID(client, msg.Info.Sender, senderAltForMessage(client, msg.Info))
	sender := msg.Info.Sender.User
	resolvedSender := msg.Info.Sender.ToNonAD()
	if senderIdentity.State == IdentityResolved {
		if parsed, err := types.ParseJID(senderIdentity.ResolvedJID); err == nil {
			resolvedSender = parsed
		}
	}
	messageIdentity := MessageIdentity{
		OriginalSenderJID: originalSenderJID,
		OriginalChatJID:   originalChatJID,
		ResolvedSenderJID: senderIdentity.ResolvedJID,
		ResolvedChatJID:   chatIdentity.ResolvedJID,
		State:             senderIdentity.State,
		ChatState:         chatIdentity.State,
	}
	if msg.Info.Chat.Server == types.GroupServer {
		messageIdentity.GroupParticipantJID = originalSenderJID
	}

	// Get appropriate chat name (pass resolved JID so contact lookup works).
	name := GetChatName(client, messageStore, resolvedChat, resolvedChat.String(), nil, resolvedSender.User, logger)

	// If contact resolution fails (common for LIDs), PushName is often the best available display name.
	// Only apply for direct messages (not groups) and only when the stored name is the numeric JID user.
	if !msg.Info.IsFromMe && msg.Info.Chat.Server != "g.us" && strings.TrimSpace(msg.Info.PushName) != "" {
		pushName := strings.TrimSpace(msg.Info.PushName)
		if name == "" || name == msg.Info.Chat.User {
			logger.Infof("Updating chat name from PushName")
			name = pushName
		}
	}

	// Recover the true send-time if this message first arrived undecryptable and is
	// now landing via a retry-resend (whose stanza `t` is the resend time, not the
	// original). See origMsgTime / rememberOriginalTimestamp.
	msgTimestamp := msg.Info.Timestamp
	if orig, ok := takeOriginalTimestamp(msg.Info.ID); ok && orig.Before(msgTimestamp) {
		logger.Infof("Using original pre-retry timestamp")
		msgTimestamp = orig
	}

	// Update chat in database with the message timestamp (keeps last message time updated)
	err := messageStore.StoreChat(chatJID, name, msgTimestamp)
	if err != nil {
		logger.Warnf("Failed to store chat")
	}

	updateChatEphemeralSettingsFromProtocolMessage(messageStore, chatJID, msg.Message, msg.Info.Timestamp.Unix(), logger)
	handleMessageRevoke(messageStore, msg.Message, chatJID, msg.Info.Timestamp.Unix(), logger)

	// Backfill ephemeral state from any regular message's ContextInfo.
	// EPHEMERAL_SETTING ProtocolMessages and GroupInfo events only fire on
	// changes, so chats whose disappearing timer was set before the bridge
	// started (or before this code shipped) would otherwise stay invisible
	// to outgoing-message logic.
	if backfill := extractChatEphemeralFromMessage(msg.Message); backfill.SettingTimestamp != 0 {
		if err := messageStore.UpdateChatEphemeralSettings(chatJID, backfill.Expiration, backfill.SettingTimestamp); err != nil {
			logger.Warnf("Failed to backfill ephemeral settings")
		}
	}

	// Status updates are stored but never forwarded or auto-downloaded.
	isStatus := msg.Info.Chat == types.StatusBroadcastJID
	shouldForward := !isStatus && webhooksEnabled() && (forwardSelfMessages || !msg.Info.IsFromMe)

	// Reactions arrive as their own message stanza rather than message content.
	// Persist them in the messages table as media_type="reaction", with the
	// emoji in `content` and the reacted-to message ID in `filename`, then
	// return — a reaction is not a normal content message. An empty emoji is a
	// valid event meaning "reaction removed"; we store it (so consumers see the
	// removal) rather than dropping it.
	if reaction := msg.Message.GetReactionMessage(); reaction != nil {
		reactedToID := ""
		if key := reaction.GetKey(); key != nil {
			reactedToID = key.GetID()
		}
		if reactedToID != "" {
			emoji := reaction.GetText()
			if err := messageStore.StoreLiveMessageWithIdentity(
				msg.Info.ID, chatJID, sender, emoji,
				msgTimestamp, msg.Info.IsFromMe,
				"reaction", reactedToID, "", nil, nil, nil, 0, "", messageIdentity,
				"live",
			); err != nil {
				logger.Warnf("Failed to store reaction")
			}
			if shouldForward {
				SendReactionWebhook(sender, chatJID, msg.Info.IsFromMe, msg.Info.ID, reactedToID, emoji)
			}
		}
		return
	}

	// Extract text content
	content := extractTextContent(msg.Message)

	// Extract media info - pass message timestamp + ID for unique filenames.
	// Must be the same (retry-corrected) timestamp we store below: downloadMedia
	// rebuilds the on-disk filename from the stored timestamp.
	mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg.Message, msgTimestamp, msg.Info.ID)

	// Extract quoted message info
	quotedMessageId, quotedSender, quotedContent := extractQuotedMessageInfo(msg.Message)
	mentionedJIDs := extractMentionedJIDs(msg.Message)

	// Skip if there's no content and no media
	if content == "" && mediaType == "" {
		return
	}

	// Store message in database first so that downloadMedia (which queries the DB
	// by message ID) can find the row when we call it synchronously below.
	err = messageStore.StoreLiveMessageWithIdentity(
		msg.Info.ID,
		chatJID,
		sender,
		content,
		msgTimestamp,
		msg.Info.IsFromMe,
		mediaType,
		filename,
		url,
		mediaKey,
		fileSHA256,
		fileEncSHA256,
		fileLength,
		quotedMessageId,
		messageIdentity,
		"live",
	)
	stored := err == nil
	if !stored {
		// The row is what /api/download, get_message_context and mark-read key
		// on; without it the message exists only downstream. Still forward the
		// webhook so the text isn't lost, but say so loudly and skip media
		// downloads, which look the row up by ID and would only fail again.
		logger.Errorf("Failed to store message; media download skipped")
	}

	var quotedIsFromMe *bool
	if quotedMessageId != "" {
		var lookupErr error
		quotedIsFromMe, lookupErr = messageStore.GetMessageIsFromMe(quotedMessageId, chatJID)
		if lookupErr != nil {
			logger.Warnf("Failed to resolve quoted message origin")
		}
	}

	// The opt-out covers every implicit download, including webhook images.
	shouldDownload := !isStatus && autoDownloadMediaEnabled()

	// Forwarded images download synchronously to include bytes in the webhook.
	// Other media downloads asynchronously for caching when downloads are enabled.
	var imageDownloadPath string
	imageMimeType := msg.Message.GetImageMessage().GetMimetype()
	if mediaType == "image" && url != "" && len(mediaKey) > 0 && shouldForward && stored && shouldDownload {
		logger.Infof("Downloading image media (synchronous)")
		success, _, _, dlPath, dlErr := downloadMediaForMessage(client, messageStore, msg.Info.ID, chatJID)
		if success && dlErr == nil {
			imageDownloadPath = dlPath
			// Detect MIME type by sniffing the actual file bytes rather than
			// trusting the generated filename extension (always .jpg).
			if f, openErr := os.Open(dlPath); openErr == nil {
				buf := make([]byte, 512)
				if n, readErr := f.Read(buf); readErr == nil || n > 0 {
					imageMimeType = http.DetectContentType(buf[:n])
				}
				_ = f.Close()
			}
			if imageMimeType == "" {
				imageMimeType = "application/octet-stream"
			}
			logger.Infof("Image downloaded")
		} else {
			logger.Warnf("Image download failed")
			// Fall back to async download so media is cached for future MCP tool calls
			scheduleMediaDownload(func() {
				_, _, _, _, _ = downloadMediaForMessage(client, messageStore, msg.Info.ID, chatJID)
			})
		}
	} else if mediaType != "" && url != "" && len(mediaKey) > 0 && stored && shouldDownload {
		// Media that is not included in a webhook payload: async download for caching.
		logger.Infof("Auto-downloading media")
		scheduleMediaDownload(func() {
			success, _, _, _, err := downloadMediaForMessage(client, messageStore, msg.Info.ID, chatJID)
			if success && err == nil {
				logger.Infof("Auto-downloaded media")
			} else {
				logger.Warnf("Auto-download failed")
			}
		})
	}

	// Send webhook for incoming messages.
	// Forward self-messages when FORWARD_SELF=true.
	// Always forward image messages (even without a text caption) so the AI vision
	// pipeline can analyse the image content.
	hasText := content != ""
	hasImage := mediaType == "image"

	if shouldForward && (hasText || hasImage) {
		if hasImage {
			SendWebhookWithMedia(
				sender, content, chatJID, msg.Info.IsFromMe,
				quotedMessageId, quotedSender, quotedContent, quotedIsFromMe, mentionedJIDs,
				msg.Info.ID, mediaType, imageMimeType, filename, imageDownloadPath,
			)
		} else {
			SendWebhookWithMessageID(sender, content, chatJID, msg.Info.IsFromMe, quotedMessageId, quotedSender, quotedContent, quotedIsFromMe, mentionedJIDs, msg.Info.ID)
		}
	}

	if err == nil && getEnvBool("WHATSAPP_LOG_CONTENT", false) {
		// Log message reception
		timestamp := msg.Info.Timestamp.Format("2006-01-02 15:04:05")
		direction := "←"
		if msg.Info.IsFromMe {
			direction = "→"
		}

		// Log based on message type
		if mediaType != "" {
			fmt.Printf("[%s] %s %s: [%s: %s] %s\n", timestamp, direction, sender, mediaType, filename, content)
		} else if content != "" {
			fmt.Printf("[%s] %s %s: %s\n", timestamp, direction, sender, content)
		}
	}
}

// DownloadMediaRequest represents the request body for the download media API
type DownloadMediaRequest struct {
	MessageID string `json:"message_id"`
	ChatJID   string `json:"chat_jid"`
}

// DownloadMediaResponse represents the response for the download media API
type DownloadMediaResponse struct {
	Success  bool   `json:"success"`
	Message  string `json:"message"`
	Filename string `json:"filename,omitempty"`
	Path     string `json:"path,omitempty"`
}

// Store additional media info in the database
func (store *MessageStore) StoreMediaInfo(id, chatJID, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64) error {
	_, err := store.db.Exec(
		"UPDATE messages SET url = ?, media_key = ?, file_sha256 = ?, file_enc_sha256 = ?, file_length = ? WHERE id = ? AND chat_jid = ?",
		url, mediaKey, fileSHA256, fileEncSHA256, fileLength, id, chatJID,
	)
	return err
}

// Get media info from the database
func (store *MessageStore) GetMediaInfo(id, chatJID string) (string, string, string, []byte, []byte, []byte, uint64, error) {
	var mediaType, filename, url string
	var mediaKey, fileSHA256, fileEncSHA256 []byte
	var fileLength uint64

	err := store.db.QueryRow(
		"SELECT media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length FROM messages WHERE id = ? AND chat_jid = ?",
		id, chatJID,
	).Scan(&mediaType, &filename, &url, &mediaKey, &fileSHA256, &fileEncSHA256, &fileLength)

	return mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength, err
}

// MediaDownloader implements the whatsmeow.DownloadableMessage interface
type MediaDownloader struct {
	URL           string
	DirectPath    string
	MediaKey      []byte
	FileLength    uint64
	FileSHA256    []byte
	FileEncSHA256 []byte
	MediaType     whatsmeow.MediaType
}

// GetDirectPath implements the DownloadableMessage interface
func (d *MediaDownloader) GetDirectPath() string {
	return d.DirectPath
}

// GetURL implements the DownloadableMessage interface
func (d *MediaDownloader) GetURL() string {
	return d.URL
}

// GetMediaKey implements the DownloadableMessage interface
func (d *MediaDownloader) GetMediaKey() []byte {
	return d.MediaKey
}

// GetFileLength implements the DownloadableMessage interface
func (d *MediaDownloader) GetFileLength() uint64 {
	return d.FileLength
}

// GetFileSHA256 implements the DownloadableMessage interface
func (d *MediaDownloader) GetFileSHA256() []byte {
	return d.FileSHA256
}

// GetFileEncSHA256 implements the DownloadableMessage interface
func (d *MediaDownloader) GetFileEncSHA256() []byte {
	return d.FileEncSHA256
}

// GetMediaType implements the DownloadableMessage interface
func (d *MediaDownloader) GetMediaType() whatsmeow.MediaType {
	return d.MediaType
}

// hasCompleteMediaInfo reports whether a stored message row carries enough
// media metadata to be downloadable. Extracted so tests can exercise the
// exact predicate downloadMedia enforces, instead of a hand-copied duplicate
// that can silently drift from it.
func hasCompleteMediaInfo(url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64) bool {
	return url != "" && len(mediaKey) != 0 && len(fileSHA256) != 0 && len(fileEncSHA256) != 0 && fileLength != 0
}

// Function to download media from a message
func downloadMedia(client *whatsmeow.Client, messageStore *MessageStore, messageID, chatJID string) (bool, string, string, string, error) {
	// Query the database for the message including timestamp
	var mediaType, url string
	var mediaKey, fileSHA256, fileEncSHA256 []byte
	var fileLength uint64
	var timestamp time.Time
	var err error

	// Get media info AND timestamp from the database
	err = messageStore.db.QueryRow(
		"SELECT media_type, url, media_key, file_sha256, file_enc_sha256, file_length, timestamp FROM messages WHERE id = ? AND chat_jid = ?",
		messageID, chatJID,
	).Scan(&mediaType, &url, &mediaKey, &fileSHA256, &fileEncSHA256, &fileLength, &timestamp)

	if err != nil {
		return false, "", "", "", fmt.Errorf("failed to find message: %v", err)
	}

	// Check if this is a media message
	if mediaType == "" {
		return false, "", "", "", fmt.Errorf("not a media message")
	}

	// Rebuild the path from (timestamp, messageID) — it must match
	// extractMediaInfo and remain inside store/ even for malformed IDs.
	chatDir, localPath, filename, err := mediaDownloadStorePaths(chatJID, mediaType, messageID, timestamp)
	if err != nil {
		return false, "", "", "", err
	}

	// Create directory for the chat if it doesn't exist. Owner-only (0700):
	// downloaded media can include private images/documents/voice notes.
	if err := ensureOwnerOnlyDirectory(chatDir); err != nil {
		return false, "", "", "", fmt.Errorf("failed to create chat directory: %v", err)
	}

	rootAbs, _ := filepath.Abs("store")
	rootReal, rootErr := filepath.EvalSymlinks(rootAbs)
	chatReal, chatErr := filepath.EvalSymlinks(chatDir)
	if rootErr != nil || chatErr != nil || !pathWithin(rootReal, chatReal) {
		return false, "", "", "", errors.New("media directory escapes store")
	}
	if targetInfo, e := os.Lstat(localPath); e == nil && targetInfo.Mode()&os.ModeSymlink != 0 {
		return false, "", "", "", errors.New("media symlinks are forbidden")
	}

	// mediaDownloadStorePaths returns an absolute, store-confined path.
	absPath := localPath

	// Check if file already exists
	if _, err := os.Stat(localPath); err == nil {
		// File exists, return it
		fmt.Println("Media file already cached")
		return true, mediaType, filename, absPath, nil
	}

	// If we don't have all the media info we need, we can't download
	if !hasCompleteMediaInfo(url, mediaKey, fileSHA256, fileEncSHA256, fileLength) {
		return false, "", "", "", fmt.Errorf("incomplete media information for download")
	}

	fmt.Println("Attempting to download media")

	// Extract direct path from URL
	directPath := extractDirectPathFromURL(url)

	// Create a downloader that implements DownloadableMessage
	var waMediaType whatsmeow.MediaType
	switch mediaType {
	case "image":
		waMediaType = whatsmeow.MediaImage
	case "video":
		waMediaType = whatsmeow.MediaVideo
	case "audio":
		waMediaType = whatsmeow.MediaAudio
	case "document":
		waMediaType = whatsmeow.MediaDocument
	case "sticker":
		// whatsmeow derives sticker decryption keys from the image HKDF info string
		// (see download.go: classToMediaType maps "StickerMessage" -> MediaImage).
		waMediaType = whatsmeow.MediaImage
	default:
		return false, "", "", "", fmt.Errorf("unsupported media type: %s", mediaType)
	}

	downloader := &MediaDownloader{
		URL:           url,
		DirectPath:    directPath,
		MediaKey:      mediaKey,
		FileLength:    fileLength,
		FileSHA256:    fileSHA256,
		FileEncSHA256: fileEncSHA256,
		MediaType:     waMediaType,
	}

	// Download the media using whatsmeow client
	mediaData, err := downloadMediaData(client, downloader)
	if err != nil {
		return false, "", "", "", errors.New("failed to download media; details omitted to protect signed URLs")
	}

	// Save the downloaded media to file. Owner-only (0600), same reasoning
	// as the chat directory above.
	if err := writeOwnerOnlyFile(localPath, mediaData); err != nil {
		return false, "", "", "", fmt.Errorf("failed to save media file: %v", err)
	}

	fmt.Printf("Successfully downloaded media (%d bytes)\n", len(mediaData))
	return true, mediaType, filename, absPath, nil
}

// downloadMediaData lets media persistence tests avoid a network request.
var downloadMediaData = func(client *whatsmeow.Client, downloader *MediaDownloader) ([]byte, error) {
	return client.Download(context.Background(), downloader)
}

// downloadMediaForMessage allows message-handling tests to verify whether a
// download blocks event processing without changing production behavior.
var downloadMediaForMessage = downloadMedia

// scheduleMediaDownload launches background caching work. Keeping the launch
// separate lets tests verify whether work was scheduled without timing sleeps.
var scheduleMediaDownload = func(download func()) { go download() }

// Extract direct path from a WhatsApp media URL
func extractDirectPathFromURL(url string) string {
	// The direct path is typically in the URL, we need to extract it
	// Example URL: https://mmg.whatsapp.net/v/t62.7118-24/13812002_698058036224062_3424455886509161511_n.enc?ccb=11-4&oh=...

	// Find the path part after the domain
	parts := strings.SplitN(url, ".net/", 2)
	if len(parts) < 2 {
		return url // Return original URL if parsing fails
	}

	// Keep the query string: it carries the CDN auth tokens (oh=/oe=).
	// whatsmeow's Download rebuilds the URL as host + directPath + "&hash=..."
	// and the CDN returns 403 if the auth params are missing.
	return "/" + parts[1]
}

// Start a REST API server to expose the WhatsApp client functionality.
//
// Auth: every handler is wrapped in withAuth, which enforces both a
// bearer-token check and a Host-header allow-list (loopback only). See
// auth.go for the rationale.
//
// Outbound media: req.MediaPath in /api/send is validated against
// allowedMediaRoots before sendWhatsAppMessage ever sees it. See
// media_path.go.
func newRESTMux(client *whatsmeow.Client, messageStore *MessageStore, port int, token string, allowedMediaRoots []string) *http.ServeMux {
	allowedHosts := buildAllowedHosts(port)
	auth := func(h http.HandlerFunc) http.HandlerFunc {
		return capabilityAuth(token, allowedHosts, h)
	}
	mux := http.NewServeMux()

	// On-demand history sync endpoint (see history_ondemand.go)
	registerHistoryEndpoint(mux, auth, client, messageStore)

	// Health check endpoint
	mux.HandleFunc("/api/health", auth(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		status := map[string]interface{}{
			"status":    "ok",
			"connected": client.IsConnected(),
			"timestamp": time.Now().Unix(),
		}
		if !client.IsConnected() {
			status["status"] = "disconnected"
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(status)
	}))

	// Handler for sending messages
	mux.HandleFunc("/api/send", auth(func(w http.ResponseWriter, r *http.Request) {
		// Only allow POST requests
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		fmt.Println("Received send request")

		// Parse the request body
		var req SendMessageRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		// Validate request
		if req.Recipient == "" {
			http.Error(w, "Recipient is required", http.StatusBadRequest)
			return
		}

		if req.Message == "" && req.MediaPath == "" {
			http.Error(w, "Message or media path is required", http.StatusBadRequest)
			return
		}

		if os.Getenv("WHATSAPP_AUTH_POLICY") != "" {
			required := "messages.send"
			if req.MediaPath != "" {
				required = "media.send"
			}
			if !consumerHasCapability(r.Header.Get("Authorization"), required) {
				http.Error(w, "Forbidden: capability required", 403)
				return
			}
		}

		// Validate and canonicalize media_path against the configured roots
		// before reading. This prevents the bridge from being used as a
		// generic file-read primitive (e.g. media_path=/Users/x/.ssh/id_rsa).
		resolvedMediaPath := req.MediaPath
		if req.MediaPath != "" {
			canonical, mpErr := validateMediaPath(req.MediaPath, allowedMediaRoots)
			if mpErr != nil {
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusForbidden)
				_ = json.NewEncoder(w).Encode(SendMessageResponse{
					Success: false,
					Message: fmt.Sprintf("media_path rejected: %v", mpErr),
				})
				return
			}
			resolvedMediaPath = canonical
		}

		// Avoid logging req.Message verbatim — it's user content and may
		// contain secrets the user pasted into a chat.
		fmt.Printf("Send request has_media=%v\n", resolvedMediaPath != "")

		// Send the message
		success, message := sendWhatsAppMessage(client, messageStore, req.Recipient, req.Message, resolvedMediaPath, req.QuotedMessageID, req.QuotedSenderJID, req.QuotedContent, req.Mentions)
		fmt.Printf("Send request success=%v\n", success)
		// Set response headers
		w.Header().Set("Content-Type", "application/json")

		// Set appropriate status code
		if !success {
			w.WriteHeader(http.StatusInternalServerError)
		}

		// Send response
		_ = json.NewEncoder(w).Encode(SendMessageResponse{
			Success: success,
			Message: message,
		})
	}))

	// Handler for explicitly sending read receipts for selected messages.
	mux.HandleFunc("/api/mark-read", auth(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req MarkReadRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		if req.ChatJID == "" || len(req.MessageIDs) == 0 {
			http.Error(w, "chat_jid and message_ids are required", http.StatusBadRequest)
			return
		}

		messageIDs := make([]types.MessageID, len(req.MessageIDs))
		for i, id := range req.MessageIDs {
			if strings.TrimSpace(id) == "" {
				http.Error(w, "message_ids must not contain empty values", http.StatusBadRequest)
				return
			}
			messageIDs[i] = types.MessageID(id)
		}

		chatJID, err := types.ParseJID(req.ChatJID)
		if err != nil || chatJID.User == "" || chatJID.Server == "" {
			http.Error(w, "Invalid chat_jid", http.StatusBadRequest)
			return
		}

		senderJID := types.EmptyJID
		if req.SenderJID != "" {
			if strings.Contains(req.SenderJID, "@") {
				senderJID, err = types.ParseJID(req.SenderJID)
			} else {
				senderJID = types.NewJID(strings.TrimSpace(req.SenderJID), types.DefaultUserServer)
			}
			if err != nil || senderJID.User == "" || senderJID.Server == "" {
				http.Error(w, "Invalid sender_jid", http.StatusBadRequest)
				return
			}
		} else if chatJID.Server == types.GroupServer {
			http.Error(w, "sender_jid is required for group read receipts", http.StatusBadRequest)
			return
		}

		readAt := time.Now()
		if req.Timestamp != "" {
			readAt, err = time.Parse(time.RFC3339, req.Timestamp)
			if err != nil {
				http.Error(w, "timestamp must be RFC 3339", http.StatusBadRequest)
				return
			}
		}

		w.Header().Set("Content-Type", "application/json")
		if !client.IsConnected() {
			w.WriteHeader(http.StatusServiceUnavailable)
			_ = json.NewEncoder(w).Encode(SendMessageResponse{
				Success: false,
				Message: "WhatsApp client is not connected. Please wait for reconnection.",
			})
			return
		}

		// Validate against the storage (phone-form) chat JID before any
		// external side effect. LID rewrite happens only for the receipt.
		if err := messageStore.ValidateInboundMarkRead(req.ChatJID, req.SenderJID, req.MessageIDs); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// MCP storage normalizes chats/senders to phone JIDs; MarkRead routes
		// the receipt `to`/`participant` as given, so resolve PN -> LID the
		// same way sendWhatsAppMessage does or migrated contacts silently fail.
		chatJID, err = resolveRecipientJID(client, req.ChatJID)
		if err != nil || chatJID.User == "" || chatJID.Server == "" {
			http.Error(w, "Invalid chat_jid", http.StatusBadRequest)
			return
		}
		if req.SenderJID != "" {
			senderJID, err = resolveRecipientJID(client, req.SenderJID)
			if err != nil || senderJID.User == "" || senderJID.Server == "" {
				http.Error(w, "Invalid sender_jid", http.StatusBadRequest)
				return
			}
		}

		if err := client.MarkRead(context.Background(), messageIDs, readAt, chatJID, senderJID); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(SendMessageResponse{Success: false, Message: err.Error()})
			return
		}

		// Advance the local read marker immediately so list_chats unread
		// clears without waiting for the self-read receipt round-trip.
		localReadAt := readAt
		if ts, ok, tsErr := messageStore.MaxMessageTimestamp(req.ChatJID, req.MessageIDs); tsErr == nil && ok {
			localReadAt = ts
		}
		if err := messageStore.MarkChatRead(req.ChatJID, localReadAt); err != nil {
			// Receipt already sent; log but still report success to the caller.
			fmt.Println("Warning: failed to persist local read marker")
		}

		_ = json.NewEncoder(w).Encode(SendMessageResponse{Success: true, Message: "Messages marked as read"})
	}))

	// Handler for sending (or removing) emoji reactions
	mux.HandleFunc("/api/react", auth(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req ReactRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Recipient == "" || req.MessageID == "" || req.Emoji == nil {
			http.Error(w, "recipient, message_id, and emoji are required", http.StatusBadRequest)
			return
		}
		chatJID, err := types.ParseJID(req.Recipient)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid recipient JID: %v", err), http.StatusBadRequest)
			return
		}
		var senderJID types.JID
		switch {
		case req.FromMe:
			if client.Store.ID == nil {
				http.Error(w, "Not logged in", http.StatusServiceUnavailable)
				return
			}
			senderJID = *client.Store.ID
		case req.SenderJID != "":
			if senderJID, err = types.ParseJID(req.SenderJID); err != nil {
				http.Error(w, fmt.Sprintf("Invalid sender_jid: %v", err), http.StatusBadRequest)
				return
			}
			if senderJID.User == "" || senderJID.Server == "" {
				http.Error(w, "Invalid sender_jid", http.StatusBadRequest)
				return
			}
		default:
			if chatJID.Server == types.GroupServer {
				http.Error(w, "sender_jid is required for group reactions when from_me is false", http.StatusBadRequest)
				return
			}
			senderJID = chatJID
		}
		msg := client.BuildReaction(chatJID, senderJID, req.MessageID, *req.Emoji)
		w.Header().Set("Content-Type", "application/json")
		if _, err := client.SendMessage(context.Background(), chatJID, msg); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]bool{"ok": true})
	}))

	// Handler for downloading media
	mux.HandleFunc("/api/download", auth(func(w http.ResponseWriter, r *http.Request) {
		// Only allow POST requests
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		// Check if connected
		if !client.IsConnected() {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusServiceUnavailable)
			_ = json.NewEncoder(w).Encode(DownloadMediaResponse{
				Success: false,
				Message: "WhatsApp client is not connected. Please wait for reconnection.",
			})
			return
		}

		// Parse the request body
		var req DownloadMediaRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		// Validate request
		if req.MessageID == "" || req.ChatJID == "" {
			http.Error(w, "Message ID and Chat JID are required", http.StatusBadRequest)
			return
		}

		// Log download request for debugging
		fmt.Println("Received media download request")

		// Download the media
		success, mediaType, filename, path, err := downloadMedia(client, messageStore, req.MessageID, req.ChatJID)

		// Set response headers
		w.Header().Set("Content-Type", "application/json")

		// Handle download result
		if !success || err != nil {
			errMsg := "Unknown error"
			if err != nil {
				errMsg = err.Error()
			}

			w.WriteHeader(http.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(DownloadMediaResponse{
				Success: false,
				Message: fmt.Sprintf("Failed to download media: %s", errMsg),
			})
			return
		}

		// Send successful response
		_ = json.NewEncoder(w).Encode(DownloadMediaResponse{
			Success:  true,
			Message:  fmt.Sprintf("Successfully downloaded %s media", mediaType),
			Filename: filename,
			Path:     path,
		})
	}))

	// Handler for sending typing indicator
	mux.HandleFunc("/api/typing", auth(func(w http.ResponseWriter, r *http.Request) {
		// Only allow POST requests
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		// Parse the request body
		var req struct {
			Recipient string `json:"recipient"`
			IsTyping  bool   `json:"is_typing"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		// Validate request
		if req.Recipient == "" {
			http.Error(w, "Recipient is required", http.StatusBadRequest)
			return
		}

		// Create JID for recipient
		var recipientJID types.JID
		var err error

		// Check if recipient is a JID
		if strings.Contains(req.Recipient, "@") {
			recipientJID, err = types.ParseJID(req.Recipient)
			if err != nil {
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]interface{}{
					"success": false,
					"message": fmt.Sprintf("Error parsing JID: %v", err),
				})
				return
			}
		} else {
			// Create JID from phone number
			recipientJID = types.JID{
				User:   req.Recipient,
				Server: "s.whatsapp.net",
			}
		}

		// Determine the chat presence state
		var state types.ChatPresence
		if req.IsTyping {
			state = types.ChatPresenceComposing
		} else {
			state = types.ChatPresencePaused
		}

		// Send the chat presence update
		err = client.SendChatPresence(context.Background(), recipientJID, state, types.ChatPresenceMediaText)

		// Set response headers
		w.Header().Set("Content-Type", "application/json")

		// Send response
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"success": false,
				"message": fmt.Sprintf("Failed to send typing indicator: %v", err),
			})
		} else {
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"success": true,
				"message": fmt.Sprintf("Typing indicator set to %v", req.IsTyping),
			})
		}
	}))

	return mux
}

func startRESTServer(client *whatsmeow.Client, messageStore *MessageStore, port int, token string, allowedMediaRoots []string) {
	handler := newRESTMux(client, messageStore, port, token, allowedMediaRoots)

	// Start the server with proper timeouts. Bind to loopback so the bridge is
	// not reachable from the LAN; MCP clients talk to it over localhost.
	serverAddr := fmt.Sprintf("127.0.0.1:%d", port)
	fmt.Printf("Starting REST API server on %s...\n", serverAddr)

	// Create server with timeouts for stability
	server := &http.Server{
		Addr:         serverAddr,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 60 * time.Second, // Longer for media downloads
		IdleTimeout:  120 * time.Second,
		Handler:      handler,
	}

	// Run server in a goroutine so it doesn't block
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			fmt.Println("REST API server error")
		}
	}()
}

func webhookStartupMessage(forwardSelf bool) string {
	if !webhooksEnabled() {
		return "WEBHOOK_ENABLED=false: outbound webhooks disabled"
	}
	if forwardSelf {
		return "FORWARD_SELF enabled: forwarding self messages to webhook"
	}
	return "FORWARD_SELF disabled: self messages will NOT be forwarded"
}

// pairingQROutcome reports how a pairing QR channel ended.
type pairingQROutcome int

const (
	// pairingQRChannelClosed means the channel drained without a verdict.
	pairingQRChannelClosed pairingQROutcome = iota
	// pairingQRSucceeded means the phone completed the handshake.
	pairingQRSucceeded
	// pairingQRTimedOut means the server ran out of codes to offer.
	pairingQRTimedOut
)

// renderPairingQRCodes drains a pairing QR channel and writes every code the
// server offers to w, delegating the actual rendering to renderQR.
//
// Every code has to be rendered, not just the first one. Since WhatsApp's 2026
// companion-registration change the server answers a scan with a
// companion_reg_refresh notification; whatsmeow then rotates the ADV secret
// and emits a fresh code, and only that rotated code can still complete the
// handshake. Showing just the first code leaves a stale one on screen, so
// every later scan is validated against a secret the server has already
// dropped and the phone reports "check your connection" while pairing never
// completes.
func renderPairingQRCodes(qrChan <-chan whatsmeow.QRChannelItem, w io.Writer, renderQR func(code string, w io.Writer)) pairingQROutcome {
	codes := 0
	for evt := range qrChan {
		switch evt.Event {
		case "code":
			codes++
			// Terminal output is best-effort; keep draining pairing events if a write fails.
			if codes == 1 {
				_, _ = fmt.Fprintln(w, "\nScan this QR code with your WhatsApp app:")
			} else {
				_, _ = fmt.Fprintf(w, "\nQR code refreshed (#%d) - scan this one instead:\n", codes)
			}
			renderQR(evt.Code, w)
			_, _ = fmt.Fprintln(w, "\nWaiting for QR code scan...")
		case "success":
			return pairingQRSucceeded
		case "timeout":
			return pairingQRTimedOut
		}
	}
	return pairingQRChannelClosed
}

func main() {
	flag.Parse()
	syscall.Umask(0o077)
	storeLock, lockErr := acquireStoreLock()
	if lockErr != nil {
		fmt.Fprintln(os.Stderr, "Bridge store unavailable")
		os.Exit(1)
	}
	defer func() { _ = storeLock.Close() }()
	if policyPath := os.Getenv("WHATSAPP_AUTH_POLICY"); policyPath != "" {
		if _, err := loadCapabilityPolicy(policyPath); err != nil {
			fmt.Fprintln(os.Stderr, "Invalid consumer policy")
			os.Exit(1)
		}
	}

	// Set up logger with DEBUG level for more detailed logging
	logger := waLog.Stdout("Client", "WARN", true)
	logger.Infof("Starting WhatsApp client...")

	logger.Infof("%s", webhookStartupMessage(forwardSelfMessages))

	// Create database connection for storing session data
	dbLog := dependencyPrivacyLogger{sink: waLog.Stdout("Database", "INFO", true)}

	// Create directory for database if it doesn't exist. Owner-only (0700),
	// same reasoning as NewMessageStore.
	if err := ensureOwnerOnlyDirectory("store"); err != nil {
		logger.Errorf("Failed to create store directory")
		return
	}

	container, err := sqlstore.New(context.Background(), "sqlite3", "file:store/whatsapp.db?_foreign_keys=on", dbLog)
	if err != nil {
		logger.Errorf("Failed to connect to database")
		return
	}

	// Get device store - This contains session information
	deviceStore, err := container.GetFirstDevice(context.Background())
	if err != nil {
		if err == sql.ErrNoRows {
			// No device exists, create one
			deviceStore = container.NewDevice()
			logger.Infof("Created new device")
		} else {
			logger.Errorf("Failed to get device")
			return
		}
	}

	// Optionally request a full history sync at pair time.
	//
	// whatsmeow's default DeviceProps has RequireFullSync=false, which asks the
	// primary device for "recent" history only (typically ~3 months, decided by
	// the phone). Setting RequireFullSync=true with a large FullSyncDaysLimit
	// flips the handshake to request full-history mode. The phone still decides
	// the actual cap — iPad companion is documented at ~1 year max
	// (https://wabetainfo.com/...). Only meaningful at pair time: for an
	// already-paired session (whatsapp.db present), this is a no-op because no
	// new pair handshake fires.
	//
	// Enable by passing --full-history-pair on the command line BEFORE deleting
	// whatsapp.db and re-scanning the QR code. The flag defaults to false so
	// normal launchd-managed restarts don't accidentally trigger a huge sync.
	if *fullHistoryPairFlag {
		store.DeviceProps.RequireFullSync = proto.Bool(true)
		store.DeviceProps.HistorySyncConfig = &waCompanionReg.DeviceProps_HistorySyncConfig{
			FullSyncDaysLimit:   proto.Uint32(3650),
			FullSyncSizeMbLimit: proto.Uint32(102400),
			StorageQuotaMb:      proto.Uint32(102400),
		}
		logger.Infof("--full-history-pair enabled: requesting full history (days=3650, sizeMb=102400)")
	}

	// Set the linked-device label shown in WhatsApp's "Linked Devices" list.
	// whatsmeow's built-in default is the literal string "whatsmeow", which is
	// opaque to end users who then see an unfamiliar name attached to their
	// account. WHATSAPP_DEVICE_NAME lets an operator show a recognisable label
	// (e.g. a product or company name) instead. Empty/unset keeps the whatsmeow
	// default. This only takes effect at pair time — an already-paired session
	// (whatsapp.db present) keeps the name captured when the QR was scanned; to
	// change it, re-pair. The platform icon (DeviceProps.PlatformType) is left
	// at whatsmeow's default on purpose: this is a labelling convenience, not a
	// way to impersonate an official WhatsApp client.
	if name := resolveDeviceName(); name != "" {
		store.DeviceProps.Os = proto.String(name)
		logger.Infof("Linked-device name configured")
	}

	// Create client instance
	client := whatsmeow.NewClient(deviceStore, dependencyPrivacyLogger{sink: logger})
	if client == nil {
		logger.Errorf("Failed to create WhatsApp client")
		return
	}

	// Initialize message store
	messageStore, err := NewMessageStore()
	if err != nil {
		logger.Errorf("Failed to initialize message store")
		return
	}
	defer func() { _ = messageStore.Close() }()

	// Resolve the REST API port. Pure env parsing with no dependency on the
	// WhatsApp connection, so it's safe to do this early alongside the token
	// load below — and failing fast here means we don't run a QR-pairing
	// flow only to error out on an invalid port afterwards.
	port := 8080
	if p := os.Getenv("WHATSAPP_BRIDGE_PORT"); p != "" {
		v, err := strconv.Atoi(p)
		if err != nil || v < 1 || v > 65535 {
			logger.Errorf("Invalid WHATSAPP_BRIDGE_PORT, must be 1-65535")
			return
		}
		port = v
	}

	// Load (or generate on first run) the bearer token used to authenticate
	// REST callers, and attach it to outbound webhook POSTs so the hub's
	// fail-closed inbound-auth middleware accepts them (see auth.go and
	// webhook.go). This MUST happen before the event handler below is
	// registered: WhatsApp can deliver messages — including a burst of
	// history-sync backlog — as soon as the connection succeeds, and any
	// message handled before this assignment would go out with no bridge
	// token attached.
	bridgeToken, fresh, tokErr := loadOrCreateBridgeToken()
	if tokErr != nil {
		logger.Errorf("Failed to initialize bridge token")
		return
	}
	webhookAuthToken = bridgeToken

	// Print the one-time setup banner immediately, before attempting to
	// connect/pair. loadOrCreateBridgeToken() already persisted the token to
	// disk as soon as it generated one; if the banner instead waited until
	// after a successful connection (as it used to), a QR-pairing timeout or
	// early exit would leave a token on disk that was never shown to the
	// user — and loadOrCreateBridgeToken() would report fresh=false on every
	// later run, so the banner would never get a second chance to print it.
	if fresh {
		logger.Infof("Bridge token stored privately; value omitted")
	}

	if *offlineFlag || (*waitUnpairedFlag && client.Store.ID == nil) {
		roots, err := resolveMediaRoots()
		if err != nil {
			logger.Errorf("Invalid media roots")
			return
		}
		startRESTServer(client, messageStore, port, bridgeToken, roots)
		waitForShutdown()
		return
	}

	var qrWriter io.WriteCloser
	if client.Store.ID == nil {
		qrWriter, err = pairingWriter(*pairSocketFlag)
		if err != nil {
			logger.Errorf("Pairing not enabled")
			return
		}
		defer func() { _ = qrWriter.Close() }()
	}

	// Channel to signal reconnection needs
	reconnectChan := make(chan bool, 1)

	// Setup event handling for messages and history sync
	client.AddEventHandler(func(evt interface{}) {
		switch v := evt.(type) {
		case *events.Message:
			// Process regular messages
			handleMessage(client, messageStore, v, logger)

		case *events.UndecryptableMessage:
			// The first (failed) delivery carries the original send-time. WhatsApp
			// re-sends after our retry receipt, but that copy's `t` is the resend
			// time — so stash the original now and reuse it in handleMessage.
			rememberOriginalTimestamp(v.Info.ID, v.Info.Timestamp)

		case *events.HistorySync:
			// Process history sync events
			handleHistorySync(client, messageStore, v, logger)

		case *events.Receipt:
			// Persist read state so consumers can distinguish genuine unread
			// from "latest message is inbound". Only our own reads count.
			if isSelfReadReceipt(v) {
				chatJID := resolveLIDChat(client, v.Chat, v.SenderAlt, v.RecipientAlt, v.IsFromMe).String()
				// Prefer the acknowledged messages' timestamps over the
				// receipt event time so out-of-order delivery cannot advance
				// the marker past an unread message.
				readAt := v.Timestamp
				ids := make([]string, len(v.MessageIDs))
				for i, id := range v.MessageIDs {
					ids[i] = string(id)
				}
				if ts, ok, err := messageStore.MaxMessageTimestamp(chatJID, ids); err != nil {
					logger.Warnf("Failed to look up read receipt message times")
				} else if ok {
					readAt = ts
				}
				if err := messageStore.MarkChatRead(chatJID, readAt); err != nil {
					logger.Warnf("Failed to mark chat read")
				}
			}

		case *events.GroupInfo:
			if v.Ephemeral != nil {
				expiration := uint32(0)
				if v.Ephemeral.IsEphemeral {
					expiration = v.Ephemeral.DisappearingTimer
				}
				if err := messageStore.UpdateChatEphemeralSettings(v.JID.String(), expiration, v.Timestamp.Unix()); err != nil {
					logger.Warnf("Failed to store group ephemeral settings")
				}
			}

		case *events.CallOffer:
			// 1:1 incoming call. call_type defaults to "voice"; CallOffer
			// doesn't expose Media directly (it's buried in the binary Data
			// node). Group calls come through CallOfferNotice instead, which
			// DOES expose Media cleanly.
			handleCallOffer(client, messageStore, v.BasicCallMeta, "voice", false, logger)

		case *events.CallOfferNotice:
			// Group calls. v.Media is "audio" or "video"; normalize to our
			// "voice"/"video" convention.
			callType := "voice"
			if v.Media == "video" {
				callType = "video"
			}
			isGroup := v.Type == "group" || !v.BasicCallMeta.GroupJID.IsEmpty()
			handleCallOffer(client, messageStore, v.BasicCallMeta, callType, isGroup, logger)

		case *events.CallAccept:
			if err := messageStore.MarkCallAnswered(v.CallID, callChatJID(v.BasicCallMeta)); err != nil {
				logger.Warnf("Failed to mark call answered")
			} else {
				logger.Infof("Call answered")
			}

		case *events.CallReject:
			if err := messageStore.MarkCallRejected(v.CallID, callChatJID(v.BasicCallMeta)); err != nil {
				logger.Warnf("Failed to mark call rejected")
			} else {
				logger.Infof("Call rejected")
			}

		case *events.CallTerminate:
			if err := messageStore.MarkCallTerminated(v.CallID, callChatJID(v.BasicCallMeta), v.Reason, v.Timestamp); err != nil {
				logger.Warnf("Failed to mark call terminated")
			} else {
				logger.Infof("Call terminated")
			}

		case *events.Connected:
			logger.Infof("✓ Successfully connected to WhatsApp servers")

		case *events.LoggedOut:
			logger.Warnf("⚠️  Device logged out, please scan QR code to log in again")

		case *events.Disconnected:
			logger.Warnf("⚠️  Disconnected from WhatsApp servers, will attempt reconnection...")
			// Signal reconnection needed
			select {
			case reconnectChan <- true:
			default:
				// Channel already has a reconnect signal
			}

		case *events.ConnectFailure:
			logger.Errorf("❌ Connection failure: %v", v.Reason)
			// Signal reconnection needed
			select {
			case reconnectChan <- true:
			default:
			}

		case *events.StreamError:
			logger.Errorf("❌ Stream error: %v", v.Code)
			// Signal reconnection needed
			select {
			case reconnectChan <- true:
			default:
			}

		case *events.StreamReplaced:
			// Another WhatsApp Web session took our slot. whatsmeow treats this
			// as a "permanent" disconnect and suppresses the Disconnected event,
			// so we must handle it explicitly. Wait briefly to avoid ping-ponging
			// with the other client, then reconnect.
			logger.Warnf("⚠️  Stream replaced by another session — will reconnect after 30s")
			go func() {
				time.Sleep(30 * time.Second)
				select {
				case reconnectChan <- true:
				default:
				}
			}()

		case *events.ClientOutdated:
			logger.Errorf("❌ Client outdated - please update whatsmeow library")
		}
	})

	// Create channel to track connection success
	connected := make(chan bool, 1)

	// Add connection retry logic
	maxRetries := 3
	var connErr error

	for attempt := 1; attempt <= maxRetries; attempt++ {
		logger.Infof("Connection attempt %d/%d...", attempt, maxRetries)

		// Connect to WhatsApp
		if client.Store.ID == nil {
			// No ID stored, this is a new client, need to pair with phone
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
			defer cancel()

			qrChan, connErr := client.GetQRChannel(ctx)
			if connErr != nil {
				logger.Errorf("Failed to get QR channel")
				if attempt == maxRetries {
					return
				}
				time.Sleep(5 * time.Second)
				continue
			}

			connErr = client.Connect()
			if connErr != nil {
				logger.Errorf("Failed to connect (attempt %d)", attempt)
				if attempt == maxRetries {
					return
				}
				time.Sleep(5 * time.Second)
				continue
			}

			// Print QR codes for pairing with the phone.
			switch renderPairingQRCodes(qrChan, qrWriter, func(code string, w io.Writer) {
				qrterminal.GenerateHalfBlock(code, qrterminal.L, w)
			}) {
			case pairingQRSucceeded:
				connected <- true
			case pairingQRTimedOut:
				logger.Warnf("QR code timed out")
			case pairingQRChannelClosed:
			}

			// Wait for connection with timeout
			select {
			case <-connected:
				fmt.Println("\nSuccessfully connected and authenticated!")
				goto connectionSuccess
			case <-ctx.Done():
				logger.Errorf("Timeout waiting for QR code scan (attempt %d)", attempt)
				client.Disconnect()
				if attempt == maxRetries {
					return
				}
				time.Sleep(10 * time.Second)
				continue
			}
		} else {
			// Already logged in, just connect
			connErr = client.Connect()
			if connErr != nil {
				logger.Errorf("Failed to connect (attempt %d)", attempt)
				if attempt == maxRetries {
					return
				}
				time.Sleep(5 * time.Second)
				continue
			}
			connected <- true
			break
		}
	}

connectionSuccess:

	// Wait a moment for connection to stabilize
	time.Sleep(2 * time.Second)

	if !client.IsConnected() {
		logger.Errorf("Failed to establish stable connection")
		return
	}

	fmt.Println("\n✓ Connected to WhatsApp! Type 'help' for commands.")

	// port and bridgeToken were already resolved above, before the connect/
	// pairing loop, so the setup banner could print immediately.

	// Resolve the allow-listed roots that media_path values in /api/send must
	// live under. See media_path.go for the rationale.
	allowedMediaRoots, mrErr := resolveMediaRoots()
	if mrErr != nil {
		logger.Errorf("Failed to resolve media roots")
		return
	}
	logger.Infof("Allowed media roots configured: %d", len(allowedMediaRoots))

	startRESTServer(client, messageStore, port, bridgeToken, allowedMediaRoots)

	// Create a channel to keep the main goroutine alive
	exitChan := make(chan os.Signal, 1)
	signal.Notify(exitChan, syscall.SIGINT, syscall.SIGTERM)

	fmt.Println("REST server is running. Press Ctrl+C to disconnect and exit.")

	// Start reconnection handler goroutine
	go func() {
		reconnectBackoff := time.Second * 5
		maxBackoff := time.Minute * 5

		for {
			select {
			case <-reconnectChan:
				logger.Infof("🔄 Attempting to reconnect...")

				// Wait before reconnecting
				time.Sleep(reconnectBackoff)

				// Try to reconnect
				if !client.IsConnected() {
					err := client.Connect()
					if err != nil {
						logger.Errorf("Reconnection failed")
						// Increase backoff for next attempt
						reconnectBackoff = reconnectBackoff * 2
						if reconnectBackoff > maxBackoff {
							reconnectBackoff = maxBackoff
						}
						// Signal another reconnection attempt
						select {
						case reconnectChan <- true:
						default:
						}
					} else {
						logger.Infof("✓ Reconnected successfully")
						// Reset backoff on successful connection
						reconnectBackoff = time.Second * 5
					}
				} else {
					logger.Infof("Already connected, skipping reconnection")
					reconnectBackoff = time.Second * 5
				}

			case <-exitChan:
				return
			}
		}
	}()

	// Wait for termination signal
	<-exitChan

	fmt.Println("Disconnecting...")
	// Disconnect client
	client.Disconnect()
}

// GetChatName determines the appropriate name for a chat based on JID and other info
func GetChatName(client *whatsmeow.Client, messageStore *MessageStore, jid types.JID, chatJID string, conversation interface{}, sender string, logger waLog.Logger) string {
	// First, check if chat already exists in database with a name
	var existingName string
	err := messageStore.db.QueryRow("SELECT name FROM chats WHERE jid = ?", chatJID).Scan(&existingName)
	if err == nil && existingName != "" {
		// Chat exists with a name, use that
		logger.Infof("Using existing chat name")
		return existingName
	}

	// Need to determine chat name
	var name string

	if jid.Server == "g.us" {
		// This is a group chat
		logger.Infof("Getting group name")

		// Use conversation data if provided (from history sync)
		if conversation != nil {
			// Extract name from conversation if available
			// This uses type assertions to handle different possible types
			var displayName, convName *string
			// Try to extract the fields we care about regardless of the exact type
			v := reflect.ValueOf(conversation)
			if v.Kind() == reflect.Pointer && !v.IsNil() {
				v = v.Elem()

				// Try to find DisplayName field
				if displayNameField := v.FieldByName("DisplayName"); displayNameField.IsValid() && displayNameField.Kind() == reflect.Pointer && !displayNameField.IsNil() {
					dn := displayNameField.Elem().String()
					displayName = &dn
				}

				// Try to find Name field
				if nameField := v.FieldByName("Name"); nameField.IsValid() && nameField.Kind() == reflect.Pointer && !nameField.IsNil() {
					n := nameField.Elem().String()
					convName = &n
				}
			}

			// Use the name we found
			if displayName != nil && *displayName != "" {
				name = *displayName
			} else if convName != nil && *convName != "" {
				name = *convName
			}
		}

		// If we didn't get a name, try group info
		if name == "" {
			groupInfo, err := client.GetGroupInfo(context.Background(), jid)
			if err == nil && groupInfo.Name != "" {
				name = groupInfo.Name
			} else {
				// Fallback name for groups
				name = fmt.Sprintf("Group %s", jid.User)
			}
		}

		logger.Infof("Using group name")
	} else {
		// This is an individual contact
		logger.Infof("Getting contact name")

		// Use contact info (full name)
		contact, err := client.Store.Contacts.GetContact(context.Background(), jid)
		if err == nil && contact.FullName != "" {
			name = contact.FullName
		} else {
			name = lookupLocalContactName(client, messageStore, chatJID, logger)

			if name == "" {
				if sender != "" {
					name = sender
				} else {
					name = jid.User
				}
			}
		}

		logger.Infof("Using contact name")
	}

	return name
}

func lookupLocalContactName(client *whatsmeow.Client, messageStore *MessageStore, chatJID string, logger waLog.Logger) string {
	if client == nil || client.Store == nil || client.Store.ID == nil || messageStore == nil || messageStore.waDB == nil {
		return ""
	}

	var localName string
	err := messageStore.waDB.QueryRow(
		`SELECT COALESCE(
			NULLIF(full_name, ''),
			NULLIF(push_name, ''),
			NULLIF(first_name, ''),
			NULLIF(business_name, ''),
			''
		) FROM whatsmeow_contacts WHERE our_jid = ? AND their_jid = ?`,
		client.Store.ID.String(),
		chatJID,
	).Scan(&localName)
	if err == nil {
		if localName != "" {
			logger.Infof("Using local contact name")
		}
		return localName
	}
	if err != sql.ErrNoRows && !strings.Contains(err.Error(), "no such table: whatsmeow_contacts") {
		logger.Warnf("Failed to query local contact name")
	}
	return ""
}

// callChatJID resolves the chat JID that a call belongs to. For group calls
// this is the group JID; for 1:1 calls it's the call creator's JID — which
// stays stable across the entire lifecycle (Offer → Accept → Terminate).
//
// meta.From is NOT reliable as the chat key: for Accept events that fire
// when the user picks up on their phone, meta.From is the *accepting*
// device's JID (our own), not the other party's. Using From caused Accept
// UPDATEs to miss the row stored at Offer time, so the state machine fell
// through to "missed" when the user answered elsewhere.
//
// meta.CallCreator is populated from the stanza's call-creator attribute,
// which WhatsApp keeps consistent for every event in the call.
func callChatJID(meta types.BasicCallMeta) string {
	if !meta.GroupJID.IsEmpty() {
		return meta.GroupJID.String()
	}
	if !meta.CallCreator.IsEmpty() {
		return meta.CallCreator.ToNonAD().String()
	}
	return meta.From.ToNonAD().String()
}

// handleCallOffer stores a new call row. The isFromMe path is defensive —
// in practice WhatsApp's primary device handles outbound calls without
// notifying linked devices, so events observed here are always inbound and
// isFromMe stays false. We keep the branch anyway in case behavior changes.
func handleCallOffer(client *whatsmeow.Client, messageStore *MessageStore, meta types.BasicCallMeta, callType string, isGroup bool, logger waLog.Logger) {
	chatJID := callChatJID(meta)

	fromJID := ""
	switch {
	case !meta.CallCreator.IsEmpty():
		fromJID = meta.CallCreator.ToNonAD().String()
	case !meta.From.IsEmpty():
		fromJID = meta.From.ToNonAD().String()
	}

	isFromMe := client.Store.ID != nil && fromJID == client.Store.ID.ToNonAD().String()

	if err := messageStore.StoreCallOffer(meta.CallID, chatJID, fromJID, meta.Timestamp, isFromMe, callType, isGroup); err != nil {
		logger.Warnf("Failed to store call offer")
		return
	}

	kind := "Call"
	if isGroup {
		kind = "Group call"
	}
	direction := "incoming"
	if isFromMe {
		direction = "outgoing"
	}
	logger.Infof("%s %s", kind, direction)
}

func handleHistorySync(client *whatsmeow.Client, messageStore *MessageStore, historySync *events.HistorySync, logger waLog.Logger) {
	// Log every history sync event with its shape. Different sync types
	// carry different payloads; logging type/chunk/progress makes it easy
	// to reason about what arrived from WhatsApp when debugging.
	logger.Infof("Received history sync: type=%s chunk=%d progress=%d conversations=%d",
		historySync.Data.GetSyncType(),
		historySync.Data.GetChunkOrder(),
		historySync.Data.GetProgress(),
		len(historySync.Data.Conversations),
	)

	syncedCount := 0
	for _, conversation := range historySync.Data.Conversations {
		// Parse JID from the conversation
		if conversation.ID == nil {
			continue
		}

		rawChatJID := *conversation.ID

		// Try to parse the JID
		jid, err := types.ParseJID(rawChatJID)
		if err != nil {
			logger.Warnf("Failed to parse JID")
			continue
		}

		// Resolve the alias for contact lookup, but store the original chat
		// JID so history sync cannot merge or rename an existing chat.
		resolved := resolveLIDChat(client, jid, types.EmptyJID, types.EmptyJID, false)
		chatJID := jid.ToNonAD().String()
		chatIdentity := ResolvedIdentity{OriginalJID: chatJID, State: IdentityUnresolved}
		if jid.Server == types.DefaultUserServer || jid.Server == types.HiddenUserServer {
			chatIdentity = resolveIdentityJID(client, jid, types.EmptyJID)
		}

		// Get appropriate chat name by passing the history sync conversation directly
		name := GetChatName(client, messageStore, resolved, resolved.String(), conversation, "", logger)

		// Process messages
		messages := conversation.Messages
		if len(messages) > 0 {
			// Update chat with latest message timestamp
			latestMsg := messages[0]
			if latestMsg == nil || latestMsg.Message == nil {
				continue
			}

			// Get timestamp from message info
			ts := latestMsg.Message.GetMessageTimestamp()
			if ts == 0 {
				continue
			}
			timestamp := time.Unix(int64(ts), 0)

			_ = messageStore.StoreChat(chatJID, name, timestamp)
			// Backfill read state only when WhatsApp explicitly reports unread
			// metadata. Sparse history-sync chunks omit UnreadCount; the
			// generated getter then returns 0 and would permanently mark the
			// chat read under the monotonic merge.
			if conversation.UnreadCount != nil &&
				conversation.GetUnreadCount() == 0 &&
				!conversation.GetMarkedAsUnread() {
				if err := messageStore.MarkChatRead(chatJID, timestamp); err != nil {
					logger.Warnf("Failed to backfill read state")
				}
			}
			if err := messageStore.UpdateChatEphemeralSettings(
				chatJID,
				conversation.GetEphemeralExpiration(),
				conversation.GetEphemeralSettingTimestamp(),
			); err != nil {
				logger.Warnf("Failed to store history sync ephemeral settings")
			}

			// Store messages
			for _, msg := range messages {
				if msg == nil || msg.Message == nil {
					continue
				}

				// Extract text content
				var content string
				if msg.Message.Message != nil {
					if conv := msg.Message.Message.GetConversation(); conv != "" {
						content = conv
					} else if ext := msg.Message.Message.GetExtendedTextMessage(); ext != nil {
						content = ext.GetText()
					}
				}

				// Extract media info - pass message timestamp + ID for unique filenames
				var mediaType, filename, url string
				var mediaKey, fileSHA256, fileEncSHA256 []byte
				var fileLength uint64

				histMsgID := ""
				if msg.Message != nil && msg.Message.Key != nil && msg.Message.Key.ID != nil {
					histMsgID = *msg.Message.Key.ID
				}

				if msg.Message.Message != nil {
					mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength = extractMediaInfo(msg.Message.Message, timestamp, histMsgID)
				}

				// Log decoding without private message fields
				logger.Infof("History message decoded")

				// Skip messages with no content and no media
				if content == "" && mediaType == "" {
					continue
				}

				// Retain the protocol sender and record any verified resolution
				// separately; a bare participant value is never inferred as a PN.
				var sender string
				var originalSender types.JID
				var senderIdentity ResolvedIdentity
				isFromMe := false
				if msg.Message.Key != nil {
					if msg.Message.Key.FromMe != nil {
						isFromMe = *msg.Message.Key.FromMe
					}
					var rawSender types.JID
					switch {
					case isFromMe && client.Store.ID != nil:
						rawSender = client.Store.ID.ToNonAD()
					case msg.Message.Key.Participant != nil && *msg.Message.Key.Participant != "":
						if parsed, perr := types.ParseJID(*msg.Message.Key.Participant); perr == nil {
							rawSender = parsed
						} else {
							rawSender = types.JID{User: *msg.Message.Key.Participant}
						}
					default:
						rawSender = jid
					}
					var alt types.JID
					if isFromMe && client.Store.ID != nil {
						alt = client.Store.ID.ToNonAD()
					}
					originalSender = rawSender.ToNonAD()
					senderIdentity = resolveIdentityJID(client, originalSender, alt)
					sender = originalSender.User
				} else {
					originalSender = jid.ToNonAD()
					senderIdentity = resolveIdentityJID(client, originalSender, types.EmptyJID)
					sender = jid.User
				}

				// Store message
				msgID := ""
				if msg.Message.Key != nil && msg.Message.Key.ID != nil {
					msgID = *msg.Message.Key.ID
				}

				// Get message timestamp
				ts := msg.Message.GetMessageTimestamp()
				if ts == 0 {
					continue
				}
				msgTimestamp := time.Unix(int64(ts), 0)

				historyIdentity := MessageIdentity{
					OriginalSenderJID: originalSender.String(),
					OriginalChatJID:   jid.ToNonAD().String(),
					ResolvedSenderJID: senderIdentity.ResolvedJID,
					ResolvedChatJID:   chatIdentity.ResolvedJID,
					State:             senderIdentity.State,
					ChatState:         chatIdentity.State,
				}
				if jid.Server == types.GroupServer {
					historyIdentity.GroupParticipantJID = originalSender.String()
				}
				err = messageStore.StoreMessageWithIdentity(
					msgID,
					chatJID,
					sender,
					content,
					msgTimestamp,
					isFromMe,
					mediaType,
					filename,
					url,
					mediaKey,
					fileSHA256,
					fileEncSHA256,
					fileLength,
					"", // quoted_message_id: history sync does not carry ContextInfo
					historyIdentity,
				)
				if err != nil {
					logger.Warnf("Failed to store history message")
				} else {
					syncedCount++
					logger.Infof("Stored history message")
				}
			}
		}
	}

	fmt.Printf("History sync complete. Stored %d messages.\n", syncedCount)
}

// analyzeOggOpus tries to extract duration and generate a simple waveform from an Ogg Opus file
func analyzeOggOpus(data []byte) (duration uint32, waveform []byte, err error) {
	// Try to detect if this is a valid Ogg file by checking for the "OggS" signature
	// at the beginning of the file
	if len(data) < 4 || string(data[0:4]) != "OggS" {
		return 0, nil, fmt.Errorf("not a valid Ogg file (missing OggS signature)")
	}

	// Parse Ogg pages to find the last page with a valid granule position
	var lastGranule uint64
	var sampleRate uint32 = 48000 // Default Opus sample rate
	var preSkip uint16 = 0
	var foundOpusHead bool

	// Scan through the file looking for Ogg pages
	for i := 0; i < len(data); {
		// Check if we have enough data to read Ogg page header
		if i+27 >= len(data) {
			break
		}

		// Verify Ogg page signature
		if string(data[i:i+4]) != "OggS" {
			// Skip until next potential page
			i++
			continue
		}

		// Extract header fields
		granulePos := binary.LittleEndian.Uint64(data[i+6 : i+14])
		pageSeqNum := binary.LittleEndian.Uint32(data[i+18 : i+22])
		numSegments := int(data[i+26])

		// Extract segment table
		if i+27+numSegments >= len(data) {
			break
		}
		segmentTable := data[i+27 : i+27+numSegments]

		// Calculate page size
		pageSize := 27 + numSegments
		for _, segLen := range segmentTable {
			pageSize += int(segLen)
		}

		// Check if we're looking at an OpusHead packet (should be in first few pages)
		if !foundOpusHead && pageSeqNum <= 1 {
			// Look for "OpusHead" marker in this page
			pageData := data[i : i+pageSize]
			headPos := bytes.Index(pageData, []byte("OpusHead"))
			if headPos >= 0 && headPos+12 < len(pageData) {
				// Found OpusHead, extract sample rate and pre-skip
				// OpusHead format: Magic(8) + Version(1) + Channels(1) + PreSkip(2) + SampleRate(4) + ...
				headPos += 8 // Skip "OpusHead" marker
				// PreSkip is 2 bytes at offset 10
				if headPos+12 <= len(pageData) {
					preSkip = binary.LittleEndian.Uint16(pageData[headPos+10 : headPos+12])
					sampleRate = binary.LittleEndian.Uint32(pageData[headPos+12 : headPos+16])
					foundOpusHead = true
					fmt.Printf("Found OpusHead: sampleRate=%d, preSkip=%d\n", sampleRate, preSkip)
				}
			}
		}

		// Keep track of last valid granule position
		if granulePos != 0 {
			lastGranule = granulePos
		}

		// Move to next page
		i += pageSize
	}

	if !foundOpusHead {
		fmt.Println("Warning: OpusHead not found, using default values")
	}

	// Calculate duration based on granule position
	if lastGranule > 0 {
		// Formula for duration: (lastGranule - preSkip) / sampleRate
		durationSeconds := float64(lastGranule-uint64(preSkip)) / float64(sampleRate)
		duration = uint32(math.Ceil(durationSeconds))
		fmt.Printf("Calculated Opus duration from granule: %f seconds (lastGranule=%d)\n",
			durationSeconds, lastGranule)
	} else {
		// Fallback to rough estimation if granule position not found
		fmt.Println("Warning: No valid granule position found, using estimation")
		durationEstimate := float64(len(data)) / 2000.0 // Very rough approximation
		duration = uint32(durationEstimate)
	}

	// Make sure we have a reasonable duration (at least 1 second, at most 300 seconds)
	if duration < 1 {
		duration = 1
	} else if duration > 300 {
		duration = 300
	}

	// Generate waveform
	waveform = placeholderWaveform(duration)

	fmt.Printf("Ogg Opus analysis: size=%d bytes, calculated duration=%d sec, waveform=%d bytes\n",
		len(data), duration, len(waveform))

	return duration, waveform, nil
}

// min returns the smaller of x or y
func min(x, y int) int {
	if x < y {
		return x
	}
	return y
}

// placeholderWaveform generates a synthetic waveform for WhatsApp voice messages
// that appears natural with some variability based on the duration
func placeholderWaveform(duration uint32) []byte {
	// WhatsApp expects a 64-byte waveform for voice messages
	const waveformLength = 64
	waveform := make([]byte, waveformLength)

	// Seed the random number generator for consistent results with the same duration
	rand.Seed(int64(duration))

	// Create a more natural looking waveform with some patterns and variability
	// rather than completely random values

	// Base amplitude and frequency - longer messages get faster frequency
	baseAmplitude := 35.0
	frequencyFactor := float64(min(int(duration), 120)) / 30.0

	for i := range waveform {
		// Position in the waveform (normalized 0-1)
		pos := float64(i) / float64(waveformLength)

		// Create a wave pattern with some randomness
		// Use multiple sine waves of different frequencies for more natural look
		val := baseAmplitude * math.Sin(pos*math.Pi*frequencyFactor*8)
		val += (baseAmplitude / 2) * math.Sin(pos*math.Pi*frequencyFactor*16)

		// Add some randomness to make it look more natural
		val += (rand.Float64() - 0.5) * 15

		// Add some fade-in and fade-out effects
		fadeInOut := math.Sin(pos * math.Pi)
		val = val * (0.7 + 0.3*fadeInOut)

		// Center around 50 (typical voice baseline)
		val = val + 50

		// Ensure values stay within WhatsApp's expected range (0-100)
		if val < 0 {
			val = 0
		} else if val > 100 {
			val = 100
		}

		waveform[i] = byte(val)
	}

	return waveform
}
