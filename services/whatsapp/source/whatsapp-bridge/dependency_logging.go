package main

import (
	"fmt"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// dependencyPrivacyLogger is an adapter for the existing dependency logger,
// not a separate sink. Only reviewed operations and typed counts cross it:
// errors, nodes and even dynamically constructed format strings may be private.
type dependencyPrivacyLogger struct{ sink waLog.Logger }

var dependencyDiagnostics = map[string]string{
	"Failed to store LID-PN mapping for %s -> %s: %v":                 "LID-PN mapping persistence failed (details redacted)",
	"Node handling took %s for %s":                                    "Protocol node handling completed slowly (details redacted)",
	"Closing handler queue loop in the middle of handling %s":         "Protocol node handling interrupted (details redacted)",
	"Node handling is taking long for %s (started %s ago)":            "Protocol node handling delayed (details redacted)",
	"Continuing handling of %s in background as it's taking too long": "Protocol node handling continuing in background (details redacted)",
	"Event handler panicked while handling a %T: %v\n%s":              "Event handler panic (details redacted)",
	"Failed to parse message: %v":                                     "Message parsing failed (details redacted)",
	"Failed to decompress frame: %v":                                  "Protocol frame decompression failed (details redacted)",
	"Failed to decode node in frame: %v":                              "Protocol frame decoding failed (details redacted)",
	"Initial connection failed but reconnecting in background (%v)":   "Initial connection failed; reconnecting in background (details redacted)",
	"Error reconnecting after autoreconnect sleep: %v":                "Reconnection failed (details redacted)",
	"Received stream end frame":                                       "Received stream end frame",
	"Handler queue is full, message ordering is no longer guaranteed": "Handler queue is full; message ordering is no longer guaranteed",
}

func safeDependencyDiagnostic(msg string, args []any) string {
	if safe, ok := dependencyDiagnostics[msg]; ok {
		return safe
	}
	// The database migration's counts are useful; its identities are not.
	countFormats := map[string]int{
		"Migrated %d sessions, %d identity keys and %d sender keys from %s to %s": 3,
		"%d duplicate contacts found in PutAllContactNames":                       1,
		"%d duplicate contacts found in PutManyRedactedPhones":                    1,
	}
	if count, ok := countFormats[msg]; ok && len(args) >= count {
		values := make([]int64, count)
		for i := range count {
			switch value := args[i].(type) {
			case int:
				values[i] = int64(value)
			case int64:
				values[i] = value
			default:
				return "Database diagnostic (invalid counter; details redacted)"
			}
		}
		if count == 3 {
			return fmt.Sprintf("Database identity migration completed: sessions=%d identity_keys=%d sender_keys=%d", values[0], values[1], values[2])
		}
		return fmt.Sprintf("Database contact deduplication: duplicates=%d", values[0])
	}
	return "Dependency diagnostic (unclassified; details redacted)"
}

func (l dependencyPrivacyLogger) Warnf(msg string, args ...any) {
	l.sink.Warnf("%s", safeDependencyDiagnostic(msg, args))
}
func (l dependencyPrivacyLogger) Errorf(msg string, args ...any) {
	l.sink.Errorf("%s", safeDependencyDiagnostic(msg, args))
}
func (l dependencyPrivacyLogger) Infof(msg string, args ...any) {
	l.sink.Infof("%s", safeDependencyDiagnostic(msg, args))
}
func (l dependencyPrivacyLogger) Debugf(msg string, args ...any) {
	l.sink.Debugf("%s", safeDependencyDiagnostic(msg, args))
}
func (l dependencyPrivacyLogger) Sub(module string) waLog.Logger {
	switch module {
	case "Recv", "Send", "AppState", "Socket", "QRChannel":
	default:
		module = "Dependency"
	}
	return dependencyPrivacyLogger{sink: l.sink.Sub(module)}
}
