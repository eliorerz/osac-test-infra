package main

import "testing"

func TestSortLinkMappingsByNumericLocalPort(t *testing.T) {
	links := []LinkMapping{
		{LocalPortIndex: 10, Local: "eth10"},
		{LocalPortIndex: 9, Local: "eth9"},
		{LocalPortIndex: 11, Local: "eth11"},
	}

	sortLinkMappings(links)

	got := []string{links[0].Local, links[1].Local, links[2].Local}
	want := []string{"eth9", "eth10", "eth11"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("link order = %v, want %v", got, want)
		}
	}
}

func TestControllerInfoUsesConfiguredBackendVersion(t *testing.T) {
	info := controllerInfo(
		NetrisController{BackendVersion: "4.16.0-008"},
		"auth-key",
		"main",
	)

	if info.Version != "4.16.0-008" {
		t.Fatalf("expected configured backend version 4.16.0-008, got %q", info.Version)
	}
}
