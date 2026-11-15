# UI blocker: `Cui::CustomizePartsSet::onInitialize` gets null controls

State: the null and Vulkan builds both stop here, before the first frame. This note records what
was established, including the decisive trace, so the next session does not repeat it.

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
