# Writing Repositories Agents Instructions

## Image File Path

Save note images under `./assets/<filename>/<image-name>.png`, where `./assets` is the assets subdirectory beside the owning Markdown file and `<filename>` matches that file without its `.md` extension. Reference the image from the note with a relative Markdown path.

## Code File Path

Save code accompanying a note under `./assets/code/<filename>/`, where `./assets` is the assets subdirectory beside the owning Markdown file and `<filename>` matches that file without its `.md` extension. Reference the code from the note with a relative Markdown path.

## References and Footnotes

For Markdown notes with external references:

- Cite sources in the body with numeric footnote markers, for example `[^1]`. Assign numbers by first appearance and reuse the same number for repeated citations of the same source.
- Add a `## References` section at the end of the note. List references in numeric order as an ordered list, using the form `1. [^1]: Author, [Title](URL), year.`, with a short description when useful.
- Do not use named footnote markers such as `[^active-object]`.

## Markdown File Format

After finishing edits to a Markdown file, format only the files that was changed with `markdownlint-cli2`, then run `textlint` to apply typography fixes and terminology replacements.

```bash
npx markdownlint-cli2 --fix --no-globs path/to/file.md
npx textlint --fix path/to/file.md
```

Avoid running broad auto-fix commands unless the task is specifically to clean up formatting across the repository.
