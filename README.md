# Splatoon 2 — native Linux static recompilation

Splat2-ReTotK recompiles Splatoon 2's retail `main` and its SDK modules into native Linux x86-64
C++ and runs them on a vendored copy of the *Tears of the Kingdom* Linux static-recompilation
runtime, [`Muhammad1259-sigma/totk-recomp`](https://github.com/Muhammad1259-sigma/totk-recomp)
at `a32f709` (MIT), under `baseline/totk-recomp/`. The target is the Steam Deck at 1280×720/60.
This repository holds the generator, the runtime changes, the platform map and the notes — no
game code, no game data and no keys. LAS is not used.

## Status

The null (headless, no GPU) build links and boots. It reaches:

```
[ld] ftab 114173 functions, 784 imports (258 HLE, 63 lifted sdk, 192 lifted-unbound, 271 stubbed)
[boot] DT_INIT -> nninitStartup -> init_array (1604 entries) -> nnMain
[nvn] window with 3 textures            (3 buffers, present interval 1)
[audio] frame 32000: 0 voices           (audio renderer running)
[pl] no shared font available: giving the engine an empty one
[imp] nn::fontll::ScalableFontEngine::GetKerning
```

The boot passes `DT_INIT`, `nninitStartup`, the 1,604 init-array entries and `nnMain`, then the
game's own engine init: memory report, NVN device and window, presentation thread, audio
renderer, romfs sound banks, the `ELink2`/`SLink2` databases and the lifted `nn::fontll` text
engine.

There is **no visible rendering yet**. The null backend presents nothing. The Vulkan build is
built and linked: `libshaderc_combined.a` (shaderc v2025.4, glslang + SPIRV-Tools merged) was
built from source in the container and is passed to `mkninja_linux.py` through `--syslib` +
`--sysinc`; a frame has not been captured yet.

Current blocker: a null dereference in `Cui::CustomizePartsSet::onInitialize` (`main 0x1d9530`).
It looks up `/L_ItemBtn_%02d` via `Cui::Page::findPartsControl` (`0x20bd74`), gets null, and
dereferences it: the page's layout tree lacks those controls at `onInitialize` time. This is a
UI-tree problem, **not** a rendering problem. The generator emits the nearby tail call
correctly (`[[clang::musttail]]`); the old port failed here for a different reason.

## Lift coverage

Measured on the retail base NSP with the vendored generator:

| Module | Functions | Instructions | Unhandled | Disposition |
|---|---:|---:|---:|---|
| `main` | 114,172 | 5,261,347 | **0** | lift |
| `sdk` | 14,426 | 714,539 | 1,657 | HLE first (AES + halfword atomics) |
| `subsdk0` (`nv`/`nvn`) | 4,299 | 185,120 | 43 | HLE first (atomics, `xtn2`, `smaxv`, `dsb`) |
| `subsdk1` (`nn::vi`) | 385 | 13,656 | 6 | HLE first (halfword atomics) |
| `subsdk2` | 76 | 10,643 | **0** | lift later |
| `subsdk3` | 496 | 41,514 | **0** | lift later |

`main` lifts with **zero** unhandled instructions. The vendored baseline carries three local,
game-agnostic generator fixes needed for that:

- scalar `FADDP Sd, Vn.2S` (without it `main` has 15 unhandled instructions);
- PIC jump tables in the `add d, d, base` form: `sdk` 0 → 270 and `main` 0 → 1,108 tables
  resolved, leaving `br` dispatch at 378 (`sdk`, from 648) and 6,360 (`main`, from 7,468);
- functions synthesised at non-FDE `BL` targets (`main 0x13a6f2c`), which leaves `main` at
  114,173 functions and `sdk` at 14,429 (+ cold fragments).

## How it works

The six modules are mapped at fixed, non-overlapping bases; only `main`'s base is the retail one.

| Module | Base | Platform content |
|---|---|---|
| `main` | `0x7100000000` | game/engine code, `nn::init::InitializeAllocator`, `nvnLoadCProcs` |
| `sdk` | `0x7180000000` | `nn::os`, `nn::mem`, `nn::time`, `nn::oe`, `nn::diag`, `nn::fs`, `nn::nifm`, `nn::util` |
| `subsdk0` | `0x7200000000` | `nv` (`nv::InitializeGraphics`, allocator installs), `nvnBootstrapLoader` |
| `subsdk1` | `0x7280000000` | `nn::vi` (151 functions, including the 6 boot entries) |
| `subsdk2` | `0x7300000000` | exports only; lifted later |
| `subsdk3` | `0x7380000000` | exports only; lifted later |

All 51 boot functions resolve to real bodies in the dump: 39 in `sdk`, 6 `nn::vi` (`subsdk1`),
3 `nv` + `nvnBootstrapLoader` (`subsdk0`) and two in `main`. Of `main`'s 784 imports, 772 resolve
in the dump; the only non-marker misses are the eight `glslc*` shader-compiler functions.

Inside the baseline the pipeline is `tools/nso.py` (decompress NSO) → `tools/funcs.py` (find
functions) → `tools/recomp/gen.py` (AArch64 → C++); `mkninja_linux.py` writes the ninja build.
The runtime (`runtime/`) HLEs the imported Switch services (`nn::os`, `fs`, `vi`, NVN, audio,
input, time) and binds the rest to lifted bodies where they exist; 271 imports stay stubbed in
the null build. The NVN-on-Vulkan layer (`runtime/nvn/`, 41 files) supplies the Maxwell → SPIR-V
translator, ASTC, SMAA, command buffers and texture/pipeline state; `backend_null.c` is the
headless stand-in.

Splatoon-specific runtime work, all kept game-agnostic: a weak TotK frame-delta hook; the real
`MemoryInfo` heap layout (`+0x10`/`+0x18`/`+0x20`); SDK 3.x audio parameter validation and
device names; `nn::pl` shared-font state; and `runtime/hle_svc.cpp`, the `svc::aarch64::lp64`
layer for lifted `sdk` code, where `svcOutputDebugString` surfaces the game's own log text.

## Build

Everything builds in a Podman container; nothing is installed on the host. `CC=clang CXX=clang++`
must be set explicitly — `mkninja_linux.py` otherwise defaults to `clang-19`. Build paths must
not contain spaces: ninja splits `-I<path>` on them. Inside the container the tree is mounted
at `/w`.

```bash
cd <work>/Splat2-ReTotK
# deps: static Opus + Vulkan-Headers; SDL3 comes shared from the container
baseline/totk-recomp/tools/linux/build_deps.sh <work>/totk-linux/deps

export CC=clang CXX=clang++

python3 baseline/totk-recomp/tools/recomp/mkninja_linux.py --null \
    --gen <work>/gen-totk/main --syslib <sniper>/usr/lib/x86_64-linux-gnu \
    --out <work>/totk-linux/build-null --obj <work>/totk-linux/obj-null \
    --deps <work>/totk-linux/deps --gen-opt -O1 --gen-pool 5

ninja -C <work>/totk-linux/build-null -j10
```

`--null` skips Vulkan and shaderc but still links a static `libvpx.a` from the sniper sysroot.
`--gen-opt -O1` compiles the 88 generated `main` TUs and 12 `sdk` TUs at about 11 s each
(~4.5 min on this 22-core host); omit it for `-O2`. `--gen` is the generated `main` directory,
with `sdk` beside it at `<work>/gen-totk/sdk`.

## Run

```bash
TOTK_LIFT_ALL=1 TOTK_NVN_INT="0=53" \
TOTK_ROMFS=<work>/base-nsp/romfs TOTK_IMG=<work>/img TOTK_HEADLESS=1 \
    timeout -k 5 240 ./totk
```

- `TOTK_IMG`, `TOTK_ROMFS` — the reader's own decompressed module images and extracted RomFS.
- `TOTK_HEADLESS=1` — console-only run; no window, no presenter.
- `TOTK_LIFT_ALL=1` — bind `main`'s unimplemented imports to the `sdk`'s real lifted bodies
  (192 here) instead of 0-stubs, with service/IPC namespaces excluded. Temporary switch; it
  belongs in the game definition for this title.
- `TOTK_NVN_INT="0=53"` — per-game NVN API major. `nvnDeviceGetInteger(dev, 0)` is the major,
  and Splatoon 2 requires 53 where TotK requires 55. Stopgap; it belongs in the game definition.

Logs go to `<work>/logs/`, outside the repository. They contain memory sizes and file names from
the reader's own dump, not game data.

## Repository layout

| Path | What |
|---|---|
| Root `*.md` | `HANDOFF.md` (session state), `BOOT_SMOKE_NULL.md` (null boot), `SPLAT2_RETOTK_PLAN.md` (plan), `PLATFORM_*.md` (platform map), plus analysis notes |
| `baseline/totk-recomp/` | vendored MIT TotK Linux baseline: generator, HLE runtime, NVN-on-Vulkan layer, Linux scripts |
| `tools/` | NSO/MOD0 and dynsym analysis (`tools/nso`, `tools/static`), Ghidra exporters, guest/runtime patch scripts (`tools/patches`) |
| `port/` | earlier hand-written platform layer and unit tests, kept as the body-level cross-check reference |
| `harness/`, `reference/`, `sp2win/`, `docs/` | standalone guest-code harness, sead reference headers, old-port Windows runners, earlier notes and images |

## Roadmap

1. **Game definition:** title `01003bc0000a0000`, build ID `F18FF3CFCBAD0884D72ABBEB6C540D6B…`,
   six modules, heap/alias/pool sizing, 1280×720/60 and NVN API 53; `TOTK_LIFT_ALL` on by
   default.
2. **Vulkan build** (static shaderc) for the first visible frame, then title/2D UI at 720p60.
3. **Tutorial 3D room** — the smallest 3D scene — then the **plaza/stage 3D pass**.
4. **Port the old port's fixes** as the scenes reach them: packed-row glyph atlas + refresh,
   language byte order, scissored clears, R11G11B10F, six-axis, tail call.

## Relationship to the other project

`bangmcpe3321/sp2decomp` is a separate, older port of the same game (Windows, Vulkan); this repo
is independent and does not use its runtime. Cross-port findings go there as pull requests; the
generator/SDK-contract note is `RECOMP_GENERATOR_AND_SDK_CONTRACTS.md` (PR #7 per `HANDOFF.md`).
Nothing here states anything about that project's current state.

## Boundaries and legal

- The repository contains no game data, keys, saves, generated C or built binaries. `.gitignore`
  excludes exefs/romfs extracts, `*.nso`, `*.szs`, `*.bfres`, `*.byml`, keys and build output.
- You build from your own dump and your own keys. Generated C for `main` alone is about 361 MB;
  it stays outside the tree.
- The vendored baseline is MIT (`Copyright (c) 2026 the totk-recomp contributors`); keep the
  attribution. This repository's own code is MIT (`LICENSE`).
- Splatoon 2 and Nintendo Switch are trademarks of Nintendo. Not affiliated with or endorsed by
  Nintendo.

## Credits

- **totk-recomp** (MIT, the totk-recomp contributors) — the vendored Linux runtime baseline.
- **LAS Recomp** (MIT, Peiikai) — the NVN-on-Vulkan layer, `runtime/nvn/LICENSE.LASRecomp`.
- **SMAA** (MIT, Jorge Jimenez et al.) — `third_party/smaa/`, `runtime/nvn/smaa/`.
- **Opus** headers (BSD-3-Clause, Xiph.Org) — `third_party/opus/COPYING`.
- **stb_truetype** (MIT or public domain, Sean Barrett) — `runtime/linux/stb_truetype.h`.
