# UI blocker: `Cui::CustomizePartsSet::onInitialize` gets null controls

State: the null and Vulkan builds both stop here, before the first frame. This note records what
was established, including the decisive trace, so the next session does not repeat it.

## 2026-11-15 update — the two earlier hypotheses are REFUTED; it is a control-name problem

Two things ruled out with assets/traces, and the real proximate cause located:

1. **Operation mode is not the selector.** `nn::oe::GetOperationMode` (HLE `hle_oe.cpp`) has only
   two call sites in all of `main` (`0x123bbc0`, `0x123bd6c`, the nn::oe performance manager), and
   forcing handheld (`TOTK_HANDHELD=1`) vs console gives an identical 23-layout set, identical
   files, identical crash (logs `work/logs/boot-null-handheld.{log,err}` vs `…-console.*`).
2. **`Cst_CustomizeDetail_00` is NOT the missing layout.** It was decompressed and checked
   (`work/szs_list.py`, an in-repo Yaz0+SARC reader): `Layout/Cst_CustomizeTV_00.Nin_NX_NVN.szs`
   → `blyt/Cst_CustomizeTV_00.bflyt` **contains panes `L_ItemBtn_00..23` and
   `L_CustomIconBtn_00..04`** — exactly the names the two `onInitialize` functions look up.
   `Cst_CustomizeDetail_00` contains `L_ItemDetail_*`, `L_Wpn_00`, `L_Parameter_00` — *not* the
   item buttons. Those panes are `prt1` part panes of the TV layout. So the missing-layout framing
   in the earlier notes (and in `HANDOFF.md`/`BOOT_SMOKE_NULL.md`) is wrong.
3. **The generator drops no tail call.** `work/find-dropped-tailcalls-totk.py` (adapted from
   `tools/rework/find-dropped-tailcalls.py`) reports `main: functions ending in b 20074, dropped 0`.
   `f_20bd74` (`Cui::Page::findPartsControl`) emits its `b 0x20cf60` correctly.

### The actual failure: the page's control list exists, but the controls' names are invalid

Tracing `f_20bd74` → `f_20cf60` (`Control::List::searchAs<PartsCtrl>`) → `f_124b14c` (name lookup)
with `TOTK_TRACE_STR=1` (`work/logs/boot-trace-41.log`) showed the search runs and returns 0:

```
> 710020bd74(10c0372bb0, ...) "/L_ItemBtn_00"      ; findPartsControl(page=10c0372bb0)
> 710020cf60(10c0386518, ...) "/L_ItemBtn_00"      ; list = [page+0x3f0]+0x38
> 710124b14c(10c0386518, 7102ff5d88, ...) "/L_ItemBtn_00"
< 710124b14c = 0
```

Instrumenting `f_124b14c`'s loop in a scratch tree (`work/gen-totk/main-trace/`, kept for A/B)
shows the list at `page+0x3f0` is **non-empty (~30 controls)** and the RTTI check at `0x124b1d0`
**passes for every node**. What fails is the byte-for-byte *name* compare at `0x124b248`. For each
node, `[node+0x20]` is the name `char*` and `[node+0x28]` packs `(len<<32)|hash`. The name pointers
point into the UI thread's **stack** (`[os] CreateThread … stack=1002003000+100000`), and at search
time most read back garbage:

```
[search] name node=10c0ff90e8 ptr=10021022cc len=13 hash=…  'q'
[search] name node=10c111fee8 ptr=10021022fc len=12 hash=…  '/L_KeyIcon_00'
```

i.e. the registered controls hold name references into stack temporaries that have since been
reused. The item/custom-icon part panes are not the special case — **every** lookup would fail
because the names do not survive. `findPartsControl` returning null for `/L_ItemBtn_00` is a
symptom of that, not of a missing layout.

Open question (in progress): what sets a control's `[+0x20]` name field — a copy into the control's
own/heap storage (which our port is losing), or a borrowed pointer to a caller `FixedSafeString`
(the pane walker `f_1289594` builds one at `sp+0x30`)? The next step is to instrument the write and
compare the pointer/content at write time vs search time.

### SOLVED 2026-11-15: our `nn::os::CreateThread` never wrote the stack base into the guest `nn::os::ThreadType`

The name field is written by `Lp::UI::Impl::Name::init` (`main 0x124351c`). For the `Control`
constructor's `allocType == 0` it decides SHARE vs COPY with:

```
this_chars = ...; if (sead::MemUtil::isStack(this))      -> SHARE
src_chars  = [src+8]; if (!sead::MemUtil::isStack(src))  -> SHARE   ; else COPY (heap alloc + memcpy)
```

So a *stack* source string is supposed to be **copied**. `sead::MemUtil::isStack` (`main 0x13a1f30`)
returns 0 for every address in this port, so `Name::init` always took SHARE and stored a raw pointer
into the caller's stack frame; when that frame was reused the name became garbage and
`findPartsControl` returned null for every lookup.

Why `isStack` returned 0: it computes each thread's region from the **guest `nn::os::ThreadType`**
at `[[seadThread+0x224]+0x50]` (stack base) plus `s32[seadThread+0x88]` (stack size). Our
`nn::os::CreateThread` HLE stored the stack in its own host-side `HThread` but never wrote it into
the guest `ThreadType`, so every region was `[0, size)` and no stack pointer matched. A live probe
at a stack lookup showed `t224=0x1002103020 t224_80=0 t136=0x100000` (ThreadType, base 0, size 1 MB).

Fix (runtime/HLE only, game code untouched) — `runtime/hle_os_thread.cpp`:

```c
// in os_CreateThread / os_CreateThread7:
if (c->x[0]) *(u64*)(c->x[0] + 0x50) = c->x[3];   // ThreadType stack base = the stack the game passed
// in os_register_main_thread:
*(u64*)(tt + 0x50) = stack_lo;
```

Result (`work/logs/boot-null-61.log/.err`, instrumented build `build-trace`):
- `sead::MemUtil::isStack` now returns 1 for stack sources (`logs/bt62.log`: 234 × `ptr=100210292c -> 1`);
- the customize page constructs, the fs trace goes from 23 to **~93** unique layouts, and the boot
  no longer faults at `main 0x1d9530`;
- the boot then reached service inits whose lifted bodies abort on `sm:`
  (`nn::friends::Initialize`, then `nn::time::GetDeviceLocationName`). Excluding those service
  namespaces from `TOTK_LIFT_ALL` (in `rt_main.cpp`'s `kService` list) plus adding the missing
  auto-clear `nn::os::WaitEvent` HLEs cleared them, and the engine now reaches `RootTask` init and
  its `SceneLoad` thread and runs **without crashing** (`work/logs/boot-null-65.log`: `[vsync] 7200
  ticks, ~16.6 ms`, `[audio] frame 24000`).
- the main thread then parked in `nn::os::WaitThread` because `nn::os::JamMessageQueue` was
  `UNIMPL` (a worker never got its stop message). Implementing `JamMessageQueue`/
  `TryJamMessageQueue` (`runtime/hle_os_thread.cpp`) let the scene framework start
  (`SceneLoadInCalc`, `SceneGeneralMain/Sub1/Sub2`) and the game issue its **first frame**:
  `work/logs/boot-null-67.log` has `[nvn] first present (texture 0)` and 69 recorded
  `nvnDraw*/nvnClear` calls (headless/null backend records but does not display them).

(Scratch instrumentation used for this lives in `work/gen-totk/main-trace/` and is not committed;
`work/logs/boot-trace-*.log` hold the probes. `work/sym.py`, `work/szs_list.py`,
`work/rela_vtable.py`, `work/find-dropped-tailcalls-totk.py` are the in-repo diagnostics used.)

## The crash

`main 0x1d9530` (`Cui::CustomizePartsSet::onInitialize`) loops `i = 0..0x17`, formats
`/L_ItemBtn_%02d`, looks the control up with `Cui::Page::findPartsControl` (`main 0x20bd74` →
`Control::List::searchAs<PartsCtrl>`) and stores the result. At `main 0x1d95f8` it reloads that
slot and dereferences `[ctrl + 0x1f0]` **without a null check** — so on hardware the control is
always present.

Observed: the lookup returns null on the first iteration. The name was read out of the crashing
guest frame (`[stack]` lines, added to the crash report in this session): `/L_ItemBtn_00`.

Note the dump's guest registers are unreliable here — generated functions run on a local `LCtx`
copy and only sync back at `lso`/`lsi` points, so `cx->x8` can be stale. The fault address
(`0x1f0`) is the real evidence that the base was 0.

## How the page is created

Backtrace, symbolicated (all `main`-relative):

```
Lp::UI::UIMgr::prepare
  Cstm::UIMgrCstm::onPrepare
    Cui::SystemPageMgr::initialize
      Cui::PageMgr::createHandler<CustomizePageHandler>(int, SafeStringBase const&, PauseType)
        Cui::PageHandler::load(SafeStringBase const&)         0x20d1c0
          Cui::CustomizePageHandler::createPage
            Lp::UI::PageHolder::createPage<CustomizeMainPage>
              Cui::Page::initialize
                Cui::CustomizeMainPage::onInitialize           0x1d24d0
                  Cui::CustomizePartsSet::onInitialize         0x1d9530   <-- here
```

`PageHandler::load` builds `"UI_%s"` (format at `main+0x2804b34`) and calls
`main 0x127fe94(this->layout, name)`, **then calls `createPage()` unconditionally**. A failed or
empty layout load therefore does not stop page creation; it just leaves the control tree empty.

## Decisive trace

`gen.py --trace 20d1c0,127fe94,127ffb4` plus `TOTK_TRACE_STR=1` (new: prints string arguments,
including a `SafeStringBase`'s characters behind `+8`) gives, in boot order:

```
> 710020d1c0(..., name)  "Boot"          -> > 710127fe94(..., name)  "UI_Boot"
> 710020d1c0(..., name)  "Customize"     -> > 710127fe94(..., name)  "UI_Customize"
```

So the customize page's layout name is **`UI_Customize`**, and the load function is called only
twice for the whole boot. `Layout::load` accounts for those two calls, while 23 `Layout/*.szs`
files are opened through a different path — the individual layouts referenced by the page's
layout group (`Cst_CustomizeTV_00` among them).

Neither `Layout/UI_Customize.Nin_NX_NVN.szs` nor any `Customize.szs`/`Boot.szs` exists in the
romfs; the page layouts are **groups** resolved by name, not files with that name.

## What is present and what is missing

From `TOTK_TRACE_FS=1` and the `.bars`/`.barslist` resource names the engine loads per control:

* `Cst_CustomizeTV_00` **is** loaded, and its children enumerate as
  `UI_Cst_CustomizeTV_00_L_HeadBtn_00`, `…_PantsBtn_00`, `…_AmiiboBtn_00`,
  `UI_Default_Cst_CustomizeTV_00_WeaponGearBtnCtrl`, `…_OptionBtnCtrl`, `…_CustomizeBtnCtrl`.
* `Layout/Cst_CustomizeDetail_00.Nin_NX_NVN.szs` **exists in the romfs but is never opened**, and
  `Sound/ResourceList/UI_Body_Cst_CustomizeDetail_00.barslist` exists — i.e. the layout that owns
  the `/L_ItemBtn_*` controls is a real asset that this boot never requests.

> **REFUTED 2026-11-15** (see the update at the top): the asset check shows `Cst_CustomizeTV_00`
> itself contains `/L_ItemBtn_*` and `/L_CustomIconBtn_*` as `prt1` part panes, so the missing
> `Cst_CustomizeDetail_00` is a red herring. The candidates below are kept only as history.

So the question is now narrow: **why does the customize page group resolve to a set that omits
`Cst_CustomizeDetail_00`?** Candidates, in order of likelihood:

1. the page layout group is chosen by a *mode/state* value (TV vs handheld, region, language) that
   our HLE reports differently, so the group's member list differs;
2. the group's member list is read from a resource we serve with a wrong size (our `nn::fs` path),
   so an entry is dropped;
3. the sub-layout is requested later (page wake) and `onInitialize` runs first in this port only
   because a page-manager state differs.

## Cross-reference: the other port hit the same subsystem

`sp2decomp` documents `Lp::UI::Impl::RootArchiveLayoutResourceAccessor::loadImpl`
(`main 0x1304184`) and a `Lp::UI::Impl::DualHeap` allocation that was ~1 KB short for a 58 KB
layout decompression buffer (`RECOMP_BOOT_TO_UI.md`, "Open blocker: UI DualHeap allocation").
That is a different failure on the same path — their layout *was* found and did not fit — but it
confirms the shape: page layouts are decompressed into per-page `sead::ExpHeap` sub-heaps, and the
customize page is one of those pages. A useful next probe is the same one they used: break on the
decompressor with `dst == 0` and see whether `Cst_CustomizeDetail_00` is ever requested at all
(our trace says no) or whether the group list is short.

## The group's actual members (traced, in load order)

```
beginCreateSub("UI_Customize")
  Cst_CustomizeBG_00
  Cst_CustomizeTV_00
  LStick_00
  WeaponGearButton_00
  WeaponIcon_00
  ... (23 layout files in total this boot)
```

`Cst_CustomizeDetail_00` is not among them — and after a diagnostic skip of the null control it
becomes clear that *both* missing control families belong to it:

* `/L_ItemBtn_00` … `/L_ItemBtn_17` (24 slots, `CustomizePartsSet::onInitialize`)
* `/L_CustomIconBtn_00` (`CustomizeMainPage::onInitialize` itself, `main 0x1d24d0`)

So the page is missing one whole sub-layout, not one control. `Sound/ResourceList/UI_Body_Cst_CustomizeDetail_00.barslist`
exists, so the asset is expected by the engine's own resource tables.

The diagnostic skip (5 generated lines wrapped in `if (c->x[8])`) was reverted after confirming
this; it is not a fix, it only proved the failure is systematic rather than one bad control.

## What `beginCreateSub` actually is (ruled out: it is not a resource load)

`Lp::UI::PageHolder::beginCreateSub` (`main 0x127fe94`) is a *named sub-heap*, not a layout
load:

```
sead::ExpHeap::create(size, SafeStringBase const& name, parent, align, dir, flag)
Lp::UI::Impl::DualHeapAdapter::create(heap, ...)
Lp::UI::Impl::LayoutResourceMgr::beginCreate(adapter)
```

so `"UI_%s"` is the *heap name* for the page's sub-heap (explaining why no `UI_*.szs` file
exists), and the page's layouts are queued into `LayoutResourceMgr` by the page code and resolved
through `Lp::UI::Impl::RootArchiveLayoutResourceAccessor::loadImpl` (`main 0x1304184`) while the
sub is open. Every layout the game asked for was found (no `NOT FOUND` in the fs trace), so the
short set is a *queue* difference, not a failed load.

### Ruled out: language

`nn::settings::eq(Language, LanguageCode)` was an unimplemented stub returning 0 for every query
(and the argument is a *reference*, so reading x0 as the value is wrong — it gave garbage like
34614004). Now implemented (dereference x0, compare the code's two-letter tag against the enum).
It reports `Language 1, "en-US" -> 1` correctly, and the customize layout set is unchanged, so
language is not the selector. (The fix is still right: the game's own language matching was
broken, which is the same class of bug the other port fixed with its language-code byte order.)

Next candidates: the operation mode (`nn::oe::GetOperationMode`) and the page-manager state that
chooses handler sets.

## Reproducing the traces

```bash
# strings in traced calls (rebuild with --trace once)
python3 tools/recomp/gen.py <work>/img/main <work>/img/funcs_main.json <out> --trace 20d1c0,127fe94,127ffb4
TOTK_TRACE_STR=1 TOTK_TRACE_MAX=400 ... ./totk
# every file open
TOTK_TRACE_FS=1 ... ./totk
```

`--trace` costs a full regeneration and rebuild; the trace build used a separate `--obj` directory
so the normal objects stay untouched.
