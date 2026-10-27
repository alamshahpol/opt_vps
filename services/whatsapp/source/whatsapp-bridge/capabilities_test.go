package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func policyFixture(t *testing.T, capabilities []string) (string, string) {
	t.Helper()
	token := "synthetic-consumer-token-for-offline-tests"
	sum := sha256.Sum256([]byte(token))
	policy := CapabilityPolicy{Consumers: []ConsumerGrant{{ID: "reader", Account: "test-account", TokenSHA256: hex.EncodeToString(sum[:]), Capabilities: capabilities}}}
	data, _ := json.Marshal(policy)
	path := filepath.Join(t.TempDir(), "policy.json")
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("WHATSAPP_AUTH_POLICY", path)
	t.Setenv("WHATSAPP_ACCOUNT_ALIAS", "test-account")
	return path, token
}
func TestCapabilityBoundaryDeniesBeforeHandler(t *testing.T) {
	_, token := policyFixture(t, []string{"messages.read"})
	for _, path := range []string{"/api/send", "/api/react", "/api/mark-read", "/api/typing", "/api/history", "/api/download", "/api/unknown"} {
		t.Run(path, func(t *testing.T) {
			invoked := false
			h := capabilityAuth("master-token", buildAllowedHosts(8080), func(w http.ResponseWriter, r *http.Request) { invoked = true })
			r := httptest.NewRequest("POST", "http://127.0.0.1:8080"+path, nil)
			r.Header.Set("Authorization", "Bearer "+token)
			w := httptest.NewRecorder()
			h(w, r)
			if w.Code != 403 || invoked {
				t.Fatalf("boundary failed code=%d invoked=%v", w.Code, invoked)
			}
		})
	}
}
func TestCapabilityAuthenticationAccountAndRevocation(t *testing.T) {
	path, token := policyFixture(t, []string{"messages.send", "media.send"})
	for _, header := range []string{"", "Bearer wrong-token", "Bearer master-token"} {
		authenticated, _ := authorizeConsumer(header, "/api/send")
		if authenticated {
			t.Fatal("invalid token accepted")
		}
	}
	a, b := authorizeConsumer("Bearer "+token, "/api/send")
	if !a || !b {
		t.Fatal("granted send rejected")
	}
	t.Setenv("WHATSAPP_ACCOUNT_ALIAS", "different-account")
	a, _ = authorizeConsumer("Bearer "+token, "/api/send")
	if a {
		t.Fatal("cross-account token accepted")
	}
	t.Setenv("WHATSAPP_ACCOUNT_ALIAS", "test-account")
	if err := os.WriteFile(path, []byte(`{"consumers":[]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	a, _ = authorizeConsumer("Bearer "+token, "/api/send")
	if a {
		t.Fatal("revoked token accepted")
	}
}
func TestCapabilityHostAndPolicyModes(t *testing.T) {
	path, token := policyFixture(t, []string{"messages.send"})
	h := capabilityAuth("master", buildAllowedHosts(8080), func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) })
	r := httptest.NewRequest("POST", "http://evil.example:8080/api/send", nil)
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	h(w, r)
	if w.Code != 403 {
		t.Fatal("host bypass")
	}
	_ = os.Chmod(path, 0o644)
	if _, err := loadCapabilityPolicy(path); err == nil {
		t.Fatal("public policy allowed")
	}
}
func TestVerifiedDependencyRejectCallUnpaired(t *testing.T) {
	client := newTestClient(&mockLIDStore{})
	err := client.RejectCall(context.Background(), types.NewJID("synthetic", types.DefaultUserServer), "synthetic-call")
	if !errors.Is(err, whatsmeow.ErrNotLoggedIn) {
		t.Fatalf("expected ErrNotLoggedIn, got %v", err)
	}
}

func TestStoreLockPreventsCompetingBridge(t *testing.T) {
	old, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Chdir(t.TempDir()); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = os.Chdir(old) }()
	first, err := acquireStoreLock()
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = first.Close() }()
	if second, e := acquireStoreLock(); e == nil {
		_ = second.Close()
		t.Fatal("competing bridge accepted")
	}
}

func TestTokenBannerDoesNotRevealCredential(t *testing.T) {
	old := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stdout = w
	printTokenBanner("synthetic-never-log-this-credential", 8080)
	_ = w.Close()
	os.Stdout = old
	data, _ := io.ReadAll(r)
	_ = r.Close()
	if strings.Contains(string(data), "synthetic-never-log-this-credential") {
		t.Fatal("credential leaked")
	}
}

func TestMediaDownloadRejectsSymlinkedChatDirectory(t *testing.T) {
	old, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	if err = os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = os.Chdir(old) }()
	ms := newTestMessageStore(t)
	chat := "synthetic@s.whatsapp.net"
	if err = ms.StoreChat(chat, "Fixture", time.Now()); err != nil {
		t.Fatal(err)
	}
	if err = ms.StoreMessage("fixture", chat, "sender", "caption", time.Now(), false, "image", "", "", nil, nil, nil, 0, ""); err != nil {
		t.Fatal(err)
	}
	_ = os.MkdirAll("store", 0o700)
	if err = os.Symlink(t.TempDir(), filepath.Join("store", chat)); err != nil {
		t.Fatal(err)
	}
	if ok, _, _, _, e := downloadMedia(newTestClient(&mockLIDStore{}), ms, "fixture", chat); ok || e == nil {
		t.Fatal("download escaped store symlink")
	}
}
