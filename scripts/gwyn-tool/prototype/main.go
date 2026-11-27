// gwyn-tool interaction prototype. All management and update data are fixtures.
package main

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"strings"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/ansi"
)

var menus = []string{"Skills", "Rules", "Agent"}
var entries = [][]string{
	{"Review checklist", "Referenced skill", "Writing guide", "Release notes", "Troubleshooting", "Migration notes", "Example skills", "Team workflows", "Build guide", "Testing guide", "Design review", "Documentation"},
	{"Project conventions", "Personal notes (contains handwritten content)", "Formatting guide"},
}

type childFinished struct{ err error }

type model struct {
	screen     string
	menu       int
	cursor     int
	chosen     [2][12]bool
	width      int
	height     int
	result     []string
	hadFailure bool
}

func (m model) Init() tea.Cmd { return nil }

func (m model) selected() int {
	count := 0
	for i := range entries[m.menu] {
		if m.chosen[m.menu][i] {
			count++
		}
	}
	return count
}

func (m model) planned() []string {
	var lines []string
	for i, name := range entries[m.menu] {
		if !m.chosen[m.menu][i] {
			continue
		}
		if m.menu == 0 && i == 1 {
			lines = append(lines, "Keep "+name+" (external reference)")
		} else {
			lines = append(lines, "Remove "+name)
		}
	}
	return lines
}

func (m model) apply() []string {
	var lines []string
	for _, step := range m.planned() {
		if strings.HasPrefix(step, "Keep ") {
			lines = append(lines, "Skipped: "+strings.TrimPrefix(step, "Keep "))
		} else {
			lines = append(lines, "Succeeded: "+strings.TrimPrefix(step, "Remove "))
		}
	}
	return lines
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
	case childFinished:
		m.screen = "result"
		if msg.err == nil {
			m.result = []string{"Agent operation succeeded"}
			return m, nil
		}
		var status *exec.ExitError
		if errors.As(msg.err, &status) && status.ExitCode() == 130 {
			m.result = []string{"Agent operation cancelled"}
		} else {
			m.hadFailure = true
			m.result = []string{"Agent operation failed: " + msg.err.Error()}
		}
	case tea.KeyPressMsg:
		key := msg.String()
		if key == "q" || key == "ctrl+c" {
			return m, tea.Quit
		}
		switch m.screen {
		case "home":
			switch key {
			case "up", "k":
				m.menu = max(0, m.menu-1)
			case "down", "j":
				m.menu = min(len(menus)-1, m.menu+1)
			case "enter":
				m.cursor = 0
				m.screen = "select"
				if m.menu == 2 {
					m.screen = "agent"
				}
			}
		case "select":
			switch key {
			case "up", "k":
				m.cursor = max(0, m.cursor-1)
			case "down", "j":
				m.cursor = min(len(entries[m.menu])-1, m.cursor+1)
			case "space", " ":
				m.chosen[m.menu][m.cursor] = !m.chosen[m.menu][m.cursor]
			case "enter":
				if m.selected() > 0 {
					m.screen = "preview"
				}
			case "esc":
				m.screen = "home"
			}
		case "preview":
			switch key {
			case "esc", "n":
				m.screen = "select"
			case "y":
				m.result = m.apply()
				m.screen = "result"
			}
		case "agent":
			switch key {
			case "esc":
				m.screen = "home"
			case "enter":
				executable, err := os.Executable()
				if err != nil {
					return m, func() tea.Msg { return childFinished{err} }
				}
				return m, tea.ExecProcess(exec.Command(executable, "__child"), func(err error) tea.Msg {
					return childFinished{err}
				})
			}
		case "result":
			if key == "enter" || key == "esc" {
				m.screen = "home"
			}
		}
	}
	return m, nil
}

func (m model) View() tea.View {
	title := "gwyn-tool prototype"
	size := fmt.Sprintf("Terminal %dx%d", m.width, m.height)
	lines := []string{title, size, ""}
	var footer string

	switch m.screen {
	case "home":
		lines = append(lines, "Manage tools")
		for index, name := range menus {
			marker := "  "
			if index == m.menu {
				marker = "> "
			}
			lines = append(lines, marker+name)
		}
		footer = "Up/Down Move | Enter Open | q Quit"
	case "select":
		lines = append(lines, menus[m.menu]+" / Remove", fmt.Sprintf("Selected %d", m.selected()))
		visible := max(1, m.height-7)
		first := max(0, m.cursor-visible+1)
		list := entries[m.menu]
		for index := first; index < min(len(list), first+visible); index++ {
			marker, checked := "  ", "[ ] "
			if index == m.cursor {
				marker = "> "
			}
			if m.chosen[m.menu][index] {
				checked = "[x] "
			}
			lines = append(lines, marker+checked+list[index])
		}
		footer = "Up/Down Move | Space Select | Enter Preview | Esc Back"
	case "preview":
		lines = append(lines, "Review removal plan")
		lines = append(lines, m.planned()...)
		footer = "y Simulate removal | Esc Back | n Cancel"
	case "agent":
		lines = append(lines, "Agent / Interactive operation", "", "Run a child process in this terminal.")
		footer = "Enter Run | Esc Back | q Quit"
	case "result":
		lines = append(lines, "Operation results")
		lines = append(lines, m.result...)
		footer = "Enter/Esc Menu | q Quit"
	}

	lines = append(lines, "", footer)
	for i, line := range lines {
		lines[i] = ansi.Truncate(line, m.width, "…")
	}
	view := tea.NewView(strings.Join(lines, "\n"))
	view.AltScreen = true
	return view
}

func fixtureUpdate() int {
	fmt.Println("Succeeded: Global Skills")
	fmt.Println("Skipped: Claude Code (demo channel unavailable)")
	exitCode := 0
	if os.Getenv("GWYN_TOOL_PROTOTYPE_UPDATE_FAIL") == "1" {
		fmt.Println("Failed: Codex (demo exit 7)")
		exitCode = 1
	}
	fmt.Println("Succeeded: Remaining updates")
	return exitCode
}

func interactiveFixture() int {
	interrupt := make(chan os.Signal, 1)
	signal.Notify(interrupt, os.Interrupt)
	defer signal.Stop(interrupt)
	fmt.Println("Child ready: type ok or fail. Ctrl+C cancels.")
	input := make(chan string, 2)
	go func() {
		defer close(input)
		scanner := bufio.NewScanner(os.Stdin)
		for i := 0; i < 2 && scanner.Scan(); i++ {
			input <- strings.TrimSpace(scanner.Text())
		}
	}()
	var response string
	select {
	case <-interrupt:
		return 130
	case response = <-input:
	}
	fmt.Println("Child received:", response)
	fmt.Println("Press Enter to return to the TUI.")
	select {
	case <-interrupt:
		return 130
	case <-input:
	}
	if response == "ok" {
		return 0
	}
	return 7
}

func run(args []string) int {
	if len(args) > 0 {
		switch args[0] {
		case "update":
			return fixtureUpdate()
		case "__child":
			return interactiveFixture()
		case "-h", "--help":
			fmt.Println("gwyn-tool prototype [update]")
			fmt.Println("Fixtures only. Set GWYN_TOOL_PROTOTYPE_UPDATE_FAIL=1 to simulate an update failure.")
			return 0
		default:
			fmt.Fprintln(os.Stderr, "Usage: gwyn-tool prototype [update]")
			return 2
		}
	}
	initial := model{screen: "home", width: 80, height: 24}
	final, err := tea.NewProgram(initial).Run()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if final.(model).hadFailure {
		return 1
	}
	return 0
}

func main() { os.Exit(run(os.Args[1:])) }
