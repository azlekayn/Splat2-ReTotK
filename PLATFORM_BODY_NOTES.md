# Reading the real platform bodies

`PLATFORM_LAYER_FOUND.md` gives the provider module and offset for every boot function.
This note records the first cross-check between those shipped bodies and the host
implementations in `port/`. It is a starting point, not a complete audit.

## Method

```bash
# Convert a decompressed NSO to an ELF with symbols (nso2elf emits .dynsym).
node tools/nso/nso2elf.mjs work/exefs/sdk.decompressed sdk.elf

# Address and size of a symbol.
readelf -sW sdk.elf | grep '_ZN2nn2os13GetSystemTickEv'
#   1972: 0000000000081b40     8 FUNC    GLOBAL DEFAULT    1 _ZN2nn2os13GetSystemTickEv

# Disassemble exactly that extent.
aarch64-linux-gnu-objdump -d --start-address=0x81b40 --stop-address=0x81b48 sdk.elf
```

Offsets are module-relative. Only `main` has the fixed analysis base `0x7100000000`.

## `nn::os::GetSystemTick` — exact, no change needed

`sdk` 0x81b40, 8 bytes:

```
81b40:  mrs  x0, cntpct_el0
81b44:  ret
```

The real function is the physical counter. On Switch `CNTFRQ` is 19.2 MHz; the port's
`GetSystemTick` runs a monotonic steady clock scaled by `192/10000`, i.e. the same 19.2 MHz
domain. The properties the 677 call sites need — monotonic and 19.2 MHz — are already met.

## `nn::mem::StandardAllocator` — the port differs, and it matters

`sdk`:

| Symbol | Offset | Size |
|---|---:|---:|
| `StandardAllocator(void*, unsigned long)` | 0x7bd4c | 0x36 |
| `StandardAllocator::Initialize(void*, unsigned long)` | 0x7bd70 | 0x8 (tail call) |
| `StandardAllocator::Allocate(unsigned long, unsigned long)` | 0x7becc | 0x240 |
| `StandardAllocator::Free(void*)` | 0x7bfc4 | 0x96 |

The real `Allocate` checks the initialised byte at `this+1`, obtains its allocator object
through a TLS/vtable call, takes the lock at `this+0x18`, and allocates from an internal
free-list. `Free` finds the owning allocator and tail-calls its free through the vtable.

The host `port/` implementation is a **bump allocator**: `Free` is a no-op for
buffer-backed storage, so reclaimed memory is never reused. That is a real semantic
difference, not an implementation detail. The first concrete follow-up is to port the
real body, or at least a free-list with the same reuse behaviour; the constructor and
`Initialize(buffer, size)` shape already match.

## `nvnBootstrapLoader` — shape is right

`subsdk0` 0xb35c4, 0x184 bytes. The real body checks a cached module/table pointer
(`adrp 0x1a6000 + 0x3a0`), calls `nvnBootstrapLoaderInternal` (0xb367c) when the cache is
empty, and returns a function pointer. It is a name→pointer resolver, not a jump table.

The port's `nvn::BootstrapLoader` has the same shape (host registrations → backed
`LoadCProcs` slots → null). `RegisterBootstrapProc` is the seam a real NVN backend plugs
into. Null is the documented fallback both binary call sites already test.

## `nn::vi::Initialize` — intentionally still a stub

`subsdk1` 0x2740, 0x1936 bytes. The real body creates and starts service objects,
mutexes, buffer queues and IPC proxies. The port only flips a flag, which is appropriate
until the service layer exists; the recovered body is the reference for the real
implementation.

## Next candidates

- `nn::os::AllocateMemoryBlock` (sdk 0x81bd0) and `QueryMemoryInfo` (0x7ee20) — the boot
  heap-sizing path.
- `nn::os::InitializeMutex` / `LockMutex` / `UnlockMutex` (sdk 0x80d40 / 0x80d94 /
  0x80e80) — the real recursion/thread-ownership semantics behind the port's host mutex.
- `nn::vi::OpenDefaultDisplay` / `CreateLayer` / `GetDisplayVsyncEvent` — the display
  boundary the port currently fakes with static handles.
- `nv::InitializeGraphics` (subsdk0 0xc8c4) — the graphics-heap handover.

None of this requires the port runtime; it is all module-relative disassembly of the
reader's own dump.
