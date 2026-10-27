package main

import (
	"testing"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types"
)

func TestResolveLIDChat_NilClientFallsBackToLID(t *testing.T) {
	lid := types.JID{User: "184125298348272", Server: types.HiddenUserServer}

	// No alt hint and no client: must not panic, must return the LID unchanged.
	got := resolveLIDChat(nil, lid, types.EmptyJID, types.EmptyJID, false)
	if got != lid {
		t.Fatalf("expected unresolved LID %s, got %s", lid, got)
	}

	// A client whose store has no LID map behaves the same way.
	got = resolveLIDChat(&whatsmeow.Client{}, lid, types.EmptyJID, types.EmptyJID, false)
	if got != lid {
		t.Fatalf("expected unresolved LID %s with empty client, got %s", lid, got)
	}
}

func TestResolveIdentityJID_UsesOnlyTypedProtocolEvidence(t *testing.T) {
	lid := types.NewJID("184125298348272", types.HiddenUserServer)
	pn := types.NewJID("15551234567", types.DefaultUserServer)

	resolved := resolveIdentityJID(nil, lid, pn)
	if resolved.State != IdentityResolved || resolved.LID != lid.User ||
		resolved.PN != pn.User || resolved.OriginalJID != lid.String() ||
		resolved.ResolvedJID != pn.String() {
		t.Fatalf("verified alternate resolution = %#v", resolved)
	}

	bare := types.JID{User: "15551234567"}
	untyped := resolveIdentityJID(nil, bare, types.EmptyJID)
	if untyped.State != IdentityAmbiguous || untyped.ResolvedJID != "" {
		t.Fatalf("bare numeric identity must remain ambiguous, got %#v", untyped)
	}

	unmapped := resolveIdentityJID(nil, lid, types.EmptyJID)
	if unmapped.State != IdentityUnresolved || unmapped.ResolvedJID != "" {
		t.Fatalf("missing mapping must remain unresolved, got %#v", unmapped)
	}
}

func TestResolveIdentityJID_ConflictingProtocolEvidenceIsAmbiguous(t *testing.T) {
	lid := types.NewJID("184125298348272", types.HiddenUserServer)
	storePN := types.NewJID("15551234567", types.DefaultUserServer)
	alternatePN := types.NewJID("15557654321", types.DefaultUserServer)
	client := newTestClient(&mockLIDStore{
		pnByLID: map[types.JID]types.JID{lid: storePN},
	})

	got := resolveIdentityJID(client, lid, alternatePN)
	if got.State != IdentityAmbiguous || got.ResolvedJID != "" {
		t.Fatalf("conflicting protocol evidence must not resolve: %#v", got)
	}
}
