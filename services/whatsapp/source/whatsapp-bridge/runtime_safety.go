package main

import (
	"errors"
	"flag"
	"io"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"
)

var offlineFlag = flag.Bool("offline", false, "Initialize disposable stores and REST without connecting or pairing")
var waitUnpairedFlag = flag.Bool("wait-unpaired", false, "Wait without pairing when no session exists")
var pairSocketFlag = flag.String("pairing-socket", "", "Private Unix socket for attended QR display; required for new pairing")

func acquireStoreLock() (*os.File, error) {
	if err := ensureOwnerOnlyDirectory("store"); err != nil {
		return nil, err
	}
	f, err := os.OpenFile("store/.bridge.lock", os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = f.Close()
		return nil, errors.New("another bridge owns this store")
	}
	return f, nil
}

func pairingWriter(path string) (io.WriteCloser, error) {
	if path == "" || !filepath.IsAbs(path) {
		return nil, errors.New("new pairing requires an absolute private pairing socket")
	}
	// Never unlink an existing endpoint: it may belong to an active operator.
	parent := filepath.Dir(path)
	info, err := os.Stat(parent)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0o077 != 0 {
		return nil, errors.New("pairing socket parent must be private (0700)")
	}
	ln, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	defer func() { _ = ln.Close(); _ = os.Remove(path) }()
	if err = os.Chmod(path, 0o600); err != nil {
		return nil, err
	}
	if u, ok := ln.(*net.UnixListener); ok {
		_ = u.SetDeadline(time.Now().Add(5 * time.Minute))
	}
	return ln.Accept()
}

func waitForShutdown() {
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGTERM, syscall.SIGINT)
	<-ch
	signal.Stop(ch)
}
