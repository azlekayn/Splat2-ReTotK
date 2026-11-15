// nn::fs / nn::time / nn::mem implementation — host stand-ins.
#include "nn/services.hpp"

#include <chrono>
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <new>

namespace nn::fs {

namespace {

// RomFS mounts observed in the game: the literal name "content" at both MountRom call
// sites, plus the update/data mounts the SDK uses. Track them so Unmount is meaningful
// and a double mount can be detected.
std::mutex g_mountLock;
bool g_mounted[8] = {};
char g_mountNames[8][32] = {};

// The boot path mounts the game's RomFS. The cache the caller supplies is host memory;
// there is no image to mount, so the cache requirement is reported and the mount is
// recorded rather than backed by a filesystem. Serving actual file reads from RomFS is
// out of scope for the boot milestone and would need the .nca contents.
constexpr std::uint64_t kPlausibleRomCacheSize = 4ull * 1024 * 1024;

} // namespace

int QueryMountRomCacheSize(std::uint64_t *outSize) {
    if (outSize == nullptr) return -1;
    *outSize = kPlausibleRomCacheSize;
    return 0;
}

int MountRom(const char *name, void *cache, std::uint64_t cacheSize) {
    if (name == nullptr || cache == nullptr || cacheSize == 0) return -1;
    std::lock_guard<std::mutex> g(g_mountLock);
    // Reject an already-mounted name: mounting the same RomFS twice would give two
    // independent handles for one filesystem, which callers do not expect.
    for (int i = 0; i < 8; ++i) {
        if (g_mounted[i] && std::strcmp(g_mountNames[i], name) == 0) return -1;
    }
    for (int i = 0; i < 8; ++i) {
        if (!g_mounted[i]) {
            g_mounted[i] = true;
            std::snprintf(g_mountNames[i], sizeof(g_mountNames[i]), "%s", name);
            return 0;
        }
    }
    return -1; // mount table full
}

int Unmount(const char *name) {
    if (name == nullptr) return -1;
    std::lock_guard<std::mutex> g(g_mountLock);
    for (int i = 0; i < 8; ++i) {
        if (g_mounted[i] && std::strcmp(g_mountNames[i], name) == 0) {
            g_mounted[i] = false;
            g_mountNames[i][0] = '\0';
            return 0;
        }
    }
    return -1;
}

} // namespace nn::fs

namespace nn::time {

namespace {
// PosixTime is nanoseconds since the Unix epoch. The host clock is queried and scaled.
constexpr std::int64_t kNsPerSecond = 1'000'000'000;

// The module flag nn::time::Initialize / IsInitialized share with the clock path below.
// There is no clock service to start on a host: reading the clock is the only initialisation
// this backend performs, so the successful read records the same flag. Keeping ONE flag means
// IsInitialized() cannot disagree with the path that actually produces time values, which is
// what sead::DateTime::setNow's IsInitialized -> Initialize -> GetCurrentTime sequence assumes.
std::atomic<bool> g_timeInitialized{false};
} // namespace

void Initialize() {
    // Idempotent: the observed caller guards it with IsInitialized, and a second call from a
    // caller that does not must not disturb anything.
    g_timeInitialized.store(true, std::memory_order_relaxed);
}

bool IsInitialized() { return g_timeInitialized.load(std::memory_order_relaxed); }

void ResetForTesting() { g_timeInitialized.store(false, std::memory_order_relaxed); }

int StandardUserSystemClock::GetCurrentTime(PosixTime *outTime) {
    if (outTime == nullptr) return -1;
    const auto now = std::chrono::system_clock::now().time_since_epoch();
    *outTime = std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
    // The clock was successfully read, so the module is usable; record it (see
    // g_timeInitialized). Callers on the boot path call Initialize first anyway -- this only
    // keeps the flag honest for callers that do not.
    Initialize();
    return 0;
}

int StandardUserSystemClock::SetCurrentTime(PosixTime /*time*/) {
    // A guest cannot set the host clock; the call is accepted so boot code that
    // synchronises time does not treat it as fatal.
    return 0;
}

int ToCalendarTime(CalendarTime *outTime, CalendarAdditionalInfo *outInfo, PosixTime time) {
    if (outTime == nullptr) return -1;
    std::time_t secs = static_cast<std::time_t>(time / kNsPerSecond);
    std::tm tmv{};
#if defined(_WIN32)
    if (gmtime_s(&tmv, &secs) != 0) return -1;
#else
    if (gmtime_r(&secs, &tmv) == nullptr) return -1;
#endif
    outTime->year = static_cast<std::uint16_t>(tmv.tm_year + 1900);
    outTime->month = static_cast<std::uint8_t>(tmv.tm_mon + 1);
    outTime->day = static_cast<std::uint8_t>(tmv.tm_mday);
    outTime->hour = static_cast<std::uint8_t>(tmv.tm_hour);
    outTime->minute = static_cast<std::uint8_t>(tmv.tm_min);
    outTime->second = static_cast<std::uint8_t>(tmv.tm_sec);
    outTime->padding = 0;

    if (outInfo != nullptr) {
        outInfo->dayOfWeek = static_cast<std::uint32_t>(tmv.tm_wday);
        outInfo->dayOfYear = static_cast<std::uint32_t>(tmv.tm_yday);
        outInfo->gmtOffset = 0;
        std::memset(outInfo->name, 0, sizeof(outInfo->name));
    }
    return 0;
}

} // namespace nn::time

namespace nn::mem {

namespace {
// The allocator is embedded inline in game objects, so the host state lives inside the
// caller's storage rather than on the heap: one pointer to a host allocator plus a
// marker, which fits with room to spare.
struct AllocatorState {
    std::uint32_t magic;
    std::uint32_t ownsBuffer;
    std::uint32_t initialized; // 0 after a rejected Initialize; Allocate then refuses
    void *buffer;
    std::size_t size;
    std::size_t used;
};
constexpr std::uint32_t kAllocatorMagic = 0x414C4C43; // 'ALLC'
} // namespace

StandardAllocator::StandardAllocator() {
    static_assert(sizeof(AllocatorState) <= sizeof(StandardAllocator),
                  "StandardAllocator storage too small for host state");
    auto *s = reinterpret_cast<AllocatorState *>(mStorage);
    s->magic = kAllocatorMagic;
    s->ownsBuffer = 0;
    s->initialized = 1;
    s->buffer = nullptr;
    s->size = 0;
    s->used = 0;
}

StandardAllocator::StandardAllocator(void *buffer, std::size_t size) {
    auto *s = reinterpret_cast<AllocatorState *>(mStorage);
    s->magic = kAllocatorMagic;
    s->ownsBuffer = 0;
    s->initialized = 1;
    s->buffer = buffer;
    s->size = size;
    s->used = 0;
}

void StandardAllocator::Initialize(void *buffer, std::size_t size) {
    auto *s = reinterpret_cast<AllocatorState *>(mStorage);
    // Same rule as the sibling methods: an allocator whose constructor never ran has no state
    // to re-target, so refuse rather than inventing one. The game's global allocator is
    // constructed by nn::init::InitializeAllocator immediately before this call, so the magic
    // is always present on the observed path.
    if (s->magic != kAllocatorMagic) return;
    // Exactly the 3-argument constructor's state, applied to an existing object. The game
    // constructs its global allocator and then hands it the boot block, so re-targeting is the
    // documented use; `used` restarts because the new block has none of the old allocations.
    s->buffer = buffer;
    s->size = size;
    s->used = 0;
    // A rejected pair leaves the allocator UNINITIALISED rather than quietly falling back to
    // the host heap. The real function returns void, so there is nothing to report through;
    // making Allocate fail is the only observable, non-lying outcome. Allocations made before
    // a re-initialisation are not reclaimed -- the observed call happens once, immediately
    // after construction, so there is no earlier block to lose.
    s->initialized = (buffer != nullptr && size != 0) ? 1u : 0u;
}

StandardAllocator::~StandardAllocator() {
    auto *s = reinterpret_cast<AllocatorState *>(mStorage);
    if (s->magic != kAllocatorMagic) return;
    if (s->ownsBuffer != 0 && s->buffer != nullptr) std::free(s->buffer);
    s->magic = 0;
}

void *StandardAllocator::Allocate(std::size_t size, std::size_t alignment) {
    auto *s = reinterpret_cast<AllocatorState *>(mStorage);
    if (s->magic != kAllocatorMagic || s->initialized == 0 || size == 0) return nullptr;
    if (alignment < alignof(void *)) alignment = alignof(void *);
    // A backing buffer means a bump allocator over caller memory, matching the SDK's
    // 3-argument constructor form.
    if (s->buffer != nullptr) {
        const std::size_t aligned = (s->used + alignment - 1) & ~(alignment - 1);
        if (aligned + size > s->size) return nullptr;
        void *p = static_cast<unsigned char *>(s->buffer) + aligned;
        s->used = aligned + size;
        return p;
    }
    void *p = nullptr;
#if defined(_WIN32)
    p = _aligned_malloc(size, alignment);
#else
    if (posix_memalign(&p, alignment, size) != 0) return nullptr;
#endif
    return p;
}

void *StandardAllocator::Allocate(std::size_t size, void (*onAllocate)(void *), void *user) {
    void *p = Allocate(size, 8);
    if (p != nullptr && onAllocate != nullptr) onAllocate(user);
    return p;
}

void StandardAllocator::Free(void *ptr) {
    auto *s = reinterpret_cast<AllocatorState *>(mStorage);
    if (s->magic != kAllocatorMagic || s->initialized == 0 || ptr == nullptr) return;
    if (s->buffer != nullptr) return; // bump allocator: nothing to reclaim individually
    std::free(ptr);
}

} // namespace nn::mem

namespace nn::nifm {

namespace {
std::atomic<int> g_initializeCalls{0};
} // namespace

int Initialize() {
    // DOCUMENTED STUB. See PORT_WORKLIST.md line 144: nifm is the network interface manager,
    // reached even on the offline boot path, and is to be stubbed rather than implemented.
    // Nothing is enumerated, opened or configured here; the return value says "the call was
    // accepted", NOT "a network is available". The boot caller ignores it; the two callers
    // outside the closure (internetInitialize / networkInitialize) only reach this after the
    // boot milestone and will still find no service.
    g_initializeCalls.fetch_add(1, std::memory_order_relaxed);
    return 0;
}

int initializeCount() { return g_initializeCalls.load(std::memory_order_relaxed); }

} // namespace nn::nifm

namespace nn::oe {

namespace {
std::atomic<int> g_initializeCalls{0};
} // namespace

void Initialize() {
    // HOST NO-OP, deliberately. sead::PerformanceMgrNx::initialize's entire body forwards
    // here (0x7100e68c44 -> PTR_Initialize_7102f9a698, attributed to this symbol by
    // PORT_WORKLIST.md). The real service configures the operator environment; the host has
    // no equivalent, and the call site exposes no parameters or result to model, so inventing
    // a performance policy would be fabrication. The invocation is recorded so the forward is
    // observable and testable.
    g_initializeCalls.fetch_add(1, std::memory_order_relaxed);
}

int initializeCount() { return g_initializeCalls.load(std::memory_order_relaxed); }

} // namespace nn::oe
