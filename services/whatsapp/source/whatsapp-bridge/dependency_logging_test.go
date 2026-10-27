package main

import (
	"context"
	"errors"
	"strings"
	"testing"

	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

type failingPrivacyLIDStore struct{ mockLIDStore }

func (s *failingPrivacyLIDStore) PutLIDMapping(context.Context, types.JID, types.JID) error {
	return errors.New("SYNTHETIC_TOKEN_BODY_PATH")
}

func TestDependencyLoggingMappingFailure(t *testing.T) {
	pn := types.JID{User: "15555550199", Server: types.DefaultUserServer}
	lid := types.JID{User: "990000000199", Server: types.HiddenUserServer}
	client := newTestClient(&failingPrivacyLIDStore{})
	var raw, safe string
	raw = capturePrivacyLogs(t, func() {
		client.Log = waLog.Stdout("Client", "WARN", false)
		client.StoreLIDPNMapping(context.Background(), lid, pn)
	})
	if !strings.Contains(raw, pn.User) || !strings.Contains(raw, lid.User) || !strings.Contains(raw, "SYNTHETIC_TOKEN_BODY_PATH") {
		t.Fatal("baseline exposure not reproduced")
	}
	safe = capturePrivacyLogs(t, func() {
		client.Log = dependencyPrivacyLogger{sink: waLog.Stdout("Client", "WARN", false)}
		client.StoreLIDPNMapping(context.Background(), lid, pn)
	})
	assertPrivateValuesAbsent(t, safe, pn.User, lid.User, "SYNTHETIC_TOKEN_BODY_PATH")
	if !strings.Contains(safe, "ERROR") || !strings.Contains(safe, "LID-PN mapping persistence failed") {
		t.Fatal("mapping diagnostic lost")
	}
}

// Mirror the exact pinned dependency templates, not a generated substitute sink.
func TestDependencyLoggingProtocolAndDatabase(t *testing.T) {
	private := "SYNTHETIC_PHONE_LID_NODE_BODY_TOKEN_PATH"
	raw := capturePrivacyLogs(t, func() { waLog.Stdout("Client", "WARN", false).Warnf("Node handling took %s for %s", "6s", private) })
	if !strings.Contains(raw, private) {
		t.Fatal("protocol diagnostic baseline not reproduced")
	}
	out := capturePrivacyLogs(t, func() {
		client := dependencyPrivacyLogger{sink: waLog.Stdout("Client", "WARN", false)}
		client.Sub("Recv").Warnf("Node handling took %s for %s", "6s", private)
		client.Sub(private).Errorf(private, errors.New(private))
		client.Sub("Socket").Debugf("%s", private)
		db := dependencyPrivacyLogger{sink: waLog.Stdout("Database", "INFO", false)}
		db.Infof("Migrated %d sessions, %d identity keys and %d sender keys from %s to %s", int64(2), int64(3), int64(4), private, private)
		db.Warnf("%d duplicate contacts found in PutAllContactNames", 5)
		db.Errorf("database failure %v", errors.New(private))
	})
	assertPrivateValuesAbsent(t, out, private)
	for _, safe := range []string{"Client/Recv WARN", "Client/Dependency ERROR", "Protocol node handling completed slowly", "sessions=2 identity_keys=3 sender_keys=4", "duplicates=5", "Database ERROR"} {
		if !strings.Contains(out, safe) {
			t.Fatalf("missing safe diagnostic %s", safe)
		}
	}
	if strings.Contains(out, "DEBUG") {
		t.Fatal("DEBUG unexpectedly enabled")
	}
}

type privateStringer struct{}

func (privateStringer) String() string { panic("dependency log must not evaluate private arguments") }
func TestDependencyLoggingDoesNotRenderArguments(t *testing.T) {
	for _, msg := range []string{"%s", "Failed to parse message: %v", "Migrated %d sessions, %d identity keys and %d sender keys from %s to %s"} {
		out := capturePrivacyLogs(t, func() {
			dependencyPrivacyLogger{sink: waLog.Stdout("Client", "WARN", false)}.Errorf(msg, privateStringer{}, privateStringer{}, privateStringer{})
		})
		if !strings.Contains(out, "ERROR") {
			t.Fatal("error silently suppressed")
		}
	}
}
