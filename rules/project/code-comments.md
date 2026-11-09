# Code Comment Guidelines

Write comments that explain interface contracts, data meaning, and implementation decisions across programming languages. Apply these rules to new or modified code and affected comments; leave unrelated code alone.

## Format and Language

- Follow the project's comment and documentation conventions. When none exist, use the language's customary format, such as Python docstrings, JavaScript/TypeScript JSDoc/TSDoc, or Rust documentation comments. Use documentation tags only where the chosen format calls for them.
- Follow the project's existing comment language. If unspecified, follow the user's requested language; otherwise default to English. Keep the same language within a module where practical, and preserve identifiers and protocol names. Leave unrelated existing comments in their original language.

## Function and Method Contracts

- Document public interfaces and internal functions or methods with complex constraints. Simple accessors and other self-explanatory functions may omit comments.
- Describe the operation and the information a caller needs to use it correctly. Include parameter constraints, units, valid ranges, nullability, ownership, return values, success and failure conditions, errors or exceptions, boundary behavior, and side effects where relevant. Document only the items that apply; avoid repeating information already clear from names and type signatures.
- Keep each contract in one authoritative location that callers and documentation tools use, unless the project requires duplication. For example, public C/C++ interfaces usually belong in headers, while Python contracts usually belong in docstrings at the definition. Use comments at the implementation for additional algorithm decisions and internal constraints.

## Types, Fields, and Properties

- Describe a type's purpose and invariants when they are not clear from its name and structure.
- Explain field and property meanings where needed, including units, valid ranges, sentinel values, nullability, and ownership constraints. Self-explanatory fields and properties may omit comments.

## Process and Branch Comments

- Add comments where a logical step or branch has a purpose, boundary condition, or constraint that is not apparent from the code. Place them near the relevant step or condition.
- Explain why an algorithm, ordering, workaround, or special case is necessary. Avoid narrating assignments, loops, or conditions that the code already makes clear.

## Accuracy and Maintenance

- Read the implementation and relevant callers or tests before describing behavior. Verify design reasons from available evidence; if a reason remains unclear, ask for clarification rather than inventing an explanation.
- Update affected comments when behavior or interface constraints change. Keep documentation consistent with the code without expanding the task into a file-wide comment cleanup.
