# Splatoon 2 / TotK runtime handoff

State at the end of the 2026-11-14 session. Read this before continuing.

## Repositories and branches

| What | Where |
|---|---|
| Port repo (this one) | `azlekayn/Splat2-ReTotK` (GitHub) / `wingrepo/Splat2-ReTotK` (Forgejo) |
| Active branch | `retotk-baseline` |
| Runtime baseline | `Muhammad1259-sigma/totk-recomp` @ `a32f709`, MIT, vendored at `baseline/totk-recomp/` |
| Research/tooling repo | `bangmcpe3321/sp2decomp`; open PRs #3–#6 from `azlekayn/sp2decomp` |
| Old Splatoon 2 port | WonderRecomp lineage, `~/sp2port` on the Windows machine (not here) |

The baseline copy includes a generator fix: scalar `FADDP Sd, Vn.2S` is now handled. Without
it, Splatoon 2's `main` has 15 unhandled instructions.

## Persistent data (outside the repo)

Everything here is the user's own dump; do not commit it.

- `/mnt/SSD Storage/Games/Ports/Switch/Splat2/prod.keys`
- `/mnt/SSD Storage/Games/Ports/Switch/Splat2/work/base-nsp/exefs/` — `main`, `sdk`, `rtld`,
  `subsdk0..3`, `main.npdm` (extracted with nstool, ticket included)
- `/mnt/SSD Storage/Games/Ports/Switch/Splat2/work/base-nsp/romfs/` — 3.1 GB extracted RomFS
- `/mnt/SSD Storage/Games/Ports/Switch/Splat2/work/base-nsp/exefs/*.decompressed` — the
  Python-decompressed NSO images used for analysis
- `/mnt/SSD Storage/Games/Ports/Switch/Splat2/work/img/` — `tools/nso.py` images
  (`main.bin/json`, `sdk`, `subsdk*`)
- `/mnt/SSD Storage/Games/Ports/Switch/Splat2/work/gen-totk/` — generated C from the patched
  baseline (`main` 361 MB; `sdk` and `subsdk*` reports)
- `/mnt/SSD Storage/Games/Ports/Switch/Splat2/work/Splat2-ReTotK/` — persistent clone of this
  repo on `retotk-baseline`

## Lift coverage (baseline generator)

| Module | Functions | Instructions | Unhandled | Plan |
|---|---:|---:|---:|---|
| `main` | 114,172 | 5,261,347 | **0** | lift |
| `sdk` | 14,426 | 714,539 | 1,657 | HLE first (AES + halfword atomics) |
| `subsdk0` | 4,299 | 185,120 | 43 | HLE first |
| `subsdk1` | 385 | 13,656 | 6 | HLE first |
| `subsdk2` | 76 | 10,643 | **0** | lift later |
| `subsdk3` | 496 | 41,514 | **0** | lift later |

Module bases: `main 0x7100000000`, `sdk 0x7180000000`, `subsdk0 0x7200000000`,
`subsdk1 0x7280000000`, `subsdk2 0x7300000000`, `subsdk3 0x7380000000`.

Regenerate with the vendored baseline:

```bash
cd work/Splat2-ReTotK/baseline/totk-recomp
python3 tools/nso.py <exefs>/main /path/img/main
python3 tools/funcs.py /path/img/main /path/img/funcs_main.json
python3 tools/recomp/gen.py /path/img/main /path/img/funcs_main.json /path/gen/main
```

`python3` needs `lz4` and `capstone` (the baseline expects 5.0.9; the 5.0.9 wheel reports
5.0.7, which is harmless here). The 15 `faddp` misses are fixed in the vendored copy.

## Platform layer

The platform layer is in the dump; see `PLATFORM_LAYER_FOUND.md` and
`PLATFORM_BODY_NOTES.md` (this repo; also in the research repo). All 51 boot functions resolve:
39 in `sdk`, 6 `nn::vi` in `subsdk1`, 3 `nv` + `nvnBootstrapLoader` in `subsdk0`, and
`nn::init::InitializeAllocator` + `nvnLoadCProcs` in `main`. `main` has 784 imports; 772
resolve in the dump, and the only non-marker misses are the 8 `glslc*` functions.

## Build status

- Host: 22 cores, 30 GB RAM, clang 22, ninja, cmake, Podman.
- `engage-linux-build` container: clang/ninja/cmake, SDL3 shared, `libvpx.so` — no static
  `libvpx.a`/`libshaderc_combined.a`.
- XC2 AppImage sysroot has `llvm/sysroot/usr/lib/x86_64-linux-gnu/libvpx.a`; no shaderc.
- The baseline needs static `libvpx.a` + `libshaderc_combined.a` for a Vulkan build.
  `--null` still links `libvpx.a` but skips shaderc, so it is the fastest first smoke test.
- Deck target: build against the SteamRT/sniper sysroot (the XC2 `build-diag.sh` pattern),
  or the baseline's native build for a smoke test and a sniper build for the release.

## Next steps

1. **Null/headless boot.** Build the baseline runtime with `--null` against
   `work/gen-totk/main` and the XC2 `libvpx.a`; run with `TOTK_IMG=work/img`. Goal: reach
   `nnMain` and see which HLE functions are missing for Splatoon 2.
2. **Splatoon 2 game definition.** Title `01003bc0000a0000`, build ID
   `F18FF3CFCBAD0884D72ABBEB6C540D6B…`, six modules, heap/alias/pool, 1280×720/60.
3. **First visible milestone: title/2D UI at 720p60 on the Deck.** Then the tutorial 3D room,
   then the plaza 3D pass.
4. **HLE work.** Use the recovered 51 bodies to implement/fix `nn::os`, `nn::vi`, `nv`/`nvn`
   and the Splatoon 2 import names; the TotK runtime's HLE is the starting point.
5. **Port old-port fixes when the scenes reach them:** packed-row glyph atlas + refresh,
   language byte order, scissored clears, R11G11B10F, six-axis, tail-call patch.

## Boundaries

- No game data, keys, saves, generated C or built binaries in the repository.
- The baseline is MIT; keep attribution. LAS is not used.
- The user's rules for AI work apply: nothing installed on the host (Podman only), never
  print/copy keys, tell the user before a game window opens.
