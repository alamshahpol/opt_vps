package main

import (
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

func capturePrivacyLogs(t *testing.T, run func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	old := os.Stdout
	os.Stdout = w
	defer func() { os.Stdout = old; _ = w.Close(); _ = r.Close() }()
	run()
	_ = w.Close()
	out, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	return string(out)
}

func assertPrivateValuesAbsent(t *testing.T, output string, values ...string) {
	t.Helper()
	for _, value := range values {
		if strings.Contains(output, value) {
			t.Fatal("private synthetic value reached logs")
		}
	}
}

func TestLoggingPrivacyResolvers(t *testing.T) {
	pn := types.JID{User: "15555550123", Server: types.DefaultUserServer}
	lid := types.JID{User: "990000000123", Server: types.HiddenUserServer}
	client := newTestClient(&mockLIDStore{pnByLID: map[types.JID]types.JID{lid: pn}, lidByPN: map[types.JID]types.JID{pn: lid}})
	out := capturePrivacyLogs(t, func() {
		if got := resolveLIDChat(client, lid, pn, types.EmptyJID, false); got != pn {
			t.Fatal("alt resolution changed")
		}
		if got := resolveLIDChat(client, lid, types.EmptyJID, types.EmptyJID, false); got != pn {
			t.Fatal("map resolution changed")
		}
		if got := resolveLIDChat(nil, lid, pn, types.EmptyJID, false); got != pn {
			t.Fatal("message alternate resolution changed")
		}
		if got := resolveLIDChat(nil, lid, types.EmptyJID, types.EmptyJID, false); got != lid {
			t.Fatal("unresolved fallback changed")
		}
		if got, err := resolveRecipientJID(client, pn.String()); err != nil || got != lid {
			t.Fatal("PN to LID resolution changed")
		}
	})
	assertPrivateValuesAbsent(t, out, pn.User, lid.User)
	for _, diagnostic := range []string{"message alternate", "LID store", "Could not resolve", "cache"} {
		if !strings.Contains(out, diagnostic) {
			t.Fatalf("missing diagnostic %s", diagnostic)
		}
	}
}

func TestLoggingPrivacyInboundNamesAndPersistence(t *testing.T) {
	t.Setenv("WHATSAPP_LOG_CONTENT", "false")
	t.Setenv("WEBHOOK_ENABLED", "false")
	t.Setenv("WHATSAPP_AUTO_DOWNLOAD_MEDIA", "false")
	pn := types.JID{User: "15555550123", Server: types.DefaultUserServer}
	lid := types.JID{User: "990000000123", Server: types.HiddenUserServer}
	client := newTestClient(&mockLIDStore{pnByLID: map[types.JID]types.JID{lid: pn}})
	ms := newTestMessageStore(t)
	body := "SYNTHETIC_PRIVATE_BODY"
	name := "SYNTHETIC_PRIVATE_NAME"
	msg := buildTextMessage(lid, lid, pn, types.EmptyJID, false, body)
	msg.Info.PushName = name
	out := capturePrivacyLogs(t, func() { handleMessage(client, ms, msg, waLog.Stdout("PrivacyTest", "INFO", false)) })
	assertPrivateValuesAbsent(t, out, pn.User, lid.User, body, name, string(msg.Info.ID))
	if !strings.Contains(out, "Resolved LID chat") {
		t.Fatal("missing resolver diagnostic")
	}
	var storedBody, storedSender, originalSenderJID, resolvedSenderJID string
	var fromMe bool
	if err := ms.db.QueryRow(
		"SELECT content,sender,is_from_me,original_sender_jid,resolved_sender_jid FROM messages WHERE id=? AND chat_jid=?",
		msg.Info.ID,
		lid.String(),
	).Scan(&storedBody, &storedSender, &fromMe, &originalSenderJID, &resolvedSenderJID); err != nil {
		t.Fatal(err)
	}
	if storedBody != body || storedSender != lid.User || originalSenderJID != lid.String() ||
		resolvedSenderJID != pn.String() || fromMe {
		t.Fatal("inbound persistence changed")
	}
}

func TestLoggingPrivacyMediaDownloadAndCache(t *testing.T) {
	t.Chdir(t.TempDir())
	ms := newTestMessageStore(t)
	chat, id := "15555550123@s.whatsapp.net", "SYNTHETIC_PRIVATE_MEDIA_ID"
	ts := time.Unix(1700000000, 0)
	if err := ms.StoreMessage(id, chat, "15555550123", "", ts, false, "image", "SYNTHETIC_PRIVATE_FILENAME", "https://example.invalid/private", []byte("SYNTHETIC_KEY"), []byte("hash"), []byte("enc-hash"), 4, ""); err != nil {
		t.Fatal(err)
	}
	old := downloadMediaData
	downloadMediaData = func(_ *whatsmeow.Client, _ *MediaDownloader) ([]byte, error) { return []byte("test"), nil }
	defer func() { downloadMediaData = old }()
	var path string
	out := capturePrivacyLogs(t, func() {
		for i := 0; i < 2; i++ {
			ok, _, _, p, err := downloadMedia(nil, ms, id, chat)
			if !ok || err != nil {
				t.Fatal("synthetic media download failed")
			}
			path = p
		}
	})
	assertPrivateValuesAbsent(t, out, chat, id, path, "15555550123", "SYNTHETIC_PRIVATE_FILENAME", "SYNTHETIC_KEY", "example.invalid")
	for _, diagnostic := range []string{"Attempting", "Successfully downloaded", "cached"} {
		if !strings.Contains(out, diagnostic) {
			t.Fatal("missing media diagnostic")
		}
	}
}
