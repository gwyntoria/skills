# C Projects Agent Instructions

## Coding Style & Naming Conventions

### Formatting

C/C++ formatting follows the following rules:

- 4-space indentation, NO tabs.
- NO column limit.
- When a function declaration or call is too long, place each argument on a separate line and align the arguments after the opening parenthesis:

  ```c
  ErrCode parse_setting_result_from_response(char* response,
                                             ResultCode* code,
                                             char* description,
                                             ToolCall tool_call[],
                                             int tool_call_num)
  ```

- Keep at most one consecutive empty line.
- Left-align pointer declarators.
- Use one space before trailing comments.

Do NOT run `clang-format` to format any changed C/C++ files.

### Naming

- Use lower_snake_case for C files, headers, functions, and local variables.
- Public functions should use names such as `calculate_len()`.
- Static private functions should use a leading underscore, such as `_calculate_len()`.
- Use all-uppercase names for macros, such as `DEFAULT_WORKER_PRIORITY`.
- Format enum types and enumerators as follows:

  ```c
  typedef enum StatusCode {
      kStatusCodeOk = 0,
      kStatusCodeFail,
      kStatusCodeRuning,
      kStatusCodeStop,
      kStatusCodeInvalid,
  } StatusCode;
  ```

- Format structures as follows:

  ```c
  typedef struct ActiveObject {
      void*         _context;
      State         _state;
      MessageQueue* _msg     // private variable
      int           pub_var; // public variable
  } ActiveObject;
  ```

### Comment

- Add function comments with `@brief`, `@param`, and `@return` for new or changed functions.
- Public declarations in headers need matching comments.
- Document structs with a struct-level description and field descriptions.
- Add process comments and comments explaining `if` branches inside functions.

Use `/** ... */` for function and struct documentation, `/**< ... */` for field descriptions, and `//` for comments inside functions. Read the implementation and callers before describing behavior; update comments when that behavior changes.

#### Function Comments

Place the comment immediately above the declaration or definition. Describe the operation in `@brief`. Use `@param[in]`, `@param[out]`, or `@param[in,out]` to show each parameter's direction, and include units, valid ranges, pointer requirements, and ownership when relevant. Describe success, failure, and boundary behavior in `@return`. Omit `@return` for a `void` function and `@param` for a function with no parameters.

For example, a public declaration in a header:

```c
/**
 * @brief Advance a countdown timer by the elapsed time.
 * @param[in,out] timer Timer to update; must be non-NULL.
 * @param[in] elapsed_ms Elapsed time in milliseconds; zero leaves the timer unchanged.
 * @return true if the timer is expired after the update, including an already
 *         expired timer; false if time remains.
 */
bool timer_advance(TimerState* timer, uint32_t elapsed_ms);
```

Put the matching contract above the definition in the source file as well. Keep both comments consistent when the interface changes. Static private functions use the same comment format above their definitions.

#### Struct and Field Comments

Place the struct description above `typedef struct`. Describe each field's meaning and any unit, valid range, sentinel value, or ownership constraint. Keep one space before a trailing field comment.

```c
/**
 * @brief Countdown state updated by timer_advance().
 */
typedef struct TimerState {
    uint32_t remaining_ms; /**< Time remaining in milliseconds; zero means expired. */
} TimerState;
```

#### Process and Branch Comments

Place process comments before a logical step and branch comments beside the condition or inside the branch. Explain the purpose, boundary, or reason for the chosen action. For example, explain why the timer clamps at zero rather than writing only "check elapsed time" or "subtract elapsed time".

The corresponding source definition combines the function contract with process and branch comments:

```c
/**
 * @brief Advance a countdown timer by the elapsed time.
 * @param[in,out] timer Timer to update; must be non-NULL.
 * @param[in] elapsed_ms Elapsed time in milliseconds; zero leaves the timer unchanged.
 * @return true if the timer is expired after the update, including an already
 *         expired timer; false if time remains.
 */
bool timer_advance(TimerState* timer, uint32_t elapsed_ms)
{
    // Resolve expiration before subtracting to prevent unsigned wraparound.
    if (elapsed_ms >= timer->remaining_ms) {
        // Equality expires the timer too; clamp any overshoot to zero.
        timer->remaining_ms = 0;
        return true;
    }

    // Preserve the unconsumed time for the next update.
    timer->remaining_ms -= elapsed_ms;
    return false;
}
```

## Commit Message Guidelines

- Use Conventional Commit subjects in the form `type(scope): summary`, such as `feat(alarm): support deep sleep RTC wake` and `fix(config): increase TCP window size to 11200`.
- Common types are `feat`, `fix`, `refactor`, `test`, `docs`, and `chore`.
- Keep the type and scope lowercase, and write a concise English summary that starts with an imperative verb.
