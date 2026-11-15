# Next-session prompt

Copy the block below as the opening message.

---

You are continuing the Splatoon 2 → native Linux port in
`/mnt/SSD Storage/Games/Ports/Switch/Splat2/work/Splat2-ReTotK`.

READ FIRST, in this order:
1. `HANDOFF.md` — state, paths, build/run recipes, generator fixes, boundaries.
2. `UI_BLOCKER_NOTES.md` — the current blocker, the traced call chain, what is ruled out, and the
   next candidates.
3. `BOOT_SMOKE_NULL.md` — null/Vulkan boot stages and the generator numbers.
4. `SPLAT2_RETOTK_PLAN.md` — milestones.

CONTEXT IN ONE PARAGRAPH
The port runs Splatoon 2's lifted `main` + HLE runtime on a vendored TotK baseline
(`baseline/totk-recomp`, MIT). Both builds work: headless (`work/totk-linux/build-null`) and
Vulkan with a real window (`work/totk-linux/build-vk`, Intel Arc, swapchain 1280x720). Boot
reaches `nnMain` and the game's own engine init: memory report, NVN device (API 53), presentation
thread, audio renderer, romfs sound banks, ELink2/SLink2, the lifted `nn::fontll` engine and
layout loading. **No frame has been drawn yet** — the boot dies in UI page construction.

CURRENT BLOCKER
`Cui::CustomizePartsSet::onInitialize` (`main 0x1d9530`) dereferences a null control at
`main 0x1d95f8`; the name is `/L_ItemBtn_00`. A diagnostic skip showed the next failure is
`/L_CustomizeIconBtn_00` in `CustomizeMainPage::onInitialize` (`main 0x1d24d0`). Both control
families live in the one sub-layout `Cst_CustomizeDetail_00`, which exists in the romfs but is
never queued by the page. Every layout that *was* requested loaded fine, so this is a layout-queue
difference, not a failed load. Language is ruled out (`nn::settings::eq` is now implemented
correctly). Next candidates: `nn::oe::GetOperationMode` (TV vs handheld can select page handler
sets), then the page-manager state that decides which handlers/pages exist at boot.

WHAT TO DO FIRST
1. Rebuild and reproduce, so you start from logs rather than assumptions:
   ```bash
   cd <work>   # /mnt/SSD Storage/Games/Ports/Switch/Splat2/work
   podman run --rm -v "$PWD:/w:z" -w /w/Splat2-ReTotK/baseline/totk-recomp localhost/engage-linux-build:latest bash -lc \
     'ninja -C /w/totk-linux/build-null -j10'
   podman run --rm -v "$PWD:/w:z" -w /w/totk-linux/build-null localhost/engage-linux-build:latest bash -lc \
     'TOTK_LIFT_ALL=1 TOTK_NVN_INT="0=53" TOTK_TRACE_FS=1 TOTK_ROMFS=/w/base-nsp/romfs TOTK_IMG=/w/img TOTK_HEADLESS=1 timeout -k 5 240 ./totk >/w/logs/boot-null-40.log 2>/w/logs/boot-null-40.err'
   ```
2. Probe the operation mode: what our `nn::oe::GetOperationMode` HLE returns, what the game
   derives from it (the page handler set / layout queue), and whether forcing the other mode
   changes the queue (then `Cst_CustomizeDetail_00` appears). `TOTK_TRACE_STR=1` with
   `gen.py --trace` on the queue/loader functions shows exactly what is queued; build the trace
   into its own `--obj`/`--out` so the normal objects stay clean.
3. If the mode is not it, find what builds the queue (`Lp::UI::Impl::LayoutResourceMgr` +
   `RootArchiveLayoutResourceAccessor::loadImpl`, `main 0x1304184`) and read where the member list
   comes from.

GOAL
Reach the first frame: pass the customize page construction without patching game code, then take
a Vulkan screenshot-level check (window opens, swapchain 1280x720, `[nvn]` draws recorded). Tell
the user before any run that opens a window. After the first frame, the milestones are title/2D UI
at 720p60, then the tutorial 3D room, then the plaza.

RULES
- Nothing on the host: Podman only (`localhost/engage-linux-build:latest`). No `/tmp`; work under
  `work/`.
- Never commit or print keys, game data, saves, generated C, or built binaries. Generated C and
  build output live under `work/` and are ignored.
- Diagnose from the game's own bodies first (disassembly/trace), and prefer lifting real code over
  writing HLE for it; HLE only what needs a service or the kernel (see the lift/HLE boundary in
  PR #7 of `bangmcpe3321/sp2decomp`).
- Keep the vendored generator fixes; do not switch to LAS.
- Commit on `retotk-baseline`, push to both remotes (GitHub `azlekayn/Splat2-ReTotK`, Forgejo
  `wingrepo/Splat2-ReTotK`). Don't touch `bangmcpe3321/sp2decomp` PRs #3–#6.
- Report with concrete log excerpts and file paths; update `HANDOFF.md` and
  `UI_BLOCKER_NOTES.md` as state changes.

KNOWN TRAPS (from earlier sessions)
- Guest register dumps can be stale: generated functions run on a local `LCtx` and sync back only
  at `lso`/`lsi`.
- `nn::*` arguments that look like values are often *references* (e.g. `settings::eq`).
- Build paths must not contain spaces; `CC`/`CXX` must be set to `clang`/`clang++`.
- The fs open log caps at 40 entries unless `TOTK_TRACE_FS=1`.
- `TOTK_NVN_INT="0=53"` is a stopgap; the per-game NVN API major (53 for this title) belongs in a
  game definition.
