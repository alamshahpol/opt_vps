package main

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"strings"
)

type ConsumerGrant struct {
	ID           string   `json:"id"`
	Account      string   `json:"account"`
	TokenSHA256  string   `json:"token_sha256"`
	Capabilities []string `json:"capabilities"`
}
type CapabilityPolicy struct {
	Consumers []ConsumerGrant `json:"consumers"`
}

var routeCapabilities = map[string]string{
	"/api/health": "", "/api/send": "messages.send", "/api/react": "reactions.send",
	"/api/mark-read": "receipts.write", "/api/typing": "typing.send",
	"/api/history": "history.request", "/api/download": "media.download",
}

func loadCapabilityPolicy(path string) (*CapabilityPolicy, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o027 != 0 {
		return nil, errors.New("policy must be private and not group writable")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var policy CapabilityPolicy
	if err = json.Unmarshal(data, &policy); err != nil {
		return nil, errors.New("invalid capability policy")
	}
	seen := map[string]bool{}
	for _, grant := range policy.Consumers {
		digest, e := hex.DecodeString(grant.TokenSHA256)
		if e != nil || len(digest) != 32 || grant.ID == "" || grant.Account == "" || seen[grant.TokenSHA256] {
			return nil, errors.New("invalid or duplicate consumer")
		}
		seen[grant.TokenSHA256] = true
	}
	return &policy, nil
}

// Reload for each request: revocation does not require a bridge restart.
func authorizeConsumer(header, path string) (bool, bool) {
	policy, err := loadCapabilityPolicy(os.Getenv("WHATSAPP_AUTH_POLICY"))
	if err != nil || !strings.HasPrefix(header, "Bearer ") {
		return false, false
	}
	token := strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
	if len(token) < 16 {
		return false, false
	}
	sum := sha256.Sum256([]byte(token))
	for _, grant := range policy.Consumers {
		digest, _ := hex.DecodeString(grant.TokenSHA256)
		if subtle.ConstantTimeCompare(sum[:], digest) != 1 || grant.Account != os.Getenv("WHATSAPP_ACCOUNT_ALIAS") {
			continue
		}
		capability, known := routeCapabilities[path]
		if !known {
			return true, false
		}
		if capability == "" {
			return true, true
		}
		// The combined send route distinguishes text and uploaded media.
		for _, scope := range grant.Capabilities {
			if scope == capability {
				return true, true
			}
		}
		return true, false
	}
	return false, false
}

func consumerHasCapability(header, capability string) bool {
	policy, err := loadCapabilityPolicy(os.Getenv("WHATSAPP_AUTH_POLICY"))
	if err != nil || !strings.HasPrefix(header, "Bearer ") {
		return false
	}
	sum := sha256.Sum256([]byte(strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))))
	for _, grant := range policy.Consumers {
		digest, _ := hex.DecodeString(grant.TokenSHA256)
		if subtle.ConstantTimeCompare(sum[:], digest) == 1 && grant.Account == os.Getenv("WHATSAPP_ACCOUNT_ALIAS") {
			for _, scope := range grant.Capabilities {
				if scope == capability {
					return true
				}
			}
		}
	}
	return false
}

func capabilityAuth(token string, hosts map[string]struct{}, h http.HandlerFunc) http.HandlerFunc {
	if os.Getenv("WHATSAPP_AUTH_POLICY") == "" {
		return withAuth(token, hosts, h)
	}
	return func(w http.ResponseWriter, r *http.Request) {
		if !hostAllowed(r.Host, hosts) {
			http.Error(w, "Forbidden: host not allowed", 403)
			return
		}
		authenticated, allowed := authorizeConsumer(r.Header.Get("Authorization"), r.URL.Path)
		// /send supports independently granted text and media permissions.
		if authenticated && r.URL.Path == "/api/send" {
			allowed = allowed || consumerHasCapability(r.Header.Get("Authorization"), "media.send")
		}
		if !authenticated {
			http.Error(w, "Unauthorized", 401)
			return
		}
		if !allowed {
			http.Error(w, "Forbidden: capability required", 403)
			return
		}
		h(w, r)
	}
}
