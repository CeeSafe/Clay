# ClayWind → CeeSafe: Port Plan

**Source:** `~/dev/ClayWind` (C11, ~12k lines). **Target:** a CeeSafe package under `~/dev/CeeSafeApps/Clay/claywind`.

**The rule: 100% CeeSafe.**
- Every line we write is `.cee`.
- No `.c`, `.h`, `.m` or C++ files, no `c = [...]` list in any manifest, and no `extern "C"` blocks in our code.
- We use only what CeeSafe's own `lib/core` and `lib/std` provide. Their internal runtime is part of the language,
  not a dependency.
- No Clay, ThorVG, SDL3, stb or any other foreign code, vendored or linked.
- CI enforces this: a check fails the build if any non-`.cee` source or any `extern "C"` appears under `src/`.

Toolchain checked: `ceesafec 0.10.1`. Docs: <https://ceesafe.github.io/CeeSafe/>.

---

## 1. What ClayWind is today

| Layer | Files | Lines | Depends on |
|---|---|---|---|
| Layout engine (Clay 0.14, **heavily forked**: margins, wrap both axes, basis/shrink, relayout passes, transforms, effects commands) | `clay.h` | 6150 | libc |
| Tailwind-style API (`Box/Row/Column/Label`, `ComponentOptions`, string specs `"grow-0"`, `"a-md"`, palette, variants, breakpoints, `F()` + arena) | `renderer.h` | 1568 | clay.h |
| Transition engine (duration/ease per element id) | `claywind_transition.h` | 195 | clay.h |
| Controls (button, checkbox, text input + caret, spin, slider, radio, tabs, dropdown, listbox/multi, context menu, tooltip, 11 vector icons, Tab focus) | `controls.h` | 402 | renderer.h |
| Seams: backend vtable (20 hooks) + platform vtable (13 hooks) | `claywind_backend.h`, `claywind_platform.h` | 207 | clay.h |
| **ThorVG backend**: vector raster, TTF text, scenes for clip/transform/blend/opacity/blur | `backends/thorvg_backend.c` | 619 | **ThorVG** |
| **SDL3 host**: window, loop, input, present | `backends/sdl_backend.h` | 302 | **SDL3** |
| Framebuffer skeleton (rect/border/scissor/gradient/ring) | `backends/framebuffer_backend.c` | 172 | none |
| Demo dashboard (4 tabs incl. Controls, Effects) | `main.c` | 562 | all |
| Tests: layout geometry (~38 cases), platform/controls, ThorVG pixel tests | `tests/` | 1421 | — |

The external dependencies are **ThorVG** (rasterizer + font engine) and **SDL3** (window/input). Clay is vendored, but
it is C, so it also has to be rewritten. The core (renderer/controls/transitions) is already free of both
dependencies, which makes the port tractable.

## 2. CeeSafe constraints that shape the design

| Constraint | Effect on the port |
|---|---|
| No preprocessor/macros | `Box(...) { }` blocks, `CLAY_STRING`, and `Label(...)` sugar all have to be redesigned (§4). |
| No struct defaults or partial init | `(ComponentOptions){.p = 16}` won't work. Use a **builder**: `Style.box().p(16).bg(SLATE_900)`. |
| A method cannot share a field's name | Builder methods (`p`, `bg`, `w`) need private field names that differ (`padding`, `background`, `width`). |
| A function in a struct field cannot be called | The vtables become **interfaces**: `interface Backend`, `interface Platform`, used as `borrow mut dyn Backend`. |
| Closures cannot be stored or outlive their block | Child builders can take `(ui) => {…}` closures for nesting, but nothing may keep them. |
| **No trigonometry or logarithms** | Write `sin/cos/atan2/exp/pow` approximations in CeeSafe (`math.cee`). We have `sqrt/floor/ceil/abs/min/max`. They are needed for rotation, gradient angles, arcs, easing and blur kernels. |
| Overflow traps; `as` is lossless only | Pixel math uses explicit `truncate<u8>`, saturating helpers and `wrappingAdd` where wrapping is intended. |
| Indexes are `usize`; no tuples, no type aliases, no `~`, no array `==` | Mechanical, but it affects every hot loop. |
| `StringView` in structs needs a region parameter | Element ids and text in render commands go into a per-frame string arena and are referenced by index/handle, not `StringView` fields. |
| Hosted std: `File`, `Console.read`, `Timer`, `Clock`, `Environment`, `Vector`, `HashMap`, `HostServices.capture` (run a process), `AsyncTcpListener` | Enough for headless, terminal and browser hosts. There is no window API, and opening a native window would need `extern "C"` into OS libraries, which the rule forbids. |
| Freestanding profile (`@export` entry, no std) | A CosmoOS framebuffer target works if the core avoids `lib/std` (use `lib/core` + a caller-provided `Allocator`). |

**Rule for the core:** depend on `lib/core` only, with per-frame storage carved from a caller-owned `FixedBufferAllocator` (see §9). Then the same
code builds hosted and freestanding (CosmoOS), which is what ClayWind was built for.

## 3. Package layout

```
CeeSafeApps/Clay/claywind/                 kind = "library"
  src/
    math.cee        sin/cos/atan2/exp/pow/lerp/clamp (no-trig workaround)
    color.cee       Color (f32 RGBA), WITH_ALPHA→withAlpha, THEME, full Tailwind palette consts
    geom.cee        Vec2, Dims, Rect, Corners, Sides, Affine2
    arena.cee       per-frame byte arena + string interning (replaces Arena/F())
    collections.cee FixedList<region r, T: Copy> over caller-provided slices (done in Phase 0), IdMap later;
                    `Vector` is hosted-only (N0293), so the core never uses it
    format.cee      F()-replacement: TextWriter into the frame arena
    layout/
      element.cee   element tree in Vector<Element> (indices, not pointers)
      sizing.cee    fit/grow/fixed/percent, min/max, basis/shrink, aspect
      flex.cee      direction, gap, justify, align, reverse, wrap (both axes), align-content, margins
      relayout.cee  height-dependent width passes (snapshot/restore, ≤3 passes)
      text.cee      wrap words/newlines, line-clamp + ellipsis, tracking, leading
      float.cee     absolute/fixed/z, attach points, clip escape
      scroll.cee    clip/scroll containers, scroll offsets, momentum
      pointer.cee   hit-testing, hover/pressed per id, Clay_PointerOver equivalents
      commands.cee  enum RenderCommand { Rect, Border, Text, Image, ClipStart/End, Transform…, Shadow,
                    Gradient, Ring, Icon, Blend…, Opacity…, Filter… }
    style.cee       Style builder (ComponentOptions), TextStyle builder, typed enums replacing string specs
    ui.cee          Ui context: open/close, box/row/column/label, variants (hover/active/focus/disabled/group)
    transition.cee  per-id eased style interpolation
    controls.cee    all controls + icons + focus ring/Tab cycling
    backend.cee     interface Backend + render(commands, backend)
    platform.cee    interface Platform, Key/MouseButton/Cursor enums, NullPlatform
    raster/
      canvas.cee    RGBA8 premultiplied surface, layer stack
      path.cee      move/line/quad/cubic, flatten, transform
      fill.cee      AA scanline coverage rasterizer (nonzero/even-odd), sparse accumulation buffer
      shapes.cee    rounded rect (per-corner), border (per-side), ring, shadow, icons
      paint.cee     solid, linear/radial gradients with stops
      blend.cee     all CSS blend modes incl. hue/saturation/color/luminosity, plus-lighter/darker
      effects.cee   group opacity, blur (3× box ≈ Gaussian), grayscale, brightness
      clip.cee      rect + rounded clip as coverage mask
      backend.cee   SoftwareBackend implements Backend
    font/
      ttf.cee       TrueType parser: head/hhea/maxp/cmap(4,12)/loca/glyf/hmtx/kern(+GPOS pairs, later)
      raster.cee    glyph outline → coverage via raster/fill
      cache.cee     glyph atlas keyed (font, glyph, size); measure + baseline
    image/
      bmp.cee, ppm.cee   loaders/writers (no deps)
      png.cee       inflate + PNG decode/encode (pure CeeSafe; phase 6)
  tests/            ports of layout_test, platform_test, raster golden tests
CeeSafeApps/Clay/claywind-hosts/
  headless/   renders N frames to BMP/PPM (CI + screenshots; replaces CLAYWIND_SCREENSHOT)
  terminal/   interactive host in a truecolor terminal (see §5)
  browser/    CeeSafe HTTP/WebSocket server + embedded canvas page (see §5)
  cosmoos/    freestanding: @export entry points over a GOP framebuffer + HID input
CeeSafeApps/Clay/claywind-demo/   port of main.c (dashboard, controls, effects tabs)
```

## 4. API redesign (C macros → CeeSafe)

C today:

```c
Column(.p = 16, .gap = 12, .bg = SLATE_900, .w = "grow-0", .h = "grow-0") {
    Row(.id = "btn", .px = 14, .py = 10, .bg = BLUE_600, .borderRadius = "a-md",
        .hover = &(ComponentOptions){.bg = BLUE_500}) {
        Label("Hello", .fontId = TEXT_LG, .color = CREAM);
    }
}
```

Proposed CeeSafe. Final syntax will be settled in the Phase 0 spike with `ceesafec check`:

```ceesafe
ui.column(Style.of().p(16).gap(12).bg(SLATE_900).w(Size.grow()).h(Size.grow()), (ui) => {
    ui.row(Style.id("btn").px(14).py(10).bg(BLUE_600).rounded(Radius.Md)
              .hover(Style.of().bg(BLUE_500)), (ui) => {
        ui.label("Hello", Text.of().size(TextSize.Lg).color(CREAM));
    });
});
```

- **Typed specs replace strings**, so the compiler catches mistakes that `"grow-0"`/`"a-md"`/`"sb"` parsing currently
  catches at runtime (or doesn't): `Size.fit()/grow()/fixed(px)/percent(p)`, `Radius.Md`, `.roundedT(Radius.Lg)`,
  `Justify.Between`, `Align.CenterCenter`, `Blend.Screen`, `Position.Absolute`.
- **Two nesting forms.** The closure form above, plus explicit `ui.open(style); …; ui.close();` as a fallback when a
  closure would fight the borrow checker (for example, a body that mutates app state that the closure also needs). The
  spike decides which one is primary.
- **Variants** (`hover/active/focus/disabled/groupHover`) are `Option<Box<Style>>` fields, or a small fixed overlay
  array on the frame arena. Overlay semantics stay as they are now.
- **Controls keep the caller-owned-state model**, which maps naturally to borrows:
  `ui.textInput("name", mut name, mut nameLen)`, `ui.checkbox("sub", "Subscribe", mut sub)`.
- **Globals** (`ClayWind_darkMode`, `ClayWind_activeId`, focus list, backend/platform pointers) move into the `Ui`
  context struct. No mutable globals.

## 5. Replacing the two dependencies

### 5.1 ThorVG → `raster/` + `font/` (pure CeeSafe)
- **Rasterizer:** analytic-coverage scanline fill (the font-rs/stb_truetype accumulation approach). It handles
  paths, rounded rects, arcs (from our own `sin/cos`) and glyphs. Shapes are flattened to lines with an error
  tolerance, and transforms are applied to the path before filling.
- **Scenes → layer stack:** `Opacity/Blend/Filter/ClipStart` push an offscreen RGBA layer the size of the bounding
  box. `…End` composites it down with the mode. This is what ThorVG's Scene stack does now.
- **Effects:** blur = three box blurs (separable, O(n) per pixel), with a Gaussian fallback for small radii. Shadow =
  blurred, offset alpha mask. Grayscale/brightness are per-pixel.
- **Text:** a TTF parser plus outline rasterization through the same filler, and a glyph cache. Fonts are read with
  `File` from a path, as now (`/System/Library/Fonts/Supplemental/Arial.ttf`), or embedded as a byte array
  constant for freestanding builds. Measurement uses the same metrics as drawing, which fixes the measure/draw
  mismatch risk noted in `framebuffer_backend.c`. Size semantics stay CSS em, as in ThorVG.
- **Scope cut:** no hinting, no CFF/OTF outlines (TrueType `glyf` only), and no complex shaping (Latin-first, the
  same as the current demo).

### 5.2 SDL3 → hosts (all pure CeeSafe)
A native desktop window can't be opened without calling C (Cocoa, X11 or Win32 through `extern "C"`), so it is **out
of scope**. Every host below uses only `lib/std` (or `lib/core`), recommended order first:

1. **Headless:** render frames to BMP/PPM with `File`. This is the CI and golden-test host, and it replaces
   `CLAYWIND_SCREENSHOT`. Build it first.
2. **Terminal** (interactive, primary dev host):
   - Output: write truecolor ANSI escapes with `Console`. Use half-block `▀` cells (2 pixels per cell), or the
     kitty/iTerm2 image protocols, which carry base64 pixel data written in CeeSafe, when the terminal has them.
   - Input: decode escape sequences read from stdin (keys, SGR-1006 mouse for pointer, buttons and wheel), and read
     the terminal size from the `\e[18t` reply.
   - Raw mode without C: run `stty raw -echo` on `/dev/tty` through `HostServices.capture`, and restore it on exit
     (in a `drop`). This is an OS tool, not linked code. Verify it in the Phase 0 spike on macOS (`stty -f`) and
     Linux (`stty -F`).
3. **Browser** (approved; full-resolution pixels and a real mouse):
   - A tiny HTTP + WebSocket server written in CeeSafe on `AsyncTcpListener`.
   - It streams frames to a `<canvas>` and receives input events back.
   - It needs a ~50-line embedded JavaScript page as the display client (approved, §8).
4. **CosmoOS** (freestanding):
   - The core builds with `--profile freestanding`; ClayWind's code exposes `@export` entry points such as
     `claywind_frame(fb, pitch, w, h, input)`.
   - The kernel calls in, and we write no C. The core must stay on `lib/core`.

## 6. Phases

| # | Phase | Deliverable | Exit criterion |
|---|---|---|---|
| 0 | **Spike** ✅ done 2026-11-03 (§9) | 200-line prototype: `Ui` with `open/close` + closure nesting, `Style` builder, `dyn Backend`, `dyn Platform`; terminal raw mode via `stty` + escape-sequence input loop | `ceesafec check` clean; borrow-checker friction understood; API form chosen; raw-mode input works on macOS and Linux |
| 1 | Foundations ✅ done 2026-11-03 (§10) | `math`, `color` (+palette), `geom`, `arena`, `collections`, `format` (over core `TextWriter`) | unit tests for `sin/cos/atan2` error < 1e-5 |
| 2 | **Layout engine** ✅ done 2026-11-03 (§11) | Port the Clay core + every fork feature in `PARITY.md` | All ~38 `tests/layout_test.c` cases ported and passing with identical geometry |
| 3 | Style/UI/transitions ✅ done 2026-11-03 (§12) | `style`, `ui`, `transition`, variants, breakpoints, container queries, scroll helpers | `platform_test.c` ported (NullPlatform) |
| 4 | Software renderer ✅ done 2026-11-03 (§13) | `raster/*` + SoftwareBackend (no text yet) | Golden BMPs for rect/border/radius/gradient/ring/shadow/blend/opacity/blur vs. ThorVG output from the C build (per-pixel tolerance) |
| 5 | Fonts ✅ done 2026-11-03 (§14) | `font/*`, measure + baseline wired into layout | Text goldens; layout text widths match the ThorVG build within 1px |
| 6 | Controls + images ✅ done 2026-11-03 (§15) | `controls`, icons, focus cycling; BMP (+PNG) images | Controls behaviour tests (scripted input through a FakePlatform) |
| 7 | Hosts + demo ✅ done 2026-11-03 (§16) | headless + terminal + browser hosts; `claywind-demo` port of `main.c` | Demo screenshots match the C build's `CLAYWIND_SCREENSHOT` for each tab |
| 8 | CosmoOS | freestanding build (`--profile freestanding`, `--emit obj`) | Object links into CosmoOS; demo frame on the QEMU GOP |
| 9 | Optional | perf pass (`ceesafe_emit_c` bounds-check report, dirty rects, only changed cells re-emitted to the terminal) | 60 fps at 1024×640 on the software path |

**Verification oracle:** keep the C build of ClayWind working on the side and use it as the reference. Generate
golden geometry dumps (render command lists) and pixel dumps from it, then diff the CeeSafe port against them at every
phase.

## 7. Risks

- **Layout fork complexity.** `clay.h` is 6k lines of macro- and arena-heavy C with subtle multi-pass logic. Mitigation:
  port by test case, not line by line. Use an index-based element store instead of Clay's pointer arenas.
- **Borrow checker vs. immediate-mode UI.** Closures that capture app state while `Ui` is also borrowed mutably may
  not compile. The Phase 0 spike exists to settle this, with `open/close` as the fallback.
- **Performance of safe pixel loops.** Bounds and overflow checks sit in the hottest code. Mitigation: work on slices
  per row, check `ceesafe_emit_c` to confirm the checks are hoisted, and use small audited `unsafe` blocks only where
  measured.
- **Text quality** without hinting or LCD filtering will look softer than ThorVG. That is acceptable for v1.
- **Pre-1.0 language.** Track `ceesafec` releases and run `ceesafec check` + `fmt --check` in CI.
- **Terminal as the main interactive display.**
  - Resolution is limited: half-blocks give 2 pixels per cell, though the image protocols give full pixels.
  - Raw mode depends on `stty` being present.
  - Key-up events are not reported, so key repeat is the terminal's and there is no `keyDown` hold state.
    `Platform.keyDown` is approximated from recent presses.

## 8. Decisions (agreed 2026-11-03)

1. **Browser host: approved.** A small embedded JavaScript canvas page is an acceptable display client. It is the only
   non-CeeSafe file, and it is served as data by the CeeSafe server. Phase 7 builds it next to the terminal host, so it
   is no longer optional.
2. **Typed builder API: approved.** It replaces the C macro style (§4).
3. **Freestanding from day one: yes.**
   - The library package (`claywind/src`) depends on `lib/core` only and takes memory from a caller-owned `FixedBufferAllocator` (§9) rather than an `Allocator`
     parameter.
   - CI runs `ceesafec check --profile freestanding` on it.
   - `lib/std` is used only in `claywind-hosts/*` and `claywind-demo`.

## 9. Phase 0 results (2026-11-03)

**Built:** `claywind/` is a freestanding library of 6 files and about 900 lines, covering style, layout, `Ui`,
backend, platform and fixed collections. `claywind-hosts/terminal/` is an executable of 3 files and about 600 lines,
with the cell-grid backend, raw-mode input and the demo. Everything is CeeSafe: 0 C files and 0 `extern "C"`.
`ceesafec check` (freestanding for the library), `fmt --check` and `build` are all clean.

**Verified:**
- `CLAYWIND_ONCE=1` renders the expected 80×24 layout: padding, gap, justify-between, align-center, grow and
  percent widths.
- A scripted pseudo-terminal run (`script -q /dev/null`, with SGR mouse and arrow-key bytes piped in, and
  `CLAYWIND_DUMP` saving the final frame) showed every piece working:
  - raw mode through `stty`, with no echoed input bytes;
  - hover, press and release making a click (2 of 2);
  - a tab switch;
  - key decoding;
  - truecolor output with hover and selected colors;
  - the alternate screen and mouse reporting turned off again on exit.

**Language findings that change the plan:**

| Finding | Consequence |
|---|---|
| No struct constants (N0216) | The palette is packed `0xRRGGBBAA` `u32` constants. Builders take `u32` (`.bg(SLATE_900)` still reads the same), and `Color.hex()` unpacks. |
| No `is` operator | Small `match` helpers (`isRow`, `isGrow`). |
| `Vector` is hosted-only, and its allocator argument may only be `SystemHeap`/`FailingAllocator` (N0263/N0293) | The core uses `FixedList<region r, T>` over slices from a caller-owned `FixedBufferAllocator`, the same model as Clay's fixed arena. `Ui<region r>` borrows that memory, and running out of room is reported once by `end()`. **This replaces the `Allocator`-parameter idea in §2.** |
| Methods cannot declare their own type parameters | Text measurement is `borrow dyn TextMeasure`, passed to `end()`. Performance-critical generics become top-level generic functions. |
| `StringView` fields need region parameters | Ids are hashed into `u32` when the style is built. Text goes into the frame's byte buffer and is referenced by offset. Application state stores codes, not views. |
| **The closure form works** | Closures that capture app state mutably while `Ui` is passed in as a parameter pass the borrow checker. `ui.nest(style, (child) => { … })` becomes the primary form, and `open()`/`close()` stays for loops and conditionals. Closure parameters need distinct names, since there is no shadowing. |
| `box` cannot be used as a binding name | Renamed (`area`, `nest`). |
| `Process.run("stty", …)` passes our stdin through; `Process.capture` does not | Raw mode uses `run`. The size query uses `capture` with `-f`/`-F /dev/tty`. |

**Carried forward:**
- The spike layout is a single-pass simplification. Phase 2 replaces it with the full Clay port: min/max, wrap,
  margins, floating, scroll, text wrapping, relayout.
- The terminal reads stdin with a blocking read, so frames are driven by input. Transitions and caret blink need a
  timed read, through `Async` file reads with a timeout, in Phase 7.
- Non-ASCII text shows as `?` until cells store code points.

## 10. Phase 1 results (2026-11-03)

**Built, in `claywind/src`:**
- `math.cee`: sin/cos/tan/atan/atan2/exp/ln/log2/pow in f64 (`Math64`) with an f32 API (`Math`), plus radians,
  hypot, clamp, lerp, smoothstep and round.
- `CubicBezier`: CSS easing, with Tailwind's `ease-linear/in/out/in-out`.
- `color.cee`: `Color`, the full palette generated from `renderer.h` (250 colors, plus WHITE/BLACK/TRANSPARENT),
  `withAlpha` and `theme`.
- `geom.cee`: `Corners` with CSS radius fitting, `Rects` (intersect/union/inset), and `Affine2` (translate, scale,
  rotate, skew, about-pivot, compose, inverse, bounds).
- `format.cee`: `Format.fixed` and `Format.padded` over core's `TextWriter`, replacing `F()`.

**Tests:** a new hosted package, `claywind-tests/`, because a freestanding package can't use `lib/std`'s `Check`.
- 19 tests pass, both natively and with `ceesafec test --interp`.
- The math is checked against an independent libm: reference tables generated from Python's `math`, ~250 cases.
  The library passes at 1e-12 (sin/cos), 1e-10 (atan/atan2), 1e-13 (exp/ln) and 1e-11 (pow). The CSS easing curves
  are within 1e-5 of a bisection reference.
- One real bug was caught: the first sine series (to x^15) was off by 6e-12 at pi/2, and was extended to x^21.

**Language findings:**
- Constant arrays hold only integers or bools, so float tables are stored as `u64` bit patterns and read with
  `f64.fromBits`. This matters for blur kernels and font tables later.
- `void` can't be a type argument, so `CheckResult<void, E>` doesn't work. Tests match on the result instead.
- `i64 as f64` is rejected as lossy; use `round<f64>(…)`. `f64 → f32` is `round<f32>(…)`.
- Tests can't live in the freestanding package: `claywind-tests` covers the public API. Internal helpers get tested
  through it, or move behind `public`.

## 11. Phase 2 results (2026-11-03)

**Built:** the full ClayWind-fork layout engine, ported from `clay.h`, in 5 files and about 2,300 lines.
- `layout_decl.cee`: `Decl`, `LayoutConfig` and `TextConfig` with every fork field.
- `layout_engine.cee`: `LayoutTree<region r>` with open/close/text/end, word measurement, intrinsic sizes, and
  previous-frame boxes for @container queries.
- `layout_size.cee`: axis sizing, flex-wrap lines, CSS grow/shrink, and Clay's largest-first compression.
- `layout_pass.cee`: text wrap with line-clamp, aspect ratio, height propagation, and the relayout
  snapshot/pin/restore passes.
- `layout_place.cee`: positioning, justify/align/baseline, wrapped-line placement, floating attach points, culling,
  and all render commands in Clay's order.

It stays freestanding: no `Vector`, and all storage is carved from a caller's `FixedBufferAllocator`.

Text is measured in `end()` through `dyn TextMetrics`. FIT sizes are then computed in reverse declaration order,
which equals Clay's close order, so the frame never has to hold a `dyn` reference.

**Verification:**
1. **The C suite, ported:** all geometry and render-command cases of `tests/layout_test.c` (31 tests) pass, with the
   same trees, expected values and 0.5 px tolerance. A planted wrong value is caught, so the harness can fail.
   Transitions and the framebuffer gradient test move to Phases 3 and 4.
2. **Differential fuzzing against the original C:**
   - **Tooling:** a C oracle builds random specs with the unmodified `clay.h`, and the CeeSafe driver
     (`claywind-tests` main) builds the same specs with the port. Every named box and every render command (type,
     box and text) is compared.
   - **Result:** 4,800 random specs are identical, plus a 1,502-element dashboard tree.
   - **Coverage per 300 specs:** every feature appears in 130 to 250 of them; about 3,300 boxes and 7,000 commands
     are compared, and 170 specs wrap text onto several lines.
   - **The one divergence it found:** Clay halves `childGap` and divider widths in `uint16_t` (integer division),
     and the port now floors to match.
   - **Where it lives:** the oracle is C test tooling and stays outside the port, in `~/dev/ClayWind/tests/`
     (`diff_oracle.c` and `diff_fuzz.py`; usage is in their headers).
3. **Performance:** 1,502 elements lay out in about 0.67 ms per frame (`CLAYWIND_BENCH=200`, compiled, including
   spec parsing).

**Not ported, intentionally:**
- Clay's built-in transition system: ClayWind uses its own, which comes in Phase 3.
- The debug view: F2, later.
- Overlay color: ClayWind doesn't use it.
- `AttachTo.ElementWithId` resolves only elements declared earlier in the frame, as in Clay.

**Next (Phase 3):** rebuild `Style`/`Ui` on `LayoutTree`, which means:
- the Tailwind builder producing `Decl`, and state variants;
- pointer hit-testing in z-order, respecting clips;
- scroll containers with persistent offsets, wheel and momentum;
- the transition engine and breakpoints/theme;
- porting the transition tests;
- moving the terminal host onto the new `Command` stream.

## 12. Phase 3 results (2026-11-03)

**Built:**
- **`style.cee`** (renderer.h's ComponentOptions and ParseComponentOptions):
  - **Model:** `Style` is a builder over `Props`, where every option is optional and "unset" keeps the base. The
    overlay order and the presets match C: shadow sm/md/lg/xl, rounded xs…full, filter defaults, and gradient
    directions mapped to CSS angles with via/positions.
  - **Typed in place of strings:** `Size.grow()`, `Radius.Md`, `Justify.Between`, `Items.Center` (main/cross
    resolved against the direction, as C does for justify and baseline), `ScrollAxis`, `absolute()/fixed()` with
    `right/bottom/inset/z`, and `gapX/gapY` by direction.
  - **Variants:** `hover/active/focus/disabled/groupHover` take a `Style`, and only its props are used.
  - **Text:** `Text` is TextOptions as a builder, with font presets and bold/mono faces at the same sizes as C.
- **`ui.cee`**:
  - **Variant resolution:** `Ui.open` resolves variants exactly as `RendererOpenElement` does: hover, then active
    (hovered and pressed), group, focus, then disabled (which wins and suppresses the rest), then transitions,
    scroll offset and cursor.
  - **Clicks:** press and release over the same element.
  - **Scrolling:** a port of `Clay_UpdateScrollContainers` (wheel ×10, drag, momentum, clamping), with
    `scrollBy/ToTop/ToBottom/Offset`.
  - **Also:** breakpoints, `theme()`/dark mode, and `containerWidth/Height` (@container).
- **`transition.cee`**: `claywind_transition.h`, ported case for case (quadratic easing, a shared clock,
  snap-on-first-sighting, delay, and LRU slots), with float color state.
- **Engine:**
  - `hitTest`, a port of `Clay_SetPointerState`: it runs on the previous frame's retained tree, roots in reverse
    z-order, respects clips, and stops at the first capturing floating root.
  - Per-element content size, `scrollExtent` and `idFor`.
- **`backend.cee`**: `Backend` is now one `draw(command, text)` over the `Command` stream.
- **Terminal host**:
  - **Migrated:** the Screen implements `Backend` (fills, text, borders, clips) and `TextMetrics`, and the demo
    uses the Tailwind API with hover/active variants, color transitions, a percent bar, wrapped text and a
    40-row scrolling log.
  - **Wheel:** scaled to 3 rows per notch, with Clay's sign convention.
  - **Frame time:** measured with `Timer`, for transitions.

**Verified:**
- **Tests:** 55 pass, compiled and with `--interp`. They include the C `test_transition` numbers case for case,
  the option mapping, hover/active/cursor/click over five frames, disabled and group variants, wheel/drag/clamp
  scrolling with culling, breakpoints/theme/@container, an eased hover through the `Ui`, and capacity overflow.
- **Differential fuzzing** now also compares hit-testing against Clay's `Clay_GetPointerOverIds`: 2,000 more specs,
  all identical, including 93 of 300 with hits under floating or clipped elements.
- **Terminal pseudo-terminal script:** both clicks registered, the tab switched, three wheel notches scrolled 9
  rows, and the hover text and key decoding worked.

**Language finding:** passing a `borrow mut T` *parameter* where `borrow mut dyn I` is expected moves the reference
(N0250) instead of reborrowing it. Taking the parameter as `borrow mut dyn I` in the first place works, and
reborrows on every use.

**Not done yet:**
- **Moves to the controls phase:** keyboard focus (Tab cycling) and the controls themselves.
- **Debug view (F2):** later.
- **Smooth transitions in the terminal:** the host only renders on input, so a transition advances only when
  events arrive. The timed-read host loop in Phase 7 fixes this.

## 13. Phase 4 results (2026-11-03)

**Built:** the ThorVG replacement, in pure, freestanding CeeSafe: `raster_core/fill/effects/backend.cee`, about 1,700
lines.
- **Coverage rasterizer:** analytic area accumulation (the font-rs method) with nonzero winding. Holes are reversed
  contours, and cubics are flattened adaptively in device space after the transform.
- **One premultiplied RGBA8 pool:** the frame is layer 0, and opacity, blend, filter and shadow layers nest on it.
  Layers are addressed by offset, never by aliasing slices.
- **Clips:** rectangles, or rasterized coverage masks for rounded or transformed clips, nested.
- **Paints** (solid, linear, radial, image) are evaluated in local space through the inverse transform.
- **Drawing matches `thorvg_backend.c`:**
  - borders: outer minus elliptical inner contour;
  - rings: centered round-join stroke outlines;
  - shadows: σ = blur/2;
  - gradients: the CSS gradient line, stops, spread;
  - icons: round-capped capsules;
  - images: bilinear, with tint and opacity;
  - transforms: T·R·S·Shear·T⁻¹.
- `renderInto/renderTree<B: Backend>`: a region-parameterized backend (the `Raster`) cannot be a `dyn` value
  (ADR 0054), so rendering is also offered by bound.

**Matched to ThorVG's actual algorithms,** read from ThorVG 1.1.2's MIT source rather than approximated:
- **Blur:** Kovesi's box approximation, two passes per axis at quality 60, integer, truncating, edge-extended,
  with σ² scaled by the transform. A true Gaussian visibly differs.
- **Blend modes:** ThorVG's u8 operators and its blended-scene composite. A blend composited directly into an
  effect scene is ignored, as in ThorVG.
- **Grayscale and image tint:** ThorVG's tint effect, with luma (54R + 182G + 19B) >> 8. The C backend passes
  intensity 100 (a percentage), which ThorVG stores as 254 out of 255. (Phase 4 used 100 out of 255; the Phase 7 demo
  comparison caught it, §16.)

**Verified:**
1. **The C pixel suite:** `tests/thorvg_test.c` is ported check for check (all but text, which comes in Phase 5),
   and passes.
2. **Differential rendering against real ThorVG:**
   - **Tooling:** `ClayWind/tests/diff_render.py`, plus `diff_oracle.c -DCLAYWIND_DIFF_RENDER`. Random layouts are
     drawn by ThorVG and by the port, then compared pixel by pixel.
   - **Pass criterion:** at most 0.5% of pixels off by more than 40.
   - **Result:** about 1,800 frames. 99% match, the worst at under 0.5% of pixels off, and every remaining frame is
     attributed to a known ThorVG bug (verified by removing its trigger). None are unexplained.
3. **Bugs the oracle found in the port, now fixed and regression-tested:**
   - Edge x was clamped before advancing to the first row: wrong slopes for rotated shapes crossing the top.
   - A degenerate ring hole inverted the winding.
   - An empty, fully clipped blur layer indexed -1. The bounds check stopped it, instead of silent corruption.
4. **Tests:** 60 pass, compiled and interpreted.

**ThorVG bugs deliberately not reproduced,** each documented in `diff_render.py`:
- **A.** A full-strength line where a border's outer and inner contours share a fractional edge (even-odd parity).
- **B.** Inside an effect, a multi-paint opacity group loses its opacity.
- **C.** Inside an effect, content in nested blend groups is dropped.
- **D.** Opacity plus blend over translucent content overflows the packed 8-bit math.

The C ClayWind shows these artifacts today; the port does not.

**Performance** (compiled, `-O2`, `CLAYWIND_RENDER_BENCH`):
- 1920×1080, 781 elements: 11 ms per frame.
- A 1024×640 dashboard with shadows, a ring and an opacity group: 23 ms per frame.
- A solid-paint fast path and pass-by-reference paints made plain fills 2× faster, and the big frame 3.7×.
- Still to do for 60 fps with effects (Phase 9): dirty-region compositing, layers sized to their content, and a
  cheaper blur.

**Language findings:**
- A struct with region parameters needs `impl<region r> I for S<r>` and cannot become `dyn`.
- `i32`/`u32` have no `min`/`max` methods, and shifts are unsigned only.
- `u32 → i32` needs `truncate`.
- A nested `if`-expression float literal defaults to `f64` despite an annotation.
- A function without reference parameters cannot return a slice.

## 14. Phase 5 results (2026-11-03)

**Built:**
- **`font.cee`** (about 650 lines): a port of ThorVG 1.1.2's sfnt/TTF reader, which draws ClayWind's text today.
  - **Tables:** found by binary search of the directory. `head`/`hhea` give unitsPerEm, ascent, descent and line
    gap; also `maxp`, and `hmtx` for advances.
  - **cmap:** format 12 (3/10, 0/4), then format 4 or 6 (3/1, 0/3), with ThorVG's segment search.
  - **Outlines:** `glyf`/`loca`, quadratic to cubic by the 2/3 rule with y flipped. Composite glyphs place their
    components by offset; scales are skipped, as in ThorVG.
  - **Kerning:** a format-0 `kern` table, with ThorVG's subtable stepping. Also a UTF-8 decoder.
- **Raster integration:**
  - `loadFont(id, bytes)` copies a face into the raster's font pool. A missing id falls back to font 0, as
    `cw_fontFor` does.
  - Text is drawn as `tvgb_text` draws it: one filled path per run, advances plus kerning, the ascender line at
    the box top, and letter spacing applied as ThorVG's spacing factor.
  - `impl TextMetrics for Raster` matches `ClayWind_Thorvg_MeasureText` (advances without kerning, plus spacing
    per glyph, half an em for an unmapped glyph) and `MeasureBaseline` (the scaled `hhea` ascent).
- **Generic metrics:** `endLayout<M>` and `endFrame<M>` replace the `end(dyn)` methods. A `dyn` value does not
  satisfy a bound, and the region-borrowing font engine cannot be `dyn`, so the engine is generic over
  `TextMetrics` throughout.

**Verified:**
1. **C text checks:** `thorvg_test.c`'s text section is ported, with Arial's cap height, baseline, advance, line
   height, ascent and letter spacing.
2. **Font unit tests:** against an independent Python parse of Arial. They cover unitsPerEm/ascent/descent, glyph
   ids and advances, the A–V kern of -152, composite Á drawing its accent, `.notdef` for unmapped code points,
   rejecting non-fonts, and UTF-8.
3. **Real-font layout fuzzing:** with `CLAYWIND_DIFF_FONT=<ttf>` the oracle measures with ThorVG and the port with
   its own engine. The results are identical: 400 specs with Arial, 100 with Arial Bold and 100 with Courier New.
4. **Text pixel fuzzing:** 445 of 450 frames match ThorVG, with the worst frame at 0.3% of pixels off. The other 5
   are known ThorVG bugs; none are unexplained. The first direct comparison gave a 19-level maximum channel
   difference on anti-aliased glyph edges.
5. **End to end:** a `Ui` laid out with `Raster` metrics gets the Arial-derived width (53.56 px for "Hello" at
   20 px with padding) and renders glyph ink.
6. **Tests:** 65 pass, compiled and interpreted.

**Performance:** a 1024×640 frame with 160 text runs (about 4,800 glyphs) rasterizes in about 16 ms. Glyphs are
decoded and filled every frame, as in ThorVG. A coverage cache keyed by sub-pixel offset is a Phase 9 option that
keeps the output identical.

**Language findings:**
- `const` cannot hold a `StringView`: use a function.
- Tests see the package's own items, so helper names must not clash.
- Borrows are tracked per field, so the font pool (read) and the path buffer (written) can be used in one function,
  provided the glyph is decoded into a local outline first.

## 15. Phase 6 results (2026-11-03)

**Built:**
- **`platform.cee`:** the full `Platform` seam from `claywind_platform.h`. It has the clock (`time`), `keyDown`,
  `keyPressed` and `keyRepeated` over a 31-key `Key` enum, a typed-character queue (`nextChar`), and the secondary
  button (`Pointer.secondaryDown` / `secondaryPressed`; `Pointer.at(position)` builds an idle pointer).
- **`ui.cee`:** per-frame input capture (key bitmasks and up to 64 typed characters), focus (`hasFocus`, `setFocus`,
  `clearFocus`), pointer capture (`capture` / `captured`), `pressedOn`, `secondaryPressedOn`, `pressedOutside` and
  `registerFocusable`. `endFrame` cycles focus with Tab and Shift-Tab, as `ClayWind_EndControls` does.
- **`controls.cee`:** every control in `controls.h`, with the same styles and colors: button, checkbox,
  textInput, `textInputEx` (caret, Left/Right/Home/End, insert, Backspace/Delete), dropdown (a floating list that
  closes on an outside click), listbox, listboxMulti, slider (with pointer capture), radio, tabs, contextMenu,
  tooltip and spinInput (−/+ buttons, and Up/Down while focused).
  - The state stays caller-owned, and sub-element ids are derived as in C (`"qty~inc"`, `"dd~2"`).
  - Item lists are one `'|'`-separated view (`"Small|Medium|Large"`, read with `itemCount` / `itemAt`), because a
    slice of `StringView`s is not allowed.
  - `textInputEx` is a generic free function over `TextMetrics`: it measures the text before the caret, and the
    Ui does not hold metrics between frames.
- **`image.cee`:** BMP and PNG decoding with no dependencies. `imageInfo` reports the size and scratch needed,
  `decodeImage` decodes into caller slices, and `loadImage` decodes straight into a Raster slot
  (`Raster.imagePixelsMut`).
  - **PNG:** a full RFC 1951 inflate (stored, fixed and dynamic blocks, read across IDAT chunk boundaries), all
    five filters, Adam7, and every color type and bit depth, with PLTE and tRNS.
  - **BMP:** 1/4/8-bit palettes, 16/24/32-bit, BI_BITFIELDS with alpha, top-down rows, and the OS/2 core header.
    RLE is reported as `Unsupported`.
- **Hosts:** the terminal `Platform` now queues typed characters, maps the `ESC [ Z` sequence to Shift-Tab, reports
  right-button presses, and keeps a clock.

**Verified:**
1. **`platform_test.c`, ported check for check** (`controls_test.cee`, scripted `FakePlatform`, 0.6 em fixed
   advance):
   - the cursor resets to default each frame and becomes a pointer on hover;
   - a button click is a one-frame event;
   - clicking a field focuses it, typing lands in the caller's buffer, insert and Backspace work at the caret, and
     Enter clears focus;
   - an empty field keeps its one-line height;
   - Tab and Shift-Tab cycle focus, and Up steps a focused spin input;
   - the slider captures the pointer while held and releases it on button-up;
   - the spin input's `+` button works.
   A second test drives tabs, checkbox, radio and dropdown (open, pick, close).
2. **Image fixtures:** `fixtures/make_images.py` writes 44 fixtures (31 PNG, 13 BMP) with expected pixels, and
   Pillow confirms the expected pixels for every case it decodes faithfully (it truncates 16-bit samples
   differently, so those are checked only against the source values). All 44 decode exactly.
3. **Robustness:** every prefix of three files, and every byte of eight files flipped three ways, gives an error or
   wrong pixels, never a panic. The fuzz found one real bug: an overflow scaling a wide BMP bit-field mask.
4. **Regression:** the layout fuzzer still matches 300 of 300 specs, and the render fuzzer leaves 0 unexplained
   frames (98 of 100 match; 2 are known ThorVG bugs).
5. **Tests:** 70 pass, compiled and interpreted. The interpreted run takes about 18 minutes, mostly in the byte-flip fuzz.

**Language findings:**
- `Slice<StringView>` is not allowed (slice elements cannot be references).
- A `borrow mut T` parameter handed to a `dyn` parameter is moved, so a helper that runs frames keeps the platform
  in a struct field (`Rig.p`) and lends the field each time.
- Ranges with literal bounds are `i32`, so indexing loops use `0usize..16`.
- A mutable sub-slice is returned with `borrow mut this.pool[a..b]`, and `let` (not `var`) binds a `SliceMut`.
- `i32` has no `abs`.

**Not done:** the terminal demo doesn't use the new controls (see §16).

## 16. Phase 7 results (2026-11-03)

**Built:**
- **`claywind-demo`** (a freestanding library): `main.c` ported line for line. It has the sidebar, the Dashboard,
  Controls (Inputs / Selection / Lists, with the live-state panel) and Effects pages, the rocking PRO badge, the
  tooltips and the context menu.
  - Hosts call `demoFrame(ui, app, metrics)` between `ui.begin` and `endFrame`.
  - `ScriptPlatform` is a deterministic platform: fixed 1/60 s frames, and a `FRAME:click|right|move|key|type:ARG`
    event script.
  - One deliberate difference: `T` toggles the theme only when no field has focus, so it can be typed.
- **Hosts** (all pure CeeSafe):
  - **`claywind-hosts/headless`:** screenshots (`CLAYWIND_SCREENSHOT` as `.bmp` or raw RGBA,
    `CLAYWIND_SCREENSHOT_TAB`, `CLAYWIND_SHOT_EVENTS`, `CLAYWIND_LIGHT`) and `CLAYWIND_BENCH`. It replaces
    `main.c`'s screenshot hook and saves the same frame (28).
  - **`claywind-hosts/browser`:** an HTTP + WebSocket server on `AsyncTcpListener`, with SHA-1, base64 and RFC 6455
    framing written in CeeSafe.
    - One async task per session waits for input with `Async.timeout` until the next 16 ms frame.
    - It renders, then sends only the rectangle that changed since the last frame.
    - The page has about 60 lines of JS: it paints rectangles with `putImageData` and sends pointer, wheel, keys
      and typed characters.
    - One session at a time; the app state survives reconnects.
  - **`claywind-hosts/terminal`:** unchanged (Phase 3/6).
- **`Platform`'s methods are now `@effects()`.** A `dyn Platform` call counts as "may block" otherwise, which async
  code (the browser host) rejects.

**Verified:**
1. **Demo vs the C build**, scene by scene:
   - **Setup:** `~/dev/ClayWind/tests/demo_shot.sh` builds `main.c` against a headless stand-in for
     `sdl_backend.h` (ThorVG into a buffer, the same script grammar and clock). `demo_compare.py` diffs 14 scenes.
   - **Scenes:** each tab in dark and light; hover; button clicks; typing with caret moves; Tab focus, the spin
     input, slider and tooltip; checkbox and theme radio; dropdown open and pick; list single- and multi-select; the
     context menu.
   - **Result:** all 14 match. The Controls and Effects scenes have no pixel off by more than 40 per channel.
     Dashboard scenes are within 0.04–0.1%: the stat cards' right-edge hairline is ThorVG bug A.
   - **Interactions checked visually:** each scripted interaction does what it should in both builds.
2. **Two real port bugs, found by the demo comparison and fixed:**
   - **Grayscale tint was far too weak.** The C backend passes `100.0` to ThorVG's tint, which is a percentage,
     stored as `(uint8_t)(100.0f * 2.55f)` = 254. The port used 100 out of 255. (§13's note is corrected.)
   - **A rounded clip lost its anti-aliased edge at fractional positions.** The mask spanned the rounded clip
     rectangle instead of every pixel the shape touches.
3. **Render fuzzer, wider:** it now also generates grayscale (`gray=1`) and brightness (`bright=K`), and treats
   grayscale as an effect scene for bugs B/C.
   - **New known class E, a port limitation (not a ThorVG bug):** a blend inside a brightness filter. ThorVG's
     brightness scene has no effect of its own, so it passes through and the blend reaches the backdrop; ThorVG then
     draws a duplicate of the subtree for the overlay. The streaming port renders the filter isolated.
   - **Results:** 490 of 500 frames match (seed 1) and 485 of 500 (seed 3), with the rest all known A–E. With Arial
     text, 298 of 300. 0 unexplained. The layout fuzzer still matches 300 of 300.
4. **Browser host:**
   - **Automated:** `claywind-hosts/browser/test_client.py`, a raw-socket client, checks the page, the 404, the
     handshake's accept key, frame rectangles, the pointer cursor, clicks ("Clicked 2"), opening Controls, typing
     into the name field, Tab, Enter, and `T` to light mode.
   - **Manually in Chrome:** the page renders, and clicks switch tabs and the theme.
5. **Tests:** 72, including `demo_test.cee` (every tab fits; a scripted Down, Down, Enter opens Effects; the clock).

**Performance:**
- Layers (opacity, blend, filter, shadow) now blur and composite only their content's bounding box, grown by the
  blur's reach. The pixels are the same as before, and the fuzzer and demo results are unchanged.
- **Dashboard frame:** 35.7 → 16.9 ms. Controls take 7.6 ms and Effects 12.1 ms (1024×640, Apple silicon, -O2).
- **What's left in the profile:** `fillPath` (rasterization) leads, then `popLayer`'s content scan.

**Language findings:**
- A struct that holds a loan cannot be a `dyn` interface value (N0268), so `ScriptPlatform` copies its script.
- `Console` is blocking, so async code uses `AsyncConsole`.
- A `dyn` call is "may sleep" unless the interface method is `@effects()`.
- There are no multi-line string literals: the page is written line by line. Arrays of `StringView` aren't allowed
  either.
- Program arguments come from `Process.argument(i)`.
- `TextWriter` has `signed` but no `unsigned`.

**Not done:**
- The browser canvas is fixed at 1024×640: the Raster's size is set at creation, so window resizing would need a
  Raster sized for the largest window.
- The terminal host still runs its own small demo, not `claywind-demo`, which is laid out for 1024×640 pixels, not
  character cells.

## 17. Cleanup with ceesafec 0.11.0 (2026-11-04)

The workarounds listed in CEESAFE-FINDINGS.md §D are gone, now that 0.11.0 has generic methods, `dyn` reborrows,
scoped values behind `borrow dyn`, and arrays of views. The packages now need ceesafec 0.11.0 or later.

**API changes (public):**
- `ui.endFrame(mut platform, metrics)` and `ui.renderInto(mut backend)` replace the free functions.
- `tree.endLayout(metrics)` and `tree.renderInto(mut backend)` replace `endLayout(...)` and `renderTree(...)`.
- `Controls.textInputEx(...)` replaces the free `textInputEx`.
- The controls take item lists as `Slice<StringView>` (C: `const char **` and a count). `itemCount` and `itemAt`
  are gone.
- `ScriptPlatform<region r>` borrows its script.

**Inside:**
- The demo's item lists and the browser page are `const [StringView; N]` tables.
- `Rig` is gone from the controls test.

**Verified:**
- 72 tests pass compiled.
- The 14 demo_compare scenes, rendered by the headless host, hash identically before and after.
- The browser host serves a byte-identical page, and `test_client.py` passes.

**ceesafec 0.12.0 (2026-11-04).** The demo's item tables and the browser page are now `static [StringView; N]`
(ADR 0066), so they are sliced where they are named: the `let x = TABLE;` lines are gone. Verified the same way: all
packages check, 72 tests pass, the 14 scenes hash identically, the page is byte-identical, and `test_client.py`
passes. The packages now need ceesafec 0.12.0 or later.

## 18. The desktop host: native windows (2026-11-04)

**What it is.** `claywind-hosts/desktop` runs the demo in a native window on macOS, Windows and Linux, still 100%
CeeSafe. It became possible once CeeSafe ADR 0069 added `Window` to lib/std (AppKit, Win32 and X11 in the C
runtime). It is the host the owner asked for as "a native app demo".

- **`DesktopPlatform`** (`src/platform.cee`) folds `WindowEvent`s into ClayWind's `Platform`:
  - pointer, buttons and wheel, with one notch giving 2.5 units, as in the browser page;
  - the named keys and F1–F12;
  - modifiers, taken from each key event, since a modifier alone sends nothing;
  - typed text through `nextChar`;
  - focus loss, which releases everything held.
- **The loop** (`src/main.cee`) drains events, lays out and renders a frame, presents it, then calls `waitFrame`.
  - **Resizing.** The window resizes freely: the layout follows it, and the frame follows through the new
    `Raster.resize`, up to 1920 × 1200.
  - **Fonts.** It looks for Arial on macOS and Windows, then Linux's Microsoft core fonts or DejaVu, or takes
    `CLAYWIND_FONT_DIR`.
- **`Raster.resize(width, height)`** (`claywind/src/raster_core.cee`) is new. It changes the frame's size within the
  capacity `create` was given. No buffer is reallocated, since each was sized for the capacity.
- **Retina** (§19): frames are drawn at the display's pixel ratio.

**Verified:**
- **macOS** (Apple silicon): the dashboard renders at about 50 frames per second.
- **Windows 11 ARM64** (Parallels VM; MSVC from the emitted C): a real mouse click opens Controls, and `WM_CLOSE`
  ends the program.
- **Ubuntu 22.04 on Xvfb** (gcc): with DejaVu fonts, a click opens Controls, and `WM_DELETE_WINDOW` ends the program
  with status 0.
- **The owner** ran it on the Mac and on the Windows VM: "Worked perfectly on both mac and windows vm".
- **ClayWind:** all packages check, and the 72 tests pass.

## 19. Retina pixel ratio and incremental rendering (2026-11-04)

**Pixel ratio.** `Raster.setPixelRatio(ratio)` makes every frame start from a `scale(ratio)` transform.
- **Layout** stays in points.
- **Drawing:** paths, text, clips, images, gradients, shadows and blur all go through the transform, so they come out
  in device pixels.
- **The rectangle-clip fast path** now also applies at the ratio's scale.
- **Frame size:** a host sets it to points × ratio with `Raster.resize`.
- **The desktop host** draws at `window.scale()` (2 on a Retina display). Past 2880 × 1800 pixels it uses a lower
  ratio.
- **The headless host** has `CLAYWIND_PIXEL_RATIO=N`.
- **Verified:**
  - at ratio 1, the 14 demo scenes are byte-identical to before;
  - at ratio 2, box-downsampled to 1×, they match the 1× frames to within anti-aliasing: at most 0.010% of pixels
    off by more than 40, in two Effects scenes.

**Incremental rendering** (`claywind/src/damage.cee`).
- **`Damage` compares frames.** It hashes each frame's commands and keeps the area each one paints. A frame then
  needs one of three things:
  - nothing, when every hash matches;
  - a redraw of up to four boxes, covering the old and new areas of each changed command, or of everything inside a
    changed bracket;
  - a full redraw, when the structure, size, ratio or clear color changed.
- **`Damage.render`** draws the boxes with the new `Raster.beginRegion`, which clears only a box and keeps the
  previous frame's pixels elsewhere.
- **Raster changes:**
  - **Fills and masks** stay inside the region.
  - **Blur** (shadows and blur filters) is computed over the region widened by its reach (`blurReach`), so the
    pixels inside are exact.
  - **Edges cut by a box.** `accumulateLine` now splits an edge that crosses a box's side within a row, where it used
    to clamp it. Clamping bent the edge, which miscomputed a boundary pixel's coverage. That case also occurs in full
    frames at clip and frame edges: 3 pixels of `dashboard-click` changed by at most 5, now exact.
- **The desktop host** renders through `Damage`, and presents only when something changed. The headless host has
  `CLAYWIND_INCREMENTAL=1` (every frame incremental) and `CLAYWIND_DAMAGE_LOG=1` (each frame's redrawn box and, for
  a full redraw, why).

**Verified:**
- **Exactness.** Each of the 14 scenes, drawn incrementally frame after frame, ends byte-identical to its full
  redraw, at ratio 1 and at ratio 2.
- **Cost per frame at ratio 2** (headless, Apple silicon):
  - full redraw: 64 ms;
  - incremental: 2.1 ms on the dashboard, 1.6 ms on Controls and 4.1 ms on Effects.
- **The desktop app on a Retina display:**
  - rendering at 2× alone: 13 FPS at 97% CPU;
  - with incremental rendering: 38 FPS at 47%;
  - with the sRGB window colour space as well: 31% CPU.
- **Where the rest goes.** The remaining cost is presenting: every frame copies the whole frame for the window,
  because the rotating badge changes every frame.

**Done in CeeSafe since** (both shipped in ceesafec 0.14.0):
- **An sRGB window on macOS** (ADR 0069 §8): Core Animation no longer converts every frame's colours on the CPU.
  That took idle CPU from 47% to 31%.
- **`Window.presentChanged`** (ADR 0070): the window takes only the boxes that changed. `Damage.redrawnCount()` and
  `Damage.redrawn(k)` give them in pixels, and the desktop host passes them on. On macOS the frame lives in two
  IOSurfaces, so no frame is copied whole.
- **Result:** the desktop app idles at 16–24% CPU on a Retina display, at 55 FPS, against 13 FPS at 97% with 2×
  rendering alone.
- **The packages now need ceesafec 0.14.0 or later.**
