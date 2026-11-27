---
name: check-mode
description: Automatically invoke this skill as the final check for every task that creates or modifies a Python, Shell, or Markdown file or edits code comments. Run the applicable formatting, linting, and manual checks on the files changed by the task.
---

# Check Changed Files

## Run the checks

After editing, collect the exact files changed by the task. Use the table to group them by check. Run each matching script with Bash 5.x from the target project root. Pass the paths for that group as separate arguments and quote each path. Use `--` before paths that start with a hyphen. Expand the scope to the entire project only for a project-wide cleanup.

| Changed files | Script | What it does |
| --- | --- | --- |
| Python files, including `.py` and `.pyi` | [scripts/check-python.sh](scripts/check-python.sh) | Runs `ruff check --fix`, then `ruff format`. Pass `--config PATH` when the project specifies one. Otherwise Ruff resolves the project configuration or the script applies its isolated fallback. |
| Bash and POSIX Shell scripts, including extensionless executables and sourced files | [scripts/check-shell.sh](scripts/check-shell.sh) | Runs `shfmt` in write and diff modes, then `shellcheck -x` on each file. Pass `--dialect bash` or `--dialect sh` for files without a supported shebang. Pass `--indent N` for the project's indentation. The default is four spaces, and `0` uses tabs. |
| Markdown files | [scripts/check-markdown.sh](scripts/check-markdown.sh) | Runs `markdownlint-cli2 --fix`, then `textlint --fix` for spacing and parentheses. The script supplies both configurations and maps its temporary filenames back to the files passed in. |

```bash
bash "$skill_dir/scripts/check-python.sh" -- "src/main.py" "src/model.pyi"
bash "$skill_dir/scripts/check-shell.sh" --dialect bash -- "bin/run" "lib/common.sh"
bash "$skill_dir/scripts/check-markdown.sh" -- "README.md" "docs/notes.md"
```

Set `skill_dir` to the directory containing this `SKILL.md`. Group Shell files with different explicit dialect or indentation requirements into separate calls. Pass every changed sourced file directly to the Shell script so ShellCheck can report its own diagnostics.

The scripts modify the specified files in place. A nonzero exit means a file or check could not be processed, a tool or rule was missing, or diagnostics remain. If a tool is unavailable, the script prints an installation command and continues with the checks it can run. If the project pins a version, use that version. Resolve issues caused by your changes and rerun the relevant script.

## Check Markdown references and images

- Use numeric footnote markers such as `[^1]` for external sources. Number sources by first citation, then reuse each number for later citations of the same source. Fix named markers, duplicate numbers for the same source, and markers without matching reference entries.
- End the note with a `## References` section. Order entries by citation number using `1. [^1]: Author, [Title](URL), year.` for the first entry. Add a short description when useful.
- Store note images at `./assets/<note-stem>/<image-name>.png` relative to the note, where `<note-stem>` is the filename without `.md`. Use that relative path in the Markdown image link and confirm it resolves to the image. If you move an image to fix its path, update affected links.

## Check code comments

Keep comments whose removal would cost maintainers information. Review comments affected by your edit against the current code and apply these checks.

- Explain decisions, business rules, and historical compatibility reasons that the code alone cannot reveal. Keep concurrency, timing, and performance constraints that maintainers must preserve.
- Document public contracts, errors or exceptions, and boundary conditions that callers rely on. Keep each contract in one authoritative location unless the project requires duplication.
- Explain complex algorithms and cite relevant sources when they help readers understand or verify the implementation.
- Update comments affected by behavior changes. Prefer clear names and structure for operations that can explain themselves. Remove comments that repeat the code and commented-out implementations within the task's scope.
- Make `TODO` and `FIXME` comments state the unresolved problem and link to an issue when available.
- Follow the project's comment style and language. Otherwise use the language's standard documentation format and the user's requested language, defaulting to English.

## Sign-off

Include `status`, `scope`, and `verification` in the final reply's verification section, in that order. When `/check` is also active, put these lines under its `verification` field.

```text
status: check-mode blocked — markdownlint-cli2 is missing
scope: 1 file — README.md
verification:
- bash "$skill_dir/scripts/check-markdown.sh" -- "README.md" → exit 1
  - markdownlint-cli2 → blocked (tool missing)
  - textlint → pass
- Markdown image paths → pass (linked files exist)
```

- `status` uses `fail` when a check found a problem that remains in the changed files, `blocked` when a prerequisite prevented an applicable check and no file problem remains, or `pass` when all applicable checks passed. Include any blockers in `verification` even when the overall status is `fail`.
- `scope` counts distinct in-scope files, including files whose checks were blocked. Name the files here or in the verification entries.
- `verification` records each applicable check's latest result. For scripts, include the command, exit code, and any remaining diagnostic or blocker with the affected paths. Use the output to classify a nonzero exit and report the subcheck results it establishes. For manual checks, name what you inspected and what you found. Omit inapplicable checks.
