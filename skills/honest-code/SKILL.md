---
name: honest-code
description: Apply the Honest Code principles when writing, reviewing or refactoring code. Use when writing new code, reviewing a diff, refactoring, or when the user asks to make code "honest". Enforces no hidden state, no silent failure, no swallowed error, no implicit default. Delegates every mechanically decidable rule to honest-check and names the ones that need a person.
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(git diff*), Bash(git log*), Bash(honest-check*)
---

# Honest Code

The other skills in this repository make a model report what it cannot do. This one makes the *code* do it.

That is the thread running through every rule below. A class holding hidden state cannot tell you what it will do next. A caught-and-swallowed exception reports success for work that failed. An implicit default absorbs the caller's omission, so the program cannot tell "chose 30 seconds" from "forgot to say." A defensive check re-tests something the signature already promised, which means the promise was never trusted. Each is a way for code to be quietly wrong, and each rule removes one.

Nineteen principles follow. The numbering is the Honest Framework's, not this file's, so that a rule number means one thing across every Open Honest artifact.

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

Two of the nineteen are only partly decidable and one is not decidable at all. Say so when you report, rather than implying the linter covered everything. A rule nobody checked is not a rule that passed.

## The rules

The text below is the Honest Code principles, held here rather than fetched, because a skill that must go and read a file pays that cost on every invocation and the step that costs something is the step that gets skipped.

It is a copy, and copies drift: these principles once lived in twelve places holding twenty-two versions between them, with no copy holding them all. So this one cannot go stale without stopping a push. `tools/vendor_check.py` compares it against the source on GitHub before every push of this repository and refuses the push when they differ, or when it cannot check.

The commit it was taken from is recorded in the block. Read it against https://github.com/openhonest/honest-code-principles if you want to confirm it yourself. A released copy is a snapshot: the source can move the day after a release, and the recorded commit is how you tell.

<!-- BEGIN VENDORED honest-code-principles.md @ 5a0ce96d009615ce328dc02bbc968f42772b9098 -->
# Honest Code: Coding Principles

Every principle names a category of defect and removes it. A practice that does not eliminate a named category of bug is a style preference, and does not belong here.

This is the single source.

## Lookup Polymorphism
Imperative conditional structures (if/elif/else chains) can easily create order dependent logic that is fragile and difficult to reason about.

Almost any dispatch can be replaced by a dict/array/map mapping keys to functions: `HANDLERS = {"email": send_email, "sms": send_sms}` then `HANDLERS[channel](data)`. The dict is a declarative dispatch table. Adding a new case means adding a row, not modifying potentially fragile control flow. The table is read by a polymorphic pure function whose operations vary depending upon the values looked up by the key.

**Enforced by** honest-check HC-P001, statically, at the gate.

## Pure Functions Over Methods
Public methods in classes are an open door to promiscuous state mutation that creates a mathematically infinite number of possible call sequences, since calls repeat without bound, which makes it impossible to exhaustively test program behavior.

A method like `user.validate()` that mutates internal state becomes `validate_user(user: dict) -> dict`. Input in, output out. The function has no access to `self` because there is no `self`. No side effects, no surprises.

A `class User` with fields, methods, getters, setters, and lifecycle hooks becomes `User = TypedDict("User", {"email": str, "name": str})`. The data is just data, with no behaviour attached. If you can't `json.dumps()` it, it's too clever by half.

Java and C# do not allow standalone functions. Honest Code is still writable in them by wrapping the function in a class exposing a single public method, which is the language's syntax for a function and not a return to objects.

**Enforced by** honest-check HC-P003, HC-P007 and HC-P010, statically, at the gate.

## I/O at the Boundary
Sprinkling input/output (I/O) operations—such as database queries, network requests, or file reads/writes—throughout your business logic tightly couples your code to external systems. This creates major structural and performance issues, and it makes the code impossible to keep DRY. The defects follow from the coupling: the logic cannot be tested without the external system standing behind it, none of it can be reused anywhere the system is absent, and there is no single place to change how the program talks to the outside.

Honest Code requires pure business logic functions in the middle; I/O (database, HTTP, file system) happens once, at the edges (route handlers, CLI entry points). The input boundary calls the pure function (either directly or through an orchestrator function that creates chains of functions defined in lookup tables) and then does the I/O with the result. This is why Honest Code has no mocks: the pure core has nothing to mock.

**Enforced by** honest-check HC-P004 and HC008, statically, against a named list of calls that reach outside the process. The list is the limit: a call it does not name is not caught.

## Composition Over Inheritance
An inheritance chain hides the code that actually runs. `class B extends A extends Base` tells you where a method is declared, not which one executes: that is decided at call time by the resolution order, and a `super()` call can land anywhere in the chain. The code you read and the code that runs are two different things, and nothing in the file marks where they part company.

Instead of `class B extends A extends Base`, use `pipe(validate, authenticate, rate_limit, create_order)`. Each step is an independent function. The pipeline is visible at the point of assembly. No `super()` calls, no hidden method resolution order. Functions are sequenced using orchestrators and the sequencing order is a lookup table. An orchestrator is the root of one operation and does not call another orchestrator: nesting them re-introduces exactly the invisible sequencing this principle removes, which is why honest-check treats it as an error (HC-OR001).

**Enforced by** honest-check HC-P003 and HC-OR001, statically, at the gate.

## DOM as State (DATAOS)
Redux/MobX/Zustand synchronize a shadow copy of server state and it is inevitable that this synchronisation will break.

Instead Honest code dictates that the DOM *is* the state. The server renders HTML and HTMX swaps it into the page. `hx-get` + `hx-target` replaces `useState` + `useEffect`. One copy of truth, not two. [DATAOS.software](https://dataos.software) is the canonical reference. This also provides closure for testing. When the server generates the front-end, reasoning about I/O becomes possible in a way that is not possible with the other approaches.

**Enforced by** honest-check HC-ST002, and by HC-P004 for browser storage calls. HC-ST002 reads the manifest the templates declare, so it is only as complete as that declaration.

## HTML Attributes Over Imperative DOM Manipulation
Imperative wiring is order-dependent and redundant by construction. Hand-written setup has to run in the right sequence, and a second piece of code touching the same element is a second copy of the same intent that can disagree with the first.

Instead of `addEventListener`, `querySelector` and `innerHTML` in JavaScript, declare `hx-post="/endpoint"`, `hx-target="#result"`, `fx-format="currency"`. The attribute declares intent; the library supplies mechanism. A declaration on the element is that intent stated once, in one place, with no order to get wrong.

**Partly enforced** by honest-check's JavaScript rules, HC-P011 and the imperative-DOM checks. A hand-written listener is caught; whether a declaration would have served better is a reading, not a check.

## References Resolve Statically
Every identifier a rendered artifact names is a reference across a boundary: an `hx-get` to a route, a `class` to a stylesheet rule, a `{% include %}` to a template. Asserting the artifact contains the string proves it was written, not that it resolves: two green tests can describe a button and a menu that never connect.

Resolve every emitted reference to its definition at the gate, not in a running browser, and generate agreeing artifacts from one declaration so they cannot disagree.

**Enforced by** honest-check HC-REF001 to HC-REF004, statically, at the gate. Each resolves an emitted reference to its definition and fails when there is none.

## Typed Exceptions at the Boundary
A `try` inside business logic ends the caller's ability to know what happened. The fault is caught, something is logged or a default returned, and the function reports success to a caller with no way to ask. Every catch in the interior is a fault that stops at that line and never reaches anyone who could act on it.

Don't catch inside business logic. Let functions raise. The route handler (or supervisor) catches, inspects the exception type (`ValidationError`, `GatewayTimeout`), and returns the appropriate status code. Retry logic belongs in the task queue infrastructure, not inline in the function.

**Enforced by** honest-check HC-P002, statically, at the gate.

## SQL Over Application Caches
A cache is a second copy of data that is already authoritative somewhere else, and the two agree only until something changes. Every write becomes two writes that can disagree, and the disagreement is silent: a stale answer is shaped exactly like a fresh one, so nothing downstream can tell them apart.

Before adding a cache, profile the query. A single SQL join with proper indexes runs under 3ms. The cache adds invalidation bugs, stale data, and a second source of truth. Fix the query or the schema first. Only cache after measurement proves it necessary. In our measurements SQLite outperformed Redis, because a local read beats a network round trip. Redis earns its place only where mutable state has to be shared across server instances, such as auth tokens.

**Partly enforced** by honest-check HC-P006, which requires a cache to carry a profiling annotation. It enforces that you measured, never that the measurement justified the cache.

## Pure Function Assertions Over Mocks
A mock makes a test agree with itself. It replaces the thing under test with a description of what you already believe, so the test passes when the belief matches the code and keeps passing when belief and code are wrong together. A suite built on mocks tells you the code still does what it did, never that it does what it should.

`assert f(input) == expected_output`. That is the whole test. If you need 9 mocks to test a function, the function has 9 hidden dependencies. Extract the pure logic; test it directly. Test the wiring separately with integration tests that hit real services. NO MOCKS.

**Enforced by** honest-test, which refuses a monkeypatch, a `mock.patch` or a runtime rebinding in a test body at collection time. honest-check catalogues HC-P012 for the same rule and does not emit it, so the static half is documented and absent.

## Type Declarations Over Imperative Validation
A hand-written check is a copy of a constraint that already exists elsewhere. The column is `varchar(255)`, the field is typed, the form says `type="email"`, and then a function checks all three again in its own words. Copies drift, and the copy that drifts is the one on the path nobody exercised.

Instead of writing `if not isinstance(x, str)`, `if len(x) > 255`, `if not re.match(...)`, declare a schema in your language's validation layer, a TypedDict, a SQL column constraint, or an `<input type="email">`. The runtime, type checker, database, or browser enforces the constraint. The programmer declares it; the machinery enforces it.

**Enforced by** honest-check HC-P005, statically, at the gate.

## Context Managers Over Instance State
A resource stored on an instance outlives the work it was opened for. Nothing in the code says when it closes, so closing becomes somebody else's job, and on the path where that somebody is a crash it does not happen at all.

Instead of `self._connection = await connect()` stored on a class, use `async with create_connection(config) as conn:`. The connection opens and closes within the scope. No persistent state leaks into the caller. Crash recovery is trivial because there's nothing to clean up.

**Enforced by** honest-check HC-P007, statically, at the gate.

## Configuration as Parameters
Configuration set in a constructor is a dependency the signature does not mention. A reader cannot see what a function needs, a caller cannot supply it, and the order things are constructed in decides whether the program works, on a sequence nobody wrote down.

Instead of `self._config` set in `__init__`, pass `config: dict` as an argument to each function that needs it. The dependency is visible in the signature. No hidden state, no initialization order bugs.

**Enforced by** honest-check HC-P007 and HC-P004's global-read clause, statically, at the gate.

## No Implicit Defaults
`def f(x, timeout=30)` silently absorbs the caller's omission. Afterwards the program cannot distinguish a caller who chose thirty seconds from one who forgot, and the non-default region is invisible at every call site, so nothing exercises it. A default is catch-and-swallow applied to inputs, and it manufactures an untested input region by construction.

Encode absence as an explicit member of a bounded type, a Maybe or a named `Nothing`, resolved in a visible boundary step and exercised by a test. The `=` is the swallow; the boundary resolve is the surfaced decision.

**Nothing enforces this.** No rule exists for a defaulted parameter in any checker here. It is the most-cited principle in this document's own tooling and the least defended, and a defaulted argument will pass every gate we run.

## Dispatch Tables Close Open Input
An open input space cannot be tested in full, so the work is to close it, and a table with its keys written out is how you close it. The keys are the type. `HANDLERS = {"email": send_email, "sms": send_sms}` declares that exactly two channels exist, so the partition a test must cover is two, whatever the caller passes. The same move works whether the value selects a handler, a format, a parser or a node kind, and it is why `getattr(obj, name)` is honest when `name` ranges over a declared set and dishonest when it ranges over the request. The line is bounded against unbounded, never static against dynamic.

The half that gets dropped is the miss. Read the table by subscript and let an unknown key raise. `table.get(key, default)` files an input nobody wrote a rule for under an answer somebody wrote for a different input, and afterwards nothing can tell the two apart. That is the input side of silent failure, and it does more damage here than anywhere else: the table was the thing that made the space enumerable, so a default quietly re-opens it while the code still reads closed. Where a miss is genuinely expected, return it as a named case the caller has to handle, never as a value shaped like a hit.

Then record what missed. An unknown key is not the caller's mistake, it is a gap in your table, and a table only grows correctly if the misses are collected rather than absorbed. The bug category this eliminates is an unhandled input read as a handled one.

**Partly enforced** by honest-check HC-P018 for an unbounded call target and HC-P013 for an unbounded routing key. The other half, a lookup read with a default instead of by subscript, is not checked by anything.

## Atomic Test-and-Set Over Check-Then-Act
A guard that reads a shared value and then writes it is not a guard. Between the read and the write another caller reads the same answer, and both proceed believing they hold the thing exclusively. Under real threads this is rare enough to be unreproducible from a bug report; under an async runtime it is not rare at all: any await between the two, a log line or a metric or any I/O, makes the race certain rather than occasional, and the code that does it looks completely ordinary.

Express the guard as one operation whose return value distinguishes "I took it" from "someone else holds it": an atomic insert, a compare-and-swap, an insert-if-absent. The token written must be unique to the caller, because a shared sentinel is not a fix, because every later caller reads it back, matches it, and reports success. The bug category this eliminates is a guard that reports protection while protecting nothing.

**Nothing enforces this.** No rule exists. A read followed by a write passes every gate here, and the race it admits is the kind that reproduces rarely enough to be argued away.

## Logging Is a Declared Boundary, and an Error Is Returned
A log line written from inside a function is a return value that skipped the type system. The function produces an observable output its signature never admits, so no caller can see it, no test can assert on it without capturing output, and no caller can decline it.

Two rules follow. **An error is returned, never written**: a function that logs a failure and carries on has reported it somewhere the caller cannot reach, and logging instead of returning is how a failure gets lost. **Information goes through one logging function of your own**, declared as a boundary, and every other function calls that one. `logger.info(...)` reaches a global you did not declare and cannot substitute, so twenty-four call sites become twenty-four independent edges; one declared function is a single edge that decides format, level, destination, and whether to write at all.

**Partly enforced** by honest-check HC-P004, whose I/O list names the logging calls that emit. That catches information written from the interior. The other half, an error written instead of returned, is not checked by anything.

## Constrain AI with Data Shape Contracts
**This one mitigates. It does not eliminate, and it is the only entry here that does not.** Instead of "write a notification system," say: write a function taking `{channel, recipient, message}` and returning `{status}`. A defined input and output contract is verifiable by reading the signature and running one example, where a class with five methods requires tracing every call sequence. That lowers the cost of finding a fault; it makes no category of fault impossible. It is kept because it works, and marked because everything else in this document promises removal.

**Nothing enforces this, and nothing could.** It is guidance for phrasing a request to a model, which is why it is also the one entry that mitigates rather than removes.

## One Gherkin Per Function
A missing test, a test that asserts nothing, and a test whose subject no longer exists are all invisible one at a time. Nothing about a suite that passes distinguishes a function nobody covered from one covered well.

Every function carries exactly one gherkin scenario naming it. The rule is a bijection, and the point of a bijection is that the two sets reconcile mechanically: a function with no scenario is code nothing describes, and a scenario with no function describes code that does not exist. The counts having to match is what makes all three obvious. Step-definition length is the secondary signal: thirty lines of setup means the code under test has hidden dependencies, and when the function is pure the step is call it and check the result.

**Enforced by** `feature-gate.sh`, which reconciles the function names in a module against the scenario subjects in its features and fails on any difference in either direction. honest-check catalogues HC-P009 for the same rule and does not emit it.

## Declarative Equivalents Over Framework Lifecycle Hooks
Lifecycle hooks are an initialisation order you cannot see. `componentDidMount`, `useEffect` cleanup and `ngOnInit` each run at a moment the framework picks, so the sequence lives in the framework's documentation instead of your file, and two hooks that must happen in an order have no way to say so.

Instead of `componentDidMount`, `useEffect` cleanup, `ngOnInit`, use HTMX attributes that declare when to load (`hx-trigger="load"`), or server-rendered HTML that arrives ready. No client-side initialization sequence.

**Enforced by** honest-check HC-P011, statically, at the gate.

## Strangler Pattern for Migration
A rewrite defers every fault to a single cutover. The first evidence that the design is wrong arrives with all of it at once, at the moment there is nothing left to fall back to.

Extract one pure function from one class method at a time. The method now calls the function, the class still exists, and the interface does not change. After six months the class is a thin shell and removing it is a cleanup. One function at a time means a fault surfaces at the step that caused it, and the blast radius of any step is that step.

**Nothing enforces this, and nothing could.** It is the order you do the work in, not a property of the code once done.
<!-- END VENDORED -->

## How to apply it

**Writing new code:** follow the rules from the start. No class for data, no if/elif dispatch, I/O at the boundary.

**Reviewing or refactoring:** run `honest-check` first, then read for the rules it cannot decide. Report in this order:

1. What the linter flagged, by rule ID
2. What you found that it cannot see: [[Declarative Equivalents Over Framework Lifecycle Hooks]] always, [[DOM as State (DATAOS)]] and [[HTML Attributes Over Imperative DOM Manipulation]] partly, and any case where the code passes the letter and breaks the intent
3. What you did not check, and why

Fix what you can. Where a violation cannot be fixed without breaking an external API, say so and leave it.

## What this skill does not do

It does not add abstraction that nothing needs. It does not refactor code that already complies. It does not apply a rule where a framework forbids the alternative, and Django models and React components are the usual cases. It does not flag ordinary conditional logic as a dispatch violation.

And it does not claim the linter's verdict as its own. `honest-check` decides what it decides; this skill reports the rest and names what neither of them looked at.

## How to write it

Follow the `writing` skill. It governs every reply and every document here, and this file does not restate it, because a rule stated in five places becomes five rules that drift apart.
