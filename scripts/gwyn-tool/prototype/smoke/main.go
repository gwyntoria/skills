// Drive the prototype through the host OS's PTY or Windows ConPTY.
package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	pty "github.com/aymanbagabas/go-pty"
	"github.com/charmbracelet/x/ansi"
	"github.com/charmbracelet/x/vt"
)

type terminal struct {
	pty.Pty
	process *pty.Cmd
	screen  *vt.Emulator
	chunks  chan []byte
	pending []byte
	log     bytes.Buffer
}

func check(err error) {
	if err != nil {
		panic(err)
	}
}

func newTerminal(ctx context.Context, binary string) *terminal {
	port, err := pty.New()
	check(err)
	t := &terminal{Pty: port, chunks: make(chan []byte, 128), screen: vt.NewEmulator(80, 24)}
	go io.Copy(io.Discard, t.screen)
	check(t.Resize(80, 24))
	t.process = t.CommandContext(ctx, binary)
	t.process.Env = append(os.Environ(), "TERM=xterm-256color")
	check(t.process.Start())

	go func() {
		defer close(t.chunks)
		buffer := make([]byte, 4096)
		for {
			n, err := t.Read(buffer)
			if n > 0 {
				select {
				case t.chunks <- bytes.Clone(buffer[:n]):
				case <-ctx.Done():
					return
				}
			}
			if err != nil {
				return
			}
		}
	}()
	return t
}

func (t *terminal) Resize(width, height int) error {
	t.screen.Resize(width, height)
	return t.Pty.Resize(width, height)
}

func (t *terminal) Close() {
	t.screen.Close()
	t.Pty.Close()
}

func (t *terminal) send(keys string) { _, err := io.WriteString(t, keys); check(err) }

func (t *terminal) expect(text string) { t.wait(text, false) }

func (t *terminal) expectOutput(text string) { t.wait(text, true) }

func (t *terminal) wait(text string, childOutput bool) {
	deadline := time.NewTimer(7 * time.Second)
	defer deadline.Stop()
	for {
		if found := bytes.Index(t.pending, []byte(text)); found >= 0 {
			t.pending = t.pending[found+len(text):]
			return
		}
		if !childOutput && strings.Contains(ansi.Strip(t.screen.Render()), text) {
			t.pending = nil
			return
		}
		select {
		case chunk, ok := <-t.chunks:
			if !ok {
				panic(fmt.Sprintf("terminal closed waiting for %q: %q", text, t.log.String()))
			}
			t.log.Write(chunk)
			_, err := t.screen.Write(chunk)
			check(err)
			t.pending = append(t.pending, chunk...)
		case <-deadline.C:
			panic(fmt.Sprintf("timed out waiting for %q: %q", text, t.log.String()))
		}
	}
}

func (t *terminal) quit(want int) {
	t.send("q")
	err := t.process.Wait()
	if t.process.ProcessState == nil || t.process.ProcessState.ExitCode() != want {
		panic(fmt.Sprintf("wanted TUI exit %d, got %v: %q", want, err, t.log.String()))
	}
}

func update(binary, failure string, want int) {
	cmd := exec.Command(binary, "update")
	cmd.Env = append(os.Environ(), "GWYN_TOOL_PROTOTYPE_UPDATE_FAIL="+failure)
	output, err := cmd.CombinedOutput()
	if cmd.ProcessState == nil || cmd.ProcessState.ExitCode() != want {
		panic(fmt.Sprintf("wanted update exit %d, got %v: %s", want, err, output))
	}
	for _, text := range []string{"Succeeded: Global Skills", "Skipped: Claude Code", "Succeeded: Remaining updates"} {
		if !bytes.Contains(output, []byte(text)) {
			panic(fmt.Sprintf("missing %q: %s", text, output))
		}
	}
	if bytes.Contains(output, []byte("Failed: Codex")) != (want == 1) {
		panic(fmt.Sprintf("unexpected failure summary: %s", output))
	}
	fmt.Printf("Non-interactive update exit %d\n", want)
}

func management(ctx context.Context, binary string) {
	t := newTerminal(ctx, binary)
	defer t.Close()

	t.expect("Manage tools")
	t.send("\r")
	t.expect("Skills / Remove")
	t.send(" j " + strings.Repeat("j", 9))
	check(t.Resize(64, 14))
	t.expect("Terminal 64x14")
	t.send("\r")
	t.expect("Review removal plan")
	t.expect("Remove Review checklist")
	t.expect("Keep Referenced skill")
	t.send("n")
	t.expect("Skills / Remove")
	t.send("\r")
	t.expect("Review removal plan")
	t.expect("Remove Review checklist")
	t.expect("Keep Referenced skill")
	t.send("y")
	t.expect("Operation results")
	t.expect("Succeeded: Review checklist")
	t.expect("Skipped: Referenced skill")
	t.send("\r")
	t.expect("Manage tools")
	t.send("j\r")
	t.expect("Rules / Remove")
	t.send("j \r")
	t.expect("Review removal plan")
	t.expect("Remove Personal notes (contains handwritten content)")
	t.send("\x1b")
	t.expect("Rules / Remove")
	t.send("\x1b")
	t.expect("Manage tools")
	fmt.Println("Management selection survives scrolling, resize, and cancellation")

	t.send("j\r")
	t.expect("Agent / Interactive operation")
	t.send("\r")
	t.expectOutput("Child ready")
	t.send("ok\r")
	t.expectOutput("Child received: ok")
	t.expect("Agent operation succeeded")
	t.send("\r")
	t.expect("Manage tools")
	t.send("\r")
	t.expect("Agent / Interactive operation")
	t.send("\r")
	t.expectOutput("Child ready")
	t.send("\x03")
	t.expectOutput("Child interrupted")
	t.expect("Agent operation cancelled")
	t.quit(0)
	fmt.Println("Child reads input and returns control after success and Ctrl+C")
}

func childFailure(ctx context.Context, binary string) {
	t := newTerminal(ctx, binary)
	defer t.Close()

	t.expect("Manage tools")
	t.send("jj\r")
	t.expect("Agent / Interactive operation")
	t.send("\r")
	t.expectOutput("Child ready")
	t.send("fail\r")
	t.expectOutput("Child received: fail")
	t.expect("Agent operation failed")
	t.quit(1)
	fmt.Println("Child failure recovers the TUI and gives session exit 1")
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "Usage: go run ./smoke PATH_TO_BINARY")
		os.Exit(2)
	}
	binary, err := filepath.Abs(os.Args[1])
	check(err)
	fmt.Printf("Native terminal check: %s/%s\n", runtime.GOOS, runtime.GOARCH)
	update(binary, "0", 0)
	update(binary, "1", 1)
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	management(ctx, binary)
	childFailure(ctx, binary)
}
