# CeeSafe language findings from the ClayWind port

Collected while porting ClayWind (Clay layout, a ThorVG-equivalent rasterizer, TrueType fonts, controls, BMP/PNG
decoding, three hosts) to pure CeeSafe, 2026-11-03, with ceesafec 0.10.1–0.10.3. Per-phase detail is in
`ClayWind-PORT-PLAN.md` §9–§16. Ranked by how much code each one bent.

## A. Worth raising upstream

### A1. `dyn` and generics do not compose (highest cost)
- A `dyn I` value does not satisfy a generic bound `T: I`.
- A type with region parameters, or one that holds a loan, cannot be `dyn` (N0268). The font engine borrows its pool,
  so it cannot be `dyn TextMetrics`.
- **Suspected bug:** a `borrow mut T` parameter passed to a `borrow mut dyn I` parameter is *moved*, not reborrowed
  (N0250 on the second use), although §13.3 says every use of a `borrow mut` reborrows.
- Cost in the port: `endLayout`, `endFrame`, `renderInto`, `textInputEx` became generic free functions; the
  controls test wraps its platform in a struct (`Rig`) to lend a field; `ScriptPlatform` copies its 4 KB script.

### A2. Methods cannot declare type parameters; no inherent `impl S {}` blocks
- The public API is lopsided: `Controls.button(...)` is a method, `textInputEx(...)` a free function only because it
  is generic over the metrics.

### A3. Arrays and slices cannot hold references
- `Slice<StringView>` and `[StringView; N]` are rejected ("array and slice elements cannot be references in v0").
- Cost: the controls take item lists as one `"Low|Medium|High"` view (a public-API wart). With no multi-line string
  literals, the browser page is written as 30 calls.

### A4. Suspected bugs and misleading diagnostics
- A float literal in a nested `if` expression defaults to `f64` even when the result is annotated `f32`.
- `var k = len;` with `len: borrow mut usize` reports N0246 "a reference variable must be declared with 'let'". The
  intent is a copy of a `Copy` value; it should copy, or the message should say how (`var k: usize = len + 0` works).
- A call through `dyn` is "may sleep" unless the interface method is `@effects()`, so async code rejects
  `ui.begin(platform)`. The fix is right; the diagnostic does not point to it.

## B. Ergonomics (frequent, small)
- `for (i in 0..16)` is `i32` even when `i` is only used as an index (many `0usize..16`).
- Missing: `min`/`max`/`abs` on `i32`/`u32`; `TextWriter.unsigned`; struct constants; `const` `StringView`; constant
  arrays of floats (stored as bit patterns).
- Blocks are not values in `match` arms or `if` expressions.
- `void` cannot be a type argument.
- Tests cannot live in a freestanding package; test files see the package's items, so helper names clash.
- The interpreter is slow: the suite takes about 18 minutes interpreted, seconds compiled.

## C. By design (leave alone)
No shadowing, no `is`, shifts only on unsigned values, `Vector` hosted-only, `box` reserved, `Console` blocking
(`AsyncConsole` in async code).

## D. Port refactors that follow upstream fixes
- A1 fixed: `endLayout`/`endFrame`/`renderInto`/`textInputEx` back to methods; drop `Rig` and the script copy.
- A3 fixed: `'|'`-separated item lists become real arrays (public API; do it before the API settles).
- A2 fixed: `textInputEx` moves into `Controls`.

## E. Status in ~/dev/CeeSafe (2026-11-03, uncommitted working tree)

Every item was reproduced against `out/ceesafec` 0.10.3 (repros in the session scratchpad, `repro/`).

| Item | Status | Where |
|---|---|---|
| A1 `borrow mut` moved into `dyn` (bug) | **Fixed.** A `borrow mut` local or field is reborrowed, then coerced. The field case was N0251 before. | `src/check/expr.cee` `coerce`; ADR 0063 §2.3; corpus `run-pass/dyn-reborrow`, `check-fail/dyn-reborrow` |
| A1 `dyn I` as a `T: I` bound | **Proposed**, not implemented | ADR 0064 §3.1 |
| A1 loans in `dyn` (OD-10a) | **Proposed**, an existing open decision | ADR 0064 §3.2 |
| A2 generic methods, inherent `impl` | **Proposed** | ADR 0064 §1 |
| A3 arrays and slices of views | **Proposed**, following the Vector rule of §25.4 | ADR 0064 §2 |
| A4 `f32` literal in a nested `if` | **Not reproduced** in isolation; dropped | — |
| A4 `var k = len` (N0246) | **Improved.** The message says how to copy, and `ceesafec fix` inserts `: T`. | `src/check/body.cee`; ADR 0063 §2.4 |
| A4 `dyn` "may sleep" explanation | **Improved.** It names the interface method and the `@effects()` fix. | `src/nir/effect_check.cee` `explainOp`; ADR 0063 §2.4 |
| B `0..16` used as an index | **Changed rule.** A range of literals is `usize` when the body indexes with its variable. | `src/check/range_index.cee`; spec §16.4; ADR 0063 §2.1; corpus `for-range-index` (run-pass and check-fail) |
| B `min`/`max` on integers | **Added** (built-ins; interpreter, C backend, `rt.h`) | ADR 0063 §2.2; corpus `run-pass/int-min-max` |
| B `abs` on integers | **Open** (it overflows at MIN) | ADR 0063 §5, question 2 |
| B `TextWriter.unsigned` | **Already exists** as `TextWriter.decimal(u64)`; my miss | — |
| B constants: structs, views, float arrays | Partly covered by ADR 0064 §2 (constant tables of views) | — |
| B blocks as values, `void` type argument | **Left alone** (§15 G5 by design) | ADR 0064 §4 |
| B interpreter speed | **Noted** for a benchmark item | ADR 0064 §4 |

**Verification:**
- Full corpus: 580 tests pass, 0 failures.
- New tests: they fail on 0.10.3 and pass with the change, compiled and interpreted.
- Fixed point: the changed compiler rebuilds itself to byte-identical C.
- Downstream: ClayWind (72 tests) and CosmoStack check.
- Contract suite: result in ROADMAP §10 once it finishes.

## F. Accepted and implemented (2026-11-04, uncommitted in ~/dev/CeeSafe)

The owner accepted ADR 0063 and ADR 0064 ("Both"), with `abs` as "Both". Everything proposed is implemented:

| Item | Now |
|---|---|
| A1 `dyn I` as a `T: I` bound | `dyn I` implements `I`, behind references only (by value: N0222 or N0330) |
| A1 loans in `dyn` (OD-10a) | a type with region parameters coerces to `borrow dyn I`; not to `Box<dyn I>` |
| A2 generic methods, inherent `impl` | `fn m<T>(…)` in structs, `x.m<T>(…)`, `impl S { … }` and `impl<T> S<T> { … }` |
| A3 arrays and slices of views | `Slice<StringView>`, `[StringView; N]`, `const LEVELS: [StringView; 3]` |
| B `abs` | `abs()` panics at the minimum; `unsignedAbs()` never panics |

Every soundness attack tried was rejected (ADR 0064 §5.2–§5.4). Full corpus: 596 tests, 0 failures. The fixed point
and the contract suite pass.

**§D refactors in ClayWind:** possible now, but the code would then need this unreleased compiler
(`~/dev/CeeSafe/out/ceesafec`), not the installed 0.10.3. They wait for a release, or for an explicit go-ahead.
