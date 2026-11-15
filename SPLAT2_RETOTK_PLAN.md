# Splatoon 2 on the TotK Linux runtime

**Target: Steam Deck, 1280×720, 60 fps.**

This repository is the Splatoon 2 project. The runtime baseline is vendored under
[`baseline/totk-recomp/`](baseline/totk-recomp/) from
[`Muhammad1259-sigma/totk-recomp`](https://github.com/Muhammad1259-sigma/totk-recomp)
(`a32f709`, MIT). That baseline is a static recompilation of *Tears of the Kingdom* to native
Linux with an NVN-on-Vulkan renderer; it runs TotK at about 60 fps on a Steam Deck. LAS is
not used.

## Why this baseline

- **Full 3D renderer**: `runtime/nvn/` (41 files) with Maxwell → SPIR-V, ASTC, SMAA,
  command buffers, texture/pipeline state. Not a 2D-only renderer.
- **Deck-shaped**: FPS limit, render scale, shader warm-up, `TOTK_*` runtime settings.
- **MIT**: reuse with attribution; no game code or data in the repository.
- The FE3H/`fe3h-Retotk` and XC2 trees are references for multi-game and Linux performance
  work; Splatoon 2 starts from the Linux baseline, not from LAS.

## Lift coverage (measured on the retail base NSP)

| Module | Functions | Instructions | Unhandled | Disposition |
|---|---:|---:|---:|---|
| `main` | 114,172 | 5,261,347 | **0** | lift |
| `sdk` | 14,426 | 714,539 | 1,657 | HLE first (AES + halfword atomics) |
| `subsdk0` (`nv`/`nvn`) | 4,299 | 185,120 | 43 | HLE first (atomics, `xtn2`, `smaxv`, `dsb`) |
| `subsdk1` (`nn::vi`) | 385 | 13,656 | 6 | HLE first (halfword atomics) |
| `subsdk2` | 76 | 10,643 | **0** | lift later |
| `subsdk3` | 496 | 41,514 | **0** | lift later |

`main` needed one generator fix: scalar `FADDP Sd, Vn.2S` (`sdk` lacks nothing there). The
baseline's `tools/recomp/gen.py` now handles the two-operand form; the patch is in
`baseline/totk-recomp/tools/recomp/gen.py`.

Module bases used for the lift:

| Module | Base |
|---|---|
| `main` | `0x7100000000` |
| `sdk` | `0x7180000000` |
| `subsdk0` | `0x7200000000` |
| `subsdk1` | `0x7280000000` |
| `subsdk2` | `0x7300000000` |
| `subsdk3` | `0x7380000000` |

The retail `main` base is `0x7100000000`. The other bases are the port's choice; they must
not overlap.

## The platform layer

The earlier conclusion that the platform layer was missing is wrong. `PLATFORM_LAYER_FOUND.md`
maps **51/51** boot functions to real bodies:

- 39 in `sdk` (`nn::os`, `nn::mem`, `nn::time`, `nn::oe`, `nn::diag`, `nn::fs`, …)
- 6 `nn::vi` in `subsdk1`
- 3 `nv` + `nvnBootstrapLoader` in `subsdk0`
- `nn::init::InitializeAllocator` and `nvnLoadCProcs` in `main`

`main` has 784 imports; 772 resolve inside the dump, and the only non-marker misses are the
8 `glslc*` shader-compiler functions. The HLE layer can therefore be written against the real
bodies instead of call-site guesses.

## Plan

1. **Runtime integration (current).** Build the baseline runtime against Splatoon 2's lifted
   `main`; HLE `sdk`/`subsdk0`/`subsdk1` by name. The baseline already HLEs `nn::os`, `fs`,
   `vi`, NVN, audio, input and time.
2. **Game definition.** Title `01003bc0000a0000` (USA base; update `01003BC0000A0800`
   v5.5.2 later), build ID `F18FF3CFCBAD0884D72ABBEB6C540D6B…`, 6 modules, heap/alias/pool
   sizes, 1280×720, 60 fps cap.
3. **First milestone: title / 2D UI at 720p60 on the Deck.** The title screen and PlayerMake
   exercise textures, formats, samplers and 2D draws without the plaza pass.
4. **Second: tutorial 3D room.** The old port already renders this; it is the smallest 3D
   scene.
5. **Third: plaza/stage 3D.** The old port's blocker; the TotK runtime's pipeline seed,
   command replay and memory path are the main assets here.
6. **Port the Splatoon-specific fixes** from the old port as the scene work reaches them:
   glyph-atlas packed rows and refresh, language-code byte order, scissored clears,
   R11G11B10F native, six-axis HLE, tail-call patch.

## Data and build boundary

- Game data lives outside the repository: exefs, RomFS, keys and saves are ignored.
- Generated C (361 MB for `main` alone) and build output are ignored; only the generator,
  runtime, patches and notes are committed.
- The baseline's `tools/build_from_xci.sh` is TotK-specific (XCI, v1.0.0, 3 modules). A
  Splatoon 2 wrapper will need to accept the NSP/ExeFS layout, 6 modules and the bases above.

## Open items

- `sdk` has 1,657 unhandled instructions (AES, halfword atomics, other SIMD). HLE is the
  first path; lifting it later needs those forms in the generator.
- `subsdk0`/`subsdk1` have 49 small gaps; HLE first, lift later if needed.
- The baseline runtime is single-game; Splatoon 2 needs a game definition and a module-loader
  change for 6 modules.
- The baseline HLE is TotK-shaped. Splatoon 2 import names overlap heavily, but the mapping
  must be checked function by function.
