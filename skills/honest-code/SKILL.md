---
name: honest-code
description: Apply the Honest Code principles when writing, reviewing or refactoring code. Use when writing new code, reviewing a diff, refactoring, or when the user asks to make code "honest". Enforces no hidden state, no silent failure, no swallowed error, no implicit default. Delegates every mechanically decidable rule to honest-check and names the ones that need a person.
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(git diff*), Bash(git log*), Bash(honest-check*)
---

# Honest Code

The other skills in this repository make a model report what it cannot do. This one makes the *code* do it.

That is the thread running through every rule below. A class holding hidden state cannot tell you what it will do next. A caught-and-swallowed exception reports success for work that failed. An implicit default absorbs the caller's omission, so the program cannot tell "chose 30 seconds" from "forgot to say." A defensive check re-tests something the signature already promised, which means the promise was never trusted. Each is a way for code to be quietly wrong, and each rule removes one.

Seventeen principles follow. The numbering is the Honest Framework's, not this file's, so that a rule number means one thing across every Open Honest artifact.

## What decides each rule, and what cannot

Most of these are decidable from source, and a linter decides them. Run it rather than eyeballing them:

```bash
honest-check path/to/module.py
```

It ships with the [Honest Framework](https://github.com/openhonest/honest-framework). Its verdict is the operational definition: code that passes is structurally Honest, and there is no "mostly."

| # | Principle | Decided by |
|---|---|---|
| 1 | Dict-lookup polymorphism over if/elif chains | `HC-P001` |
| 2 | Typed dicts over classes | `HC-P003`, `HC-P007`, `HC-P010` |
| 3 | Pure functions over methods | `HC-P003`, `HC-P004` |
| 4 | I/O at the boundary | `HC-P004`, `HC008` |
| 5 | Flat composition over inheritance | `HC-P003`, `HC-OR001` |
| 6 | DOM as state | partly: `HC-P004` catches `localStorage` and the store libraries |
| 7 | HTML attributes over imperative DOM | partly: `HC-P011` catches `addEventListener` |
| 8 | Typed exceptions at the boundary | `HC-P002` |
| 9 | SQL over application caches | `HC-P006` |
| 10 | Pure-function assertions over mocks | `honest-test`, at test time |
| 11 | Type declarations over imperative validation | `HC-P005` |
| 12 | Context managers over instance state | `HC-P007` |
| 13 | Configuration as parameters | `HC-P007`, `HC-P004` |
| 14 | Simple test steps signal honest architecture | `honest-test`, at test time |
| 15 | Declarative equivalents over lifecycle hooks | `HC-P011` |
| 16 | Strangler pattern for migration | **nothing.** It is a process, not a property of code |

Two of the sixteen are only partly decidable and one is not decidable at all. Say so when you report, rather than implying the linter covered everything. A rule nobody checked is not a rule that passed.

## The rules

### 1. Dict-lookup polymorphism over if/elif chains

Dispatching on a value to select behaviour belongs in a table.

```python
# BAD
if channel == "email": send_email(data)
elif channel == "sms": send_sms(data)

# GOOD
HANDLERS = {"email": send_email, "sms": send_sms}
HANDLERS[channel](data)
```

Only flag chains that dispatch on a value to select behaviour. Bounds checks, null guards and boolean logic are ordinary conditionals and are fine.

The table is also an option rather than a prediction: a case discovered in month six arrives as a row instead of a rewrite. Build one when you can name the axis of variation and it has a finite set of kinds. Where you cannot name the axis, write the concrete function and let the table appear when the second and third real cases show you what varies.

### 2. Typed dicts over classes

A class whose job is holding data, with an `__init__` that only assigns fields and no methods beyond accessors, is a dict with ceremony. Use `TypedDict` in Python, a plain object or interface in TypeScript, a struct in Go, a hash in Ruby.

Classes are acceptable when they wrap a stateful external resource, a connection or a socket, or when a framework requires them. Even then, keep the methods to what the framework demands.

### 3. Pure functions over methods

A method that reads `self` only to reach data it could have received as a parameter is a function wearing a class. `user.validate()` becomes `validate_user(user)`.

### 4. I/O at the boundary

Business logic that queries a database, makes an HTTP request, reads a file or logs has made itself untestable without a mock. Move the I/O to the caller. The interior receives data and returns data.

### 5. Flat composition over inheritance

Inheritance for code reuse hides where behaviour comes from. `pipe(validate, authenticate, create_order)` shows the whole sequence at the point of assembly.

### 6. DOM as state

Server-rendered HTML, swapped in by HTMX or an equivalent, with no client-side store duplicating what the server already knows. A Redux or Zustand store holding a copy of server state is a second source of truth, and two sources of truth means one of them is lying.

Where the stack rules this out, keep client state minimal and derived from server responses rather than accumulated.

### 7. HTML attributes over imperative DOM

`hx-post`, `hx-target`, `hx-trigger` declare what should happen. `addEventListener` plus `querySelector` describes how, in a place the reader has to go and find.

### 8. Typed exceptions at the boundary

Let functions raise. The boundary catches and maps exception types to responses. A try/except deep in business logic is where an error goes to be forgotten, and catch-and-swallow is the purest form of a silent failure.

Retry logic belongs in infrastructure, not inline.

### 9. SQL over application caches

Profile the query before adding Redis. Add the index, fix the join. A cache added before measurement hides the problem and adds an invalidation bug.

### 10. Pure-function assertions over mocks

`assert f(input) == expected` is the whole test. Three or more mocks in one test means the function has hidden dependencies; extract the pure logic and test that.

### 11. Type declarations over imperative validation

Declare a schema and let the machinery enforce it, rather than chaining `isinstance` and length checks.

**Defensive programming is a smell here, not prudence.** Re-checking a value the signature already types, or scattering guard clauses through business logic, is distrust of your own contracts. It means the boundary or the type is too loose, and the fix is a tighter boundary or type, never another guard. When reviewing, do not credit defensive checks as robustness. Count them as a violation.

### 12. Context managers over instance state

`async with create_connection(config) as conn:` scopes the resource. A connection stored on `self` with a manual lifecycle is a leak waiting for an exception.

### 13. Configuration as parameters

Pass `config` to the functions that need it. A module-level singleton or `self._config` makes every function's behaviour depend on something no caller can see.

### 14. No implicit defaults

`def f(x, timeout=30)` silently absorbs the caller's omission. The program can no longer distinguish a caller who chose thirty seconds from one who forgot, and the non-default region is invisible at every call site, so nothing exercises it.

A default is catch-and-swallow applied to inputs. It manufactures an untested input region by construction.

Encode absence as an explicit member of a bounded type, a Maybe or a named `Nothing`, resolved in a visible boundary step and exercised by a test. The `=` is the swallow; the boundary resolve is the surfaced decision.

### 15. Declarative equivalents over lifecycle hooks

A `useEffect` that fetches on mount, a signal handler, an ORM callback: each puts behaviour somewhere the reader does not look. Declare it where it happens.

### 16. Strangler pattern for migration

Route new traffic to the new implementation, leave the old one serving what it already serves, and delete it when nothing reaches it. Do not rewrite in place.

Nothing checks this one. It is a property of how you sequence work, not of the code, and no linter will ever see it.

### 17. Atomic test-and-set over check-then-act
A guard that reads a shared value and then writes it is not a guard. Between the read and the write another caller reads the same answer, and both proceed believing they hold the thing exclusively. Any await in between makes the race certain rather than occasional. Use one operation whose return value distinguishes "I took it" from "someone else holds it": an atomic insert, a compare-and-swap, an insert-if-absent. The token written must be unique to the caller, because every later caller reads a shared sentinel back and matches it.

## How to apply it

**Writing new code:** follow the rules from the start. No class for data, no if/elif dispatch, I/O at the boundary.

**Reviewing or refactoring:** run `honest-check` first, then read for the rules it cannot decide. Report in this order:

1. What the linter flagged, by rule ID
2. What you found that it cannot see: rule 16 always, rules 6 and 7 partly, and any case where the code passes the letter and breaks the intent
3. What you did not check, and why

Fix what you can. Where a violation cannot be fixed without breaking an external API, say so and leave it.

## What this skill does not do

It does not add abstraction that nothing needs. It does not refactor code that already complies. It does not apply a rule where a framework forbids the alternative, and Django models and React components are the usual cases. It does not flag ordinary conditional logic as a dispatch violation.

And it does not claim the linter's verdict as its own. `honest-check` decides what it decides; this skill reports the rest and names what neither of them looked at.
